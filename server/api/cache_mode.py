"""
Cache-mode control endpoints.

GET  /api/cache-mode          — current mode + snapshot availability + freshness
POST /api/cache-mode          — switch mode {mode: "live"|"latest"|"snapshot"}
POST /api/cache-snapshot      — capture the current cache.db into cache.snapshot.db
                                 (VACUUM INTO — atomic, compressed, safe mid-read)
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..odds.books.coral33.fetcher import Coral33Fetcher
from ..odds.books.kalshi.fetcher import KalshiFetcher
from ..odds.books.polymarket.fetcher import PolymarketFetcher
from ..odds.books.novig.fetcher import NovigFetcher
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


def _vacuum_into(src: Path, dest: Path) -> None:
    """Blocking `VACUUM INTO` copy of the live cache (seconds on a large DB)."""
    conn = sqlite3.connect(src)
    try:
        conn.execute(f"VACUUM INTO '{dest}'")
    finally:
        conn.close()


logger = logging.getLogger(__name__)

_INSPECT_TTL_S = 30.0
_inspect_memo: dict[Path, tuple[float, tuple, tuple[int, str | None]]] = {}
_inspect_lock = threading.Lock()
_inspect_refreshing: set[Path] = set()


def _file_stamp(path: Path, track_changes: bool) -> tuple | None:
    if not track_changes:
        return None
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _refresh_inspect(path: Path, stamp: tuple | None) -> None:
    """Background worker: recompute one file's numbers, then publish."""
    try:
        result = _inspect_db_uncached(path)
        with _inspect_lock:
            _inspect_memo[path] = (time.monotonic(), stamp, result)
    except Exception:
        logger.exception("cache-mode inspect refresh failed for %s", path)
    finally:
        with _inspect_lock:
            _inspect_refreshing.discard(path)


def _inspect_db(path: Path, *, track_changes: bool = False) -> tuple[int, str | None]:
    """Memoized, stale-while-revalidate `_inspect_db_uncached`.

    The COUNT(*) scans take 1-4.5s on the large cache files and run on every
    /api/cache-mode poll, but the numbers are display-only (cache-mode
    dropdown). So:
      - fresh memo (< 30s, same file stamp)  -> returned as-is;
      - TTL expired                          -> the LAST KNOWN value is
        returned immediately and one background thread recomputes it;
      - no memo yet, or `track_changes` and the file's size/mtime changed
                                             -> computed inline.
    `track_changes` is for the snapshot file, which only changes on a fresh
    capture — that must report the new row count at once (POST
    /api/cache-snapshot reads it right after VACUUM INTO), so a changed
    stamp still recomputes inline, exactly as before. The live cache
    changes on nearly every write, so it relies on the TTL alone."""
    stamp = _file_stamp(path, track_changes)
    now = time.monotonic()
    with _inspect_lock:
        hit = _inspect_memo.get(path)
        if hit is not None and hit[1] == stamp:
            if now - hit[0] >= _INSPECT_TTL_S and path not in _inspect_refreshing:
                _inspect_refreshing.add(path)
                threading.Thread(
                    target=_refresh_inspect,
                    args=(path, stamp),
                    name="cache-mode-inspect",
                    daemon=True,
                ).start()
            return hit[2]
    result = _inspect_db_uncached(path)
    with _inspect_lock:
        _inspect_memo[path] = (time.monotonic(), stamp, result)
    return result


