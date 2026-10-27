"""GET /api/debug/memory — cheap, read-only memory counters.

Built to chase a slow leak (the API reached a 7GB footprint after ~44h on
an 8GB laptop): every number here is an O(1) attribute read or a len(), so
it is safe to poll on a schedule. No gc.get_objects() walk — on a 500k-row
snapshot that alone stalls the event loop for seconds.
"""
from __future__ import annotations

import asyncio
import ctypes
import gc
import os
import struct
import sys
import threading
import time
from typing import Any

from fastapi import APIRouter

from ..odds import bettingdb_source as bdb
from ..odds import normalize


def _process_memory() -> dict[str, Any]:
    """Physical footprint + resident size via proc_pid_rusage (macOS) —
    the same number `footprint <pid>` and Activity Monitor report."""
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = ctypes.create_string_buffer(512)
        if lib.proc_pid_rusage(os.getpid(), 2, buf) != 0:   # RUSAGE_INFO_V2
            return {}
        resident, footprint = struct.unpack_from("<QQ", buf.raw, 64)
        return {
            "footprint_mb": round(footprint / 2**20),
            "resident_mb": round(resident / 2**20),
        }
    except (OSError, AttributeError):
        return {}


def _safe(fn) -> Any:
    try:
        return fn()
    except Exception as exc:   # one broken probe must not hide the rest
        return {"error": f"{type(exc).__name__}: {exc}"}


def build_router(
    cache, snapshot_service, kalshi_fetcher, polymarket_fetcher, novig_fetcher,
    polymarket_us_fetcher=None,
) -> APIRouter:
    router = APIRouter()
    started = time.time()

    def _snapshot() -> dict[str, Any]:
        snap = snapshot_service.current
        if snap is None:
            return {"built": False}
        return {
            "generation": snap.generation,
            "rows": len(snap.rows),
            "games": len(snap.games),
            "system_rows": len(snap.system_rows),
            "derived_entries": len(snap.derived),
            "age_s": snapshot_service.age_seconds,
            "overlays_published": snapshot_service.overlays_published,
            "last_build": getattr(snapshot_service, "last_build", {}),
        }

    def _novig() -> dict[str, Any] | None:
        stream = novig_fetcher._stream
        if stream is None:
            return None
        # state entries for markets no longer live are what a reconnect
        # strands (state isn't cleared by _drop_all).
        return {
            "state_markets": len(stream.state),
            "live_markets": len(stream._live),
            "subscribed_events": len(stream._subscribed),
            "reconnects": stream.reconnects,
        }

    @router.get("/api/debug/memory")
    async def debug_memory() -> dict[str, Any]:
        return {
            "uptime_s": round(time.time() - started),
            "process": _process_memory(),
            "gc": {
                "counts": gc.get_count(),
                "frozen": gc.get_freeze_count(),
                "garbage": len(gc.garbage),
            },
            "threads": threading.active_count(),
            "asyncio_tasks": len(asyncio.all_tasks()),
            "snapshot": _safe(_snapshot),
            # Unbounded fire-and-forget write queue (OddsCache.upsert_nowait):
            # a backlog that keeps climbing here is queued row copies in RAM.
            "cache_writer_queue": _safe(lambda: cache._writer._work_queue.qsize()),
            "mapped_rows_memo": _safe(lambda: {
                "entries": len(bdb._MAPPED_ROWS_CACHE),
                "rows": sum(len(r) for _, r in bdb._MAPPED_ROWS_CACHE.values()),
            }),
            "lru_caches": {
                name: fn.cache_info().currsize
                for name, fn in (
                    ("norm_ts", bdb._norm_ts),
                    ("encode_outcome_name", bdb._encode_outcome_name_cached),
                    ("parse_iso", normalize._parse_iso_cached),
                )
            },
            "kalshi": _safe(kalshi_fetcher.debug_stats),
            "polymarket": _safe(polymarket_fetcher.debug_stats),
            "polymarket_us": (
                _safe(polymarket_us_fetcher.debug_stats)
                if polymarket_us_fetcher is not None else None
            ),
            "novig_stream": _safe(_novig),
            "python": sys.version.split()[0],
        }

    return router
