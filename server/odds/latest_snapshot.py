"""Application-scoped, normalized view of the latest odds."""
from __future__ import annotations

import asyncio
import gc
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, TypeVar

from starlette.concurrency import run_in_threadpool

from .normalize import rows_to_games_with_non_prop


logger = logging.getLogger(__name__)

# Direct-book overlay cadence (betting_db mode). The full rebuild re-reads
# ~235k betting-db rows every 60s; the directly-fed books (novig, kalshi,
# polymarket, coral33 — a few thousand rows, some streamed in real time)
# are re-merged this often, regrouping only the games whose rows moved.
OVERLAY_INTERVAL_S = float(os.environ.get("SNAPSHOT_OVERLAY_SECONDS", "5"))
# A subprocess build slower than this is killed and that round falls back
# to the in-process build.
SUBPROCESS_TIMEOUT_S = float(os.environ.get("SNAPSHOT_SUBPROCESS_TIMEOUT_S", "240"))
_SYSTEM_SPORTS = frozenset({"mlb", "ncaaf", "nfl"})
_SYSTEM_MARKETS = frozenset({"h2h", "spreads", "totals"})


@dataclass
class _OverlayBase:
    """What the overlay needs from the last full build."""
    base_by_event: dict[str, list[dict]]        # betting-db rows per event
    direct_sig: dict[str, tuple] = field(default_factory=dict)


def _is_system_row(row: dict) -> bool:
    return row["sport_key"] in _SYSTEM_SPORTS and row["market_key"] in _SYSTEM_MARKETS


def _direct_signature(rows: list[dict]) -> tuple:
    """Order-independent identity of one event's direct-book rows: a quote
    appearing, vanishing, or changing price, size or wager type re-prices
    the game. `fetched_at` is deliberately left out — streamed books
    re-stamp unchanged quotes every few minutes, and regrouping a 6k-row
    game just to move a timestamp is what made the overlay expensive. The
    60s full rebuild still refreshes every timestamp, as before."""
    return tuple(sorted(
        (r["bookmaker_key"], r["market_key"], r["outcome_name"],
         str(r.get("outcome_point")), r["price_american"],
         r.get("max_stake_dollars"), r.get("wager_type"))
        for r in rows
    ))


def _group_by_event(rows) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["event_id"], []).append(r)
    return out


@dataclass(frozen=True)
class OddsSnapshot:
    generation: int
    built_at: datetime
    source_version: tuple
    rows: tuple[dict, ...]
    games: tuple[dict, ...]
    non_prop_games: tuple[dict, ...]
    non_prop_games_by_sport: Mapping[str, tuple[dict, ...]]
    system_rows: tuple[dict, ...]
    # Generation-scoped cache of values derived purely from this snapshot's
    # data (see `snapshot_memo`). Each overlay/rebuild publishes a new
    # OddsSnapshot object, so entries can never outlive their generation.
    derived: dict[str, Any] = field(
        default_factory=dict, compare=False, repr=False,
    )
    derived_lock: Any = field(
        default_factory=threading.RLock, compare=False, repr=False,
    )


_T = TypeVar("_T")


def snapshot_memo(snapshot: Any, name: str, compute: Callable[[], _T]) -> _T:
    """Compute `name` at most once per snapshot generation.

    `compute` must depend only on the snapshot's (immutable) data. Concurrent
    callers block on the per-snapshot lock rather than racing to compute the
    same value twice. Objects without the memo slots (test doubles) just
    compute every time."""
    derived = getattr(snapshot, "derived", None)
    lock = getattr(snapshot, "derived_lock", None)
    if not isinstance(derived, dict) or lock is None:
        return compute()
    with lock:
        if name not in derived:
            derived[name] = compute()
        return derived[name]


_BuildResult = tuple[
    tuple[dict, ...],                    # rows
    tuple[dict, ...],                    # games
    tuple[dict, ...],                    # non_prop_games
    Mapping[str, tuple[dict, ...]],      # non_prop_games_by_sport
    tuple[dict, ...],                    # system_rows
    datetime,                            # built_at
    "_OverlayBase | None",
]


def merge_betting_db(cache: Any) -> tuple[list[dict], list[dict], list[dict]]:
    """`(merged, base, direct)` — the same merge as bettingdb_source.all_current,
    with the two halves kept apart so the overlay can re-merge just the direct
    books. `merged` is base (minus rows a direct book owns) then direct, in
    that order. Shared by the in-process build and the build subprocess."""
    from . import bettingdb_source as bdb
    base = bdb._mapped_rows(None)
    direct = bdb._direct_book_rows(cache)
    direct_pks = {bdb._pk(r) for r in direct}
    merged = [
        r for r in base
        if r["bookmaker_key"] not in bdb.DIRECT_BOOK_KEYS
        or bdb._pk(r) not in direct_pks
    ]
    merged.extend(direct)
    return merged, base, direct


