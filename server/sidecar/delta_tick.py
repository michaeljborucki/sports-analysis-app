"""Autonomous Kelly-delta re-fire scheduler.

Runs every 60 seconds via APScheduler. For each active signal where
commence_time > now:

  1. Resolve ev_row_id → (current LegSpec, current kelly_full_pct).
  2. Compute current target = kelly_fraction × kelly_full_pct × bankroll_at_arm.
  3. delta = current_target - total_placed.
  4. If delta >= FLOOR ($30), enqueue a placement job for `delta` dollars.

Bails early when sidecar_mode is 'off' so the kill-switch halts both
user-triggered and autonomous activity.

Concurrency
-----------
A per-ev_row_id ``asyncio.Lock`` (held only for the duration of one
signal's compute + fire step) prevents the next tick from racing a
still-in-flight placement: the previous job must finish writing
``update_total_placed`` before the next tick reads ``total_placed``,
otherwise the same delta would fire twice."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
import weakref
from pathlib import Path

from server.sidecar import active_signals
from server.sidecar.factory import get_orchestrator
from server.sidecar.models import SidecarPlaceRequest
from server.sidecar.resolve import resolve_ev_row_to_leg
from server.sidecar.settings import KellyFraction, kelly_to_pct
from server.sidecar.splitter import FLOOR


logger = logging.getLogger(__name__)

# WeakValueDictionary so locks self-evict once no caller holds them.
# Without this, the dict grows unboundedly over uptime — every ev_row_id
# we've ever ticked stays here forever (~200B/entry, never reclaimed).
# As long as ANY caller holds a strong ref to the lock (i.e. inside
# `async with lock`), it stays in the dict; once everyone drops it, the
# next GC cycle reclaims it. asyncio.Lock is weak-referenceable.
_signal_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _get_lock(ev_row_id: str) -> asyncio.Lock:
    """Fetch-or-create the per-signal lock. The returned strong ref keeps
    the lock alive in the dict for the duration of the caller's
    `async with`; once dropped, the WeakValueDictionary lets it go."""
    lock = _signal_locks.get(ev_row_id)
    if lock is None:
        lock = asyncio.Lock()
        _signal_locks[ev_row_id] = lock
    return lock


async def run_delta_tick(db_path: Path) -> None:
    """One pass: scan active signals, fire deltas where applicable."""
    orchestrator = get_orchestrator()
    if orchestrator.mode == "off":
        return

    conn = sqlite3.connect(str(db_path))
    try:
        signals = active_signals.list_active(conn)
    finally:
        conn.close()

    for sig in signals:
        await _process_one(sig, db_path, orchestrator)


async def _process_one(sig, db_path: Path, orchestrator) -> None:
    """Per-signal lock + delta compute + maybe fire.

    The asyncio.Lock prevents the next tick from firing a duplicate
    before the previous job's ``total_placed`` write commits."""
    lock = _get_lock(sig.ev_row_id)
    async with lock:
        resolved = resolve_ev_row_to_leg(sig.ev_row_id)
        if resolved is None:
            # Row dropped out of /api/ev — skip this tick.
            conn = sqlite3.connect(str(db_path))
            try:
                active_signals.mark_checked(
                    conn, sig.ev_row_id, last_target=None, fired=False,
                )
            finally:
                conn.close()
            return

        leg, kelly_full_pct = resolved
        # All targets are rounded to the nearest $5 (compute_kelly_target
        # is the canonical helper used by both this tick and the
        # user-triggered orchestrator).
        from server.sidecar.settings import compute_kelly_target, round_stake_to_5
        current_target = compute_kelly_target(
            KellyFraction(sig.kelly_fraction),
            kelly_full_pct,
            sig.bankroll_at_arm,
        )
        delta = round_stake_to_5(current_target - sig.total_placed)

        conn = sqlite3.connect(str(db_path))
        try:
            if delta < FLOOR:
                active_signals.mark_checked(
                    conn, sig.ev_row_id,
                    last_target=current_target, fired=False,
                )
                return

            logger.info(
                "delta_tick: firing $%.0f delta on %s (was placed $%.0f, "
                "target $%.0f)",
                delta, sig.ev_row_id, sig.total_placed, current_target,
            )
            active_signals.mark_checked(
                conn, sig.ev_row_id,
                last_target=current_target, fired=True,
            )
        finally:
            conn.close()

        # Fire a fresh placement job for `delta` dollars. The orchestrator
        # handles audit, SSE, splitter, the works.
        req = SidecarPlaceRequest(
            ev_row_id=sig.ev_row_id,
            ev_leg=leg,
            kelly_full_pct=kelly_full_pct,
            kelly_fraction=KellyFraction(sig.kelly_fraction),
            bankroll=sig.bankroll_at_arm,
            trigger_source="delta_tick",
            # Bypass the orchestrator's Kelly recompute — we already
            # computed the dollar delta, the splitter should fill THAT.
            stake_override_dollars=int(delta),
        )
        await orchestrator.handle_place(req, uuid.uuid4().hex)
