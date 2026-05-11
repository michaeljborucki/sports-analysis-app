"""
Cache-mode control endpoints.

GET  /api/cache-mode          — current mode + snapshot availability + freshness
POST /api/cache-mode          — switch mode {mode: "live"|"latest"|"snapshot"}
POST /api/cache-snapshot      — capture the current cache.db into cache.snapshot.db
                                 (VACUUM INTO — atomic, compressed, safe mid-read)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..odds.books.coral33.fetcher import Coral33Fetcher
from ..odds.cache import OddsCache
from ..odds.cache_mode import CacheMode, CacheModeStore
from ..odds.fetcher import FetcherRegistry


class CacheModeStatus(BaseModel):
    mode: str
    snapshot_available: bool
    snapshot_captured_at: str | None = None
    snapshot_newest_row_at: str | None = None
    snapshot_row_count: int | None = None
    live_newest_row_at: str | None = None
    live_row_count: int | None = None


class CacheModeSetRequest(BaseModel):
    mode: str


class CacheSnapshotResponse(BaseModel):
    status: str
    path: str
    captured_at: str
    row_count: int


def _inspect_db(path: Path) -> tuple[int, str | None]:
    """Return (row_count, newest_fetched_at) for a given sqlite cache file."""
    if not path.exists():
        return 0, None
    try:
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute(
                "SELECT COUNT(*), MAX(fetched_at) FROM odds_snapshot"
            )
            row = cur.fetchone()
            return int(row[0] or 0), row[1]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0, None


def build_router(
    mode_store: CacheModeStore,
    cache: OddsCache,
    live_path: Path,
    snapshot_path: Path,
    fetcher: FetcherRegistry,
    coral33_fetcher: Coral33Fetcher,
) -> APIRouter:
    router = APIRouter()

    def _apply_mode(mode: CacheMode) -> None:
        """Apply mode side-effects: fetcher state + cache path."""
        if mode == CacheMode.LIVE:
            cache.path = live_path
            fetcher.start_all()
            coral33_fetcher.start_all()
        else:
            # LATEST or SNAPSHOT — stop both fetchers so nothing writes to the
            # cache underneath us.
            fetcher.stop_all()
            coral33_fetcher.stop_all()
            cache.path = snapshot_path if mode == CacheMode.SNAPSHOT else live_path

    @router.get("/api/cache-mode", response_model=CacheModeStatus)
    async def get_mode() -> CacheModeStatus:
        mode = mode_store.get()
        snap_mtime = (
            datetime.fromtimestamp(
                snapshot_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            if snapshot_path.exists()
            else None
        )
        snap_rows, snap_newest = _inspect_db(snapshot_path)
        live_rows, live_newest = _inspect_db(live_path)
        return CacheModeStatus(
            mode=mode.value,
            snapshot_available=snapshot_path.exists(),
            snapshot_captured_at=snap_mtime,
            snapshot_newest_row_at=snap_newest,
            snapshot_row_count=snap_rows or None,
            live_newest_row_at=live_newest,
            live_row_count=live_rows or None,
        )

    @router.post("/api/cache-mode", response_model=CacheModeStatus)
    async def set_mode(req: CacheModeSetRequest) -> CacheModeStatus:
        try:
            next_mode = CacheMode(req.mode)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"mode must be one of {[m.value for m in CacheMode]}",
            )
        if next_mode == CacheMode.SNAPSHOT and not snapshot_path.exists():
            raise HTTPException(
                status_code=400,
                detail="no snapshot available — POST /api/cache-snapshot first",
            )
        _apply_mode(next_mode)
        mode_store.set(next_mode)
        return await get_mode()

    @router.post("/api/cache-snapshot", response_model=CacheSnapshotResponse)
    async def capture_snapshot() -> CacheSnapshotResponse:
        """Capture the current live cache into the snapshot file. Uses SQLite
        VACUUM INTO — atomic, compressed, and safe to run while the source is
        being read. Does NOT change the current mode."""
        if not live_path.exists():
            raise HTTPException(status_code=400, detail="live cache does not exist yet")
        # Stop fetchers momentarily so we don't capture a partial write cycle.
        was_live = mode_store.get() == CacheMode.LIVE
        if was_live:
            fetcher.stop_all()
            coral33_fetcher.stop_all()
        try:
            if snapshot_path.exists():
                snapshot_path.unlink()
            conn = sqlite3.connect(live_path)
            try:
                conn.execute(f"VACUUM INTO '{snapshot_path}'")
            finally:
                conn.close()
        finally:
            if was_live:
                fetcher.start_all()
                coral33_fetcher.start_all()
        rows, _newest = _inspect_db(snapshot_path)
        return CacheSnapshotResponse(
            status="captured",
            path=str(snapshot_path),
            captured_at=datetime.now(timezone.utc).isoformat(),
            row_count=rows,
        )

    return router