def direct_signatures(direct: list[dict]) -> dict[str, tuple]:
    return {e: _direct_signature(rs) for e, rs in _group_by_event(direct).items()}


def finish_build(
    rows: tuple[dict, ...],
    all_games: list[dict],
    non_prop_list: list[dict],
    built_at: datetime,
    overlay_base: "_OverlayBase | None",
) -> _BuildResult:
    games = tuple(all_games)
    non_prop_games = tuple(non_prop_list)
    by_sport: dict[str, list[dict]] = {}
    for game in non_prop_games:
        by_sport.setdefault(game["sport_key"], []).append(game)
    non_prop_games_by_sport = MappingProxyType({
        sport: tuple(sport_games) for sport, sport_games in by_sport.items()
    })
    system_rows = tuple(row for row in rows if _is_system_row(row))
    return (
        rows,
        games,
        non_prop_games,
        non_prop_games_by_sport,
        system_rows,
        built_at,
        overlay_base,
    )


class LatestOddsSnapshotService:
    """Build one odds view and coalesce concurrent readers onto it."""

    def __init__(
        self,
        cache: Any,
        *,
        refresh_interval_seconds: float = 60.0,
        hard_stale_seconds: float = 90.0,
        build_in_subprocess: bool = False,
    ) -> None:
        self._cache = cache
        self._refresh_interval_seconds = refresh_interval_seconds
        self._hard_stale_seconds = hard_stale_seconds
        self._current: OddsSnapshot | None = None
        self._build_task: asyncio.Task[OddsSnapshot] | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None
        self._last_build_started = 0.0
        self._overlay_base: _OverlayBase | None = None
        self._overlay_task: asyncio.Task[None] | None = None
        self.overlays_published = 0
        # betting_db mode only: build in a fresh spawned process per round
        # (see snapshot_worker.py). Off for tests / native mode.
        self._build_in_subprocess = build_in_subprocess
        self._pool: ProcessPoolExecutor | None = None
        self.last_build: dict[str, Any] = {}

    @property
    def current(self) -> OddsSnapshot | None:
        return self._current

    @property
    def refreshing(self) -> bool:
        return self._build_task is not None and not self._build_task.done()

    @property
    def running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def age_seconds(self) -> float | None:
        if self._current is None:
            return None
        return max(
            0.0,
            (datetime.now(timezone.utc) - self._current.built_at).total_seconds(),
        )

    @property
    def is_hard_stale(self) -> bool:
        age = self.age_seconds
        return age is None or age > self._hard_stale_seconds

    async def get(self) -> OddsSnapshot:
        source_version = self._cache.read_version
        if self._current is not None and self._current.source_version == source_version:
            return self._current
        if self._current is not None:
            if self._refresh_due:
                await self._ensure_refresh(source_version)
            return self._current
        task = await self._ensure_refresh(source_version)
        return await asyncio.shield(task)

    async def _ensure_refresh(
        self, source_version: tuple,
    ) -> asyncio.Future[OddsSnapshot]:
        async with self._lock:
            if self._current is not None and self._current.source_version == source_version:
                completed = asyncio.get_running_loop().create_future()
                completed.set_result(self._current)
                return completed
            if self._build_task is None or self._build_task.done():
                self._build_task = asyncio.create_task(
                    self._build(source_version)
                )
            return self._build_task

    async def wait_until_idle(self) -> None:
        task = self._build_task
        if task is not None:
            await asyncio.shield(task)

    async def start(self) -> None:
        if self.running:
            return
        await self.get()
        self._loop_task = asyncio.create_task(self._refresh_loop())
        self._overlay_task = asyncio.create_task(self._overlay_loop())

    async def stop(self) -> None:
        if self._overlay_task is not None:
            self._overlay_task.cancel()
            self._overlay_task = None
        self._shutdown_pool(kill=True)
        task = self._loop_task
        self._loop_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval_seconds)
            age = self.age_seconds
            if (
                self._current is None
                or self._current.source_version != self._cache.read_version
                # Backstop: never let the full (betting-db) build age past two
                # intervals, whatever the version bookkeeping says.
                or (age is not None and age >= 2 * self._refresh_interval_seconds)
            ):
                await self._ensure_refresh(self._cache.read_version)

    @property
    def _refresh_due(self) -> bool:
        return (
            time.monotonic() - self._last_build_started
            >= self._refresh_interval_seconds
        )

    async def _build(self, source_version: tuple) -> OddsSnapshot:
        started = time.perf_counter()
        self._last_build_started = time.monotonic()
        try:
            (
                rows,
                games,
                non_prop_games,
                non_prop_games_by_sport,
                system_rows,
                built_at,
                overlay_base,
            ) = await self._build_result()
            generation = (
                1 if self._current is None else self._current.generation + 1
            )
            # The database can change while a large snapshot is being read.
            # Publishing the version observed after the read prevents an
            # immediate redundant rebuild of effectively the same data.
            source_version = self._cache.read_version
            snapshot = OddsSnapshot(
                generation=generation,
                built_at=built_at,
                source_version=source_version,
                rows=rows,
                games=games,
                non_prop_games=non_prop_games,
                non_prop_games_by_sport=non_prop_games_by_sport,
                system_rows=system_rows,
            )
            self._current = snapshot
            self._overlay_base = overlay_base
            self._last_error = None
            # The snapshot is long-lived; move everything allocated so far
            # into the permanent generation so gen-2 GC passes stop
            # re-traversing ~200k row dicts (measured 120-990ms full passes,
            # every ~9s, freezing the event loop and collecting ~nothing).
            # Frozen objects are still freed by refcount when released — but
            # never by the cycle collector, so unfreeze and collect first:
            # a bare freeze pinned every pending cycle (httpx, asyncio,
            # threadpool garbage) forever, leaking ~1.2GB/hour. One full
            # pass a minute instead of every ~9s.
            gc.unfreeze()
            gc.collect()
            gc.freeze()
            logger.info(
                "odds snapshot published generation=%d rows=%d games=%d "
                "build_ms=%.1f",
                generation,
                len(rows),
                len(games),
                (time.perf_counter() - started) * 1000,
            )
            return snapshot
        except Exception as exc:
            self._last_error = str(exc).strip() or type(exc).__name__
            logger.exception("odds snapshot refresh failed")
            if self._current is not None:
                return self._current
            raise

    async def _build_result(self) -> _BuildResult:
        from .cache import _odds_source
        if self._build_in_subprocess and _odds_source() == "betting_db":
            try:
                return await self._build_via_subprocess()
            except Exception:
                logger.exception(
                    "odds snapshot subprocess build failed; building in-process"
                )
                self._shutdown_pool(kill=True)
        started = time.perf_counter()
        result = await run_in_threadpool(self._build_sync)
        self.last_build = {
            "mode": "in_process",
            "total_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        return result

    async def _build_via_subprocess(self) -> _BuildResult:
        from . import snapshot_worker
        if self._pool is None:
            # spawn, not fork: a forked copy of this process (threads, open
            # sockets, the event loop) is unsafe. One task per child, so each
            # build's memory goes back to the OS when the child exits.
            self._pool = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
                max_tasks_per_child=1,
            )
        started = time.perf_counter()
        payload = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                self._pool, snapshot_worker.build_payload, str(self._cache.path),
            ),
            timeout=SUBPROCESS_TIMEOUT_S,
        )
        received = time.perf_counter()
        # Read before assembling: _assemble_payload clears the payload.
        child_ms = {k: round(v, 1) for k, v in payload["child_timings_ms"].items()}
        chunks = len(payload["row_chunks"]) + len(payload["game_chunks"])
        result = await run_in_threadpool(self._assemble_payload, payload)
        self.last_build = {
            "mode": "subprocess",
            "child_ms": child_ms,
            "subprocess_total_ms": round((received - started) * 1000, 1),
            "assemble_ms": round((time.perf_counter() - received) * 1000, 1),
            "chunks": chunks,
        }
        return result

    @staticmethod
    def _assemble_payload(payload: dict) -> _BuildResult:
        from .snapshot_worker import unpack_payload
        rows, all_games, non_prop_list, base, direct_sig, built_at = unpack_payload(payload)
        payload.clear()   # drop ~150 MB of pickles before building the rest
        overlay_base = _OverlayBase(
            base_by_event=_group_by_event(base), direct_sig=direct_sig,
        )
        return finish_build(rows, all_games, non_prop_list, built_at, overlay_base)

    def _shutdown_pool(self, kill: bool = False) -> None:
        pool, self._pool = self._pool, None
        if pool is None:
            return
        if kill:
            # A timed-out / wedged build: don't wait for it.
            for proc in list(getattr(pool, "_processes", {}).values()):
                try:
                    proc.kill()
                except Exception:
                    pass
        pool.shutdown(wait=False, cancel_futures=True)

    def _build_sync(self) -> _BuildResult:
        built_at = datetime.now(timezone.utc)
        overlay_base = None
        from .cache import _odds_source
        if _odds_source() == "betting_db":
            merged, base, direct = merge_betting_db(self._cache)
            rows = tuple(merged)
            overlay_base = _OverlayBase(
                base_by_event=_group_by_event(base),
                direct_sig=direct_signatures(direct),
            )
        else:
            rows = tuple(self._cache.all_current())
        # One grouping pass for both views (was two full rows_to_games
        # passes, ~half the 7-12s rebuild, contending with the event loop
        # for the GIL). Output is identical — see rows_to_games_with_non_prop.
        all_games, non_prop_list = rows_to_games_with_non_prop(rows, now=built_at)
        return finish_build(rows, all_games, non_prop_list, built_at, overlay_base)

    # ───────────────────────── direct-book overlay ─────────────────────────

    async def _overlay_loop(self) -> None:
        while True:
            await asyncio.sleep(OVERLAY_INTERVAL_S)
            snap, base = self._current, self._overlay_base
            if snap is None or base is None or self.refreshing:
                continue
            try:
                result = await run_in_threadpool(self._overlay_sync, snap, base)
            except Exception:
                logger.exception("odds snapshot overlay failed")
                continue
            # A full build may have published meanwhile; its data is newer.
            if result is None or self._current is not snap or self.refreshing:
                continue
            new_snap, new_sig = result
            base.direct_sig = new_sig
            self._current = new_snap
            self.overlays_published += 1

    def _overlay_sync(
        self, snap: OddsSnapshot, base: _OverlayBase,
    ) -> tuple[OddsSnapshot, dict[str, tuple]] | None:
        """Re-merge direct-book rows into `snap`, regrouping only the games
        whose direct rows changed. Same merge rule and grouping code as the
        full build, so a changed game comes out exactly as a full rebuild
        would produce it at this moment."""
        from . import bettingdb_source as bdb
        now = datetime.now(timezone.utc)
        direct_by_event = _group_by_event(bdb._direct_book_rows(self._cache))
        sig = {e: _direct_signature(rs) for e, rs in direct_by_event.items()}
        changed = {
            e for e in sig.keys() | base.direct_sig.keys()
            if sig.get(e) != base.direct_sig.get(e)
        }
        if not changed:
            return None
        rows_by_event: dict[str, list[dict]] = {}
        new_games: list[dict] = []
        new_non_prop: list[dict] = []
        for e in changed:
            direct = direct_by_event.get(e, [])
            pks = {bdb._pk(r) for r in direct}
            merged = [
                r for r in base.base_by_event.get(e, ())
                if r["bookmaker_key"] not in bdb.DIRECT_BOOK_KEYS
                or bdb._pk(r) not in pks
            ]
            merged.extend(direct)
            rows_by_event[e] = merged
            if merged:
                g, npg = rows_to_games_with_non_prop(merged, now=now)
                new_games.extend(g)
                new_non_prop.extend(npg)

        def splice(old: tuple[dict, ...], fresh: list[dict]) -> tuple[dict, ...]:
            kept = [g for g in old if g["event_id"] not in changed]
            kept.extend(fresh)
            kept.sort(key=lambda g: g["commence_time"])   # stable, as rows_to_games
            return tuple(kept)

        games = splice(snap.games, new_games)
        non_prop_games = splice(snap.non_prop_games, new_non_prop)
        by_sport: dict[str, list[dict]] = {}
        for game in non_prop_games:
            by_sport.setdefault(game["sport_key"], []).append(game)
        system_rows = [r for r in snap.system_rows if r["event_id"] not in changed]
        for merged in rows_by_event.values():
            system_rows.extend(r for r in merged if _is_system_row(r))
        # Only the direct-book part of the version advances here. Stamping the
        # live read_version would also claim the betting-db rows are current,
        # and the 60s loop would then never run a full rebuild — freezing
        # every betting-db book (caught 2026-10-09: snapshot aged to 221s).
        live_version = self._cache.read_version
        old_version = snap.source_version
        if (len(old_version) == 3 and len(live_version) == 3
                and old_version[0] == live_version[0] == "betting_db"):
            source_version = (old_version[0], old_version[1], live_version[2])
        else:
            source_version = old_version
        return OddsSnapshot(
            generation=snap.generation + 1,
            built_at=snap.built_at,
            source_version=source_version,
            # Flat rows are carried from the last full build: their only
            # readers (mapping-health audit, Novig slot map) run on minute
            # cadences, and rebuilding 300k+ rows here cost ~0.2s a tick.
            rows=snap.rows,
            games=games,
            non_prop_games=non_prop_games,
            non_prop_games_by_sport=MappingProxyType({
                sport: tuple(gs) for sport, gs in by_sport.items()
            }),
            system_rows=tuple(system_rows),
        ), sig