def _inspect_db_uncached(path: Path) -> tuple[int, str | None]:
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
    clv_scheduler=None,
    clv_capture_tick=None,
    wager_log_refresh_tick=None,
    kalshi_fetcher: KalshiFetcher | None = None,
    polymarket_fetcher: PolymarketFetcher | None = None,
    novig_fetcher: NovigFetcher | None = None,
) -> APIRouter:
    router = APIRouter()

    def _apply_mode(mode: CacheMode) -> None:
        """Apply mode side-effects: fetcher state + cache path + CLV
        capture scheduler + wager-log refresh scheduler."""
        if mode == CacheMode.LIVE:
            cache.path = live_path
            fetcher.start_all()
            coral33_fetcher.start_all()
            if kalshi_fetcher is not None:
                kalshi_fetcher.start_all()
            if polymarket_fetcher is not None:
                polymarket_fetcher.start_all()
            if novig_fetcher is not None:
                novig_fetcher.start_all()
            # CLV capture follows the same gate as the fetchers — it only
            # makes sense to devig a live cache (LATEST/SNAPSHOT are
            # frozen). Without this, flipping LATEST→LIVE at runtime
            # would leave the scheduler off until the next restart.
            if clv_scheduler is not None and clv_capture_tick is not None:
                if not clv_scheduler.running:
                    clv_scheduler.start()
                clv_scheduler.add_job(
                    clv_capture_tick,
                    trigger="interval",
                    seconds=60,
                    id="clv_capture",
                    replace_existing=True,
                    max_instances=1,
                )
            # Wager-log refresh — same gate (must be LIVE to hit
            # Coral33's API). 30-min cadence keeps newly-placed bets
            # surfacing on /accounts within a sensible window.
            if (
                clv_scheduler is not None
                and wager_log_refresh_tick is not None
            ):
                if not clv_scheduler.running:
                    clv_scheduler.start()
                clv_scheduler.add_job(
                    wager_log_refresh_tick,
                    trigger="interval",
                    minutes=30,
                    id="wager_log_refresh",
                    replace_existing=True,
                    max_instances=1,
                )
        else:
            # LATEST or SNAPSHOT — stop fetchers so nothing writes to the
            # cache underneath us.
            fetcher.stop_all()
            coral33_fetcher.stop_all()
            if kalshi_fetcher is not None:
                kalshi_fetcher.stop_all()
            if polymarket_fetcher is not None:
                polymarket_fetcher.stop_all()
            if novig_fetcher is not None:
                novig_fetcher.stop_all()
            cache.path = snapshot_path if mode == CacheMode.SNAPSHOT else live_path
            if clv_scheduler is not None:
                for job_id in ("clv_capture", "wager_log_refresh"):
                    try:
                        clv_scheduler.remove_job(job_id)
                    except Exception:
                        pass  # job didn't exist; nothing to remove

    @router.get("/api/cache-mode", response_model=CacheModeStatus)
    # Sync on purpose — see the note on /api/health. `_inspect_db` does a
    # COUNT(*) full scan over cache.db AND cache.snapshot.db; on the event
    # loop that blocked every concurrent request behind it.
    def get_mode() -> CacheModeStatus:
        mode = mode_store.get()
        snap_mtime = (
            datetime.fromtimestamp(
                snapshot_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            if snapshot_path.exists()
            else None
        )
        snap_rows, snap_newest = _inspect_db(snapshot_path, track_changes=True)
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
        return await asyncio.to_thread(get_mode)

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
            if kalshi_fetcher is not None:
                kalshi_fetcher.stop_all()
            if polymarket_fetcher is not None:
                polymarket_fetcher.stop_all()
            if novig_fetcher is not None:
                novig_fetcher.stop_all()
        try:
            if snapshot_path.exists():
                snapshot_path.unlink()
            await asyncio.to_thread(_vacuum_into, live_path, snapshot_path)
        finally:
            if was_live:
                fetcher.start_all()
                coral33_fetcher.start_all()
                if kalshi_fetcher is not None:
                    kalshi_fetcher.start_all()
                if polymarket_fetcher is not None:
                    polymarket_fetcher.start_all()
                if novig_fetcher is not None:
                    novig_fetcher.start_all()
        rows, _newest = await asyncio.to_thread(
            _inspect_db, snapshot_path, track_changes=True,
        )
        return CacheSnapshotResponse(
            status="captured",
            path=str(snapshot_path),
            captured_at=datetime.now(timezone.utc).isoformat(),
            row_count=rows,
        )

    return router
