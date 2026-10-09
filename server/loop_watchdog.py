"""Event-loop stall diagnostics. Log-only — changes no behavior.

A coroutine stamps a heartbeat every 100ms; a daemon thread checks it and,
when the loop has been unresponsive for STALL_MS, logs the loop thread's
current Python stack once per stall. Full (gen-2) GC passes are timed via
`gc.callbacks` and logged when slow, since a gen-2 pass over a few hundred
thousand row dicts freezes every thread, the loop included.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import sys
import threading
import time
import traceback

logger = logging.getLogger(__name__)

TICK_S = 0.1
STALL_MS = 300.0
FREEZE_MS = 1000.0
SLOW_GC_MS = 100.0

_last_beat = time.monotonic()
_gc_started: float | None = None


def _gc_callback(phase: str, info: dict) -> None:
    global _gc_started
    if info.get("generation") != 2:
        return
    if phase == "start":
        _gc_started = time.perf_counter()
    elif _gc_started is not None:
        ms = (time.perf_counter() - _gc_started) * 1000
        _gc_started = None
        if ms >= SLOW_GC_MS:
            logger.warning(
                "loop-watchdog: gen2 GC %.0fms collected=%s objects=%d",
                ms, info.get("collected"), len(gc.get_objects(generation=2)),
            )


def _all_thread_tops(depth: int = 4) -> str:
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for tid, frame in sys._current_frames().items():
        frames = traceback.extract_stack(frame)[-depth:]
        where = " <- ".join(
            f"{f.name}({f.filename.rsplit('/', 1)[-1]}:{f.lineno})"
            for f in reversed(frames)
        )
        out.append(f"  [{names.get(tid, tid)}] {where}")
    return "\n".join(out)


def _watch(loop_thread_id: int, stop: threading.Event) -> None:
    reported = False
    expected = time.monotonic() + TICK_S
    while not stop.wait(TICK_S):
        # The watchdog thread itself oversleeping means the whole process
        # was frozen (GIL held in C, or the OS throttled/suspended us).
        oversleep_ms = (time.monotonic() - expected) * 1000
        expected = time.monotonic() + TICK_S
        if oversleep_ms >= FREEZE_MS:
            logger.warning(
                "loop-watchdog: process froze %.0fms (gc running=%s); threads now:\n%s",
                oversleep_ms, _gc_started is not None, _all_thread_tops(),
            )
        lag_ms = (time.monotonic() - _last_beat) * 1000
        if lag_ms < STALL_MS:
            reported = False
            continue
        if reported:
            continue
        reported = True
        frame = sys._current_frames().get(loop_thread_id)
        stack = "".join(traceback.format_stack(frame, limit=25)) if frame else "<none>"
        logger.warning(
            "loop-watchdog: loop stalled %.0fms (gc running=%s); loop thread stack:\n%s",
            lag_ms, _gc_started is not None, stack,
        )


async def run() -> None:
    """Heartbeat coroutine; start with create_task in the app lifespan."""
    global _last_beat
    stop = threading.Event()
    gc.callbacks.append(_gc_callback)
    threading.Thread(
        target=_watch, args=(threading.get_ident(), stop),
        name="loop-watchdog", daemon=True,
    ).start()
    try:
        while True:
            _last_beat = time.monotonic()
            await asyncio.sleep(TICK_S)
    finally:
        stop.set()
        if _gc_callback in gc.callbacks:
            gc.callbacks.remove(_gc_callback)
