"""Novig direct fetcher — public REST, read-only.

Replaces (per row) the Odds API's copy of Novig with prices read straight
off Novig's order book, plus the size available at that price
(`max_stake_dollars`). It never places, cancels, or signs anything.

Two loops share one rate-limited client:

  * catalog refresh (every NOVIG_CATALOG_SECONDS, default 300s): list
    pregame events + markets for enabled sports inside the horizon, match
    events to the cache, and keep only markets that land on an existing
    Novig slot (see normalizer.plan_market). That set is the poll target.
  * book poller (continuous): fetch the most-overdue target's book, write
    its take prices, reschedule it by time-to-start (60s inside an hour …
    480s beyond six). 480s stays under purge_stale_rows' 600s TTL, so a
    target that keeps its schedule never flaps back to the betting-db copy.

The public endpoint allows ~2 req/s per IP, so on a busy slate not every
target makes its schedule; the most overdue goes first and anything that
falls behind ages out after 600s, at which point the betting-db copy of
that row shows again. Nothing is ever lost — only fresher where we reach.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import zlib
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .cadence import poll_interval_s
from ...cache import OddsCache, _odds_source
from ..coral33.mapping import load_coral33_config
from .client import NovigAPIError, NovigClient
from .mapping import BOOK_KEY, MAKER_BOOK_KEY, SPORT_TO_LEAGUES, app_sport
from .normalizer import (
    build_sibling_index, maker_quotes, match_event, plan_market, rows_for,
    take_quotes,
)


logger = logging.getLogger(__name__)

CATALOG_INTERVAL = int(os.environ.get("NOVIG_CATALOG_SECONDS", "300"))
HORIZON_HOURS = float(os.environ.get("NOVIG_HORIZON_HOURS", "12"))
# Concurrent book requests. An uncached book GET takes ~2.7s round trip, so one
# sequential worker can't use the rate budget; the shared token bucket in
# NovigClient is what actually bounds req/s.
POLL_WORKERS = int(os.environ.get("NOVIG_POLL_WORKERS", "8"))
# Streamed markets whose bbo hasn't moved are re-written this often so their
# rows stay inside purge_stale_rows' 600s TTL.
STREAM_REFRESH_S = 240
# Each market's re-stamp is offset by up to this much (stable per market) so
# the ~3k streamed rows don't all rewrite in the same second.
STREAM_REFRESH_SPREAD_S = 120
STREAM_REFRESH_MAX_PER_TICK = 40
# A market that opens mid-game on a streamed event triggers an early catalog
# refresh (so it gets planned and targeted), at most this often.
NEW_MARKET_CATALOG_DEBOUNCE_S = 30
# Team/fighter alias tables are shared with coral33 — same folding rules,
# and its hand-curated entries (e.g. "mick parkin" → "michael parkin") are
# exactly the name drift Novig shows too.
_CORAL33_CONFIG = Path(__file__).resolve().parents[3] / "config" / "coral33.toml"


@dataclass
class _Target:
    market: dict
    sport: str
    cache_event: dict
    plan: list
    starts: datetime
    next_due: datetime
    etag: str | None = None
    quotes: dict = field(default_factory=dict)
    maker: dict = field(default_factory=dict)
    maker_keys: set = field(default_factory=set)
    in_flight: bool = False
    written_at: datetime | None = None


def _join_market(mk: str) -> str:
    """EV ops label spreads/totals by the MAIN key and fold prop alternates;
    fold Novig plan keys the same way so the two can be joined."""
    if mk.startswith("alternate_"):
        mk = mk[len("alternate_"):]
    return mk.removesuffix("_alternate")


def _join_point(p) -> float | None:
    return None if p is None else round(float(p), 2)


class NovigFetcher:
    def __init__(self, cache: OddsCache, settings_store=None, snapshot_rows=None):
        self.cache = cache
        self.settings_store = settings_store
        # () -> published odds-snapshot rows (all books) or None. Supplies the
        # fallback slot map for Novig markets betting-db has no Novig copy of.
        self._snapshot_rows = snapshot_rows
        self.client = NovigClient()
        # Live best-bid stream (signed websocket). Only with a signing key;
        # NOVIG_WS_ENABLED=false keeps everything on REST polling.
        self._stream = None
        self._stream_tasks: list[asyncio.Task] = []
        self._stream_dirty: set[str] = set()
        self._ws_rows_written = 0
        if self.client._signer is not None and os.environ.get(
            "NOVIG_WS_ENABLED", "true"
        ).strip().lower() not in ("0", "false", "no"):
            from .ws_feed import NovigBboStream
            self._stream = NovigBboStream(
                self.client._signer,
                desired=self._stream_desired,
                # Late-bound: the flush loop swaps in a fresh set each tick.
                on_change=lambda mid: self._stream_dirty.add(mid),
                on_lost=self._stream_lost,
                on_new_market=self._stream_new_market,
            )
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._targets: dict[str, _Target] = {}
        self._poll_tasks: list[asyncio.Task] = []
        self._catalog_lock = asyncio.Lock()
        self._last_catalog_at: datetime | None = None
        self._last_catalog_stats: dict = {}
        self._last_cycle_rows: dict[str, int] = {}
        self._books_polled = 0
        self._books_unchanged = 0
        self._rows_written = 0
        self._last_book_at: datetime | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _enabled_sports(self) -> list[str]:
        sports = list(SPORT_TO_LEAGUES)
        if self.settings_store is None:
            return sports
        try:
            settings = self.settings_store.get()
        except Exception:
            logger.exception("novig: settings read failed; polling all sports")
            return sports
        return [s for s in sports if settings.is_sport_enabled(s)]

    # ───────────────────────── lifecycle ─────────────────────────

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        self.scheduler.add_job(
            self.refresh_catalog,
            trigger="interval",
            seconds=CATALOG_INTERVAL,
            jitter=15,
            next_run_time=datetime.now(timezone.utc)
            + timedelta(seconds=random.uniform(3, 10)),
            id="novig:catalog",
            replace_existing=True,
            max_instances=1,
        )
        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        self._poll_tasks = [
            asyncio.create_task(self._poll_loop()) for _ in range(POLL_WORKERS)
        ]
        if self._stream is not None:
            self._stream_tasks = [
                asyncio.create_task(self._stream.run()),
                asyncio.create_task(self._stream_flush_loop()),
            ]
        logger.info(
            "novig fetcher started (catalog %ds, horizon %.0fh, %.1f req/s)",
            CATALOG_INTERVAL, HORIZON_HOURS, self.client.stats()["rps"],
        )
        return {"status": "started", "sports": self._enabled_sports()}

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("novig: error removing jobs")
        for task in self._poll_tasks + self._stream_tasks:
            if not task.done():
                task.cancel()
        self._poll_tasks = []
        self._stream_tasks = []
        self._running = False
        logger.info("novig fetcher stopped")
        return {"status": "stopped"}

    def shutdown(self) -> None:
        try:
            self.stop_all()
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.client.aclose())
            else:
                loop.run_until_complete(self.client.aclose())
        except Exception:
            pass

    @property
    def status(self) -> dict:
        now = datetime.now(timezone.utc)
        overdue = sum(
            1 for t in self._targets.values()
            if t.next_due < now and not t.in_flight
        )
        return {
            "running": self._running,
            "last_cycle_at": self._last_catalog_at.isoformat() if self._last_catalog_at else None,
            "last_cycle_rows": dict(self._last_cycle_rows),
            "jwt_authenticated": True,
            "targets": len(self._targets),
            "targets_overdue": overdue,
            "books_polled": self._books_polled,
            "books_unchanged": self._books_unchanged,
            "rows_written": self._rows_written,
            "last_book_at": self._last_book_at.isoformat() if self._last_book_at else None,
            "catalog": dict(self._last_catalog_stats),
            "ws_enabled": self._stream is not None,
            "ws_rows_written": self._ws_rows_written,
            **({f"ws_{k}": v for k, v in self._stream.stats().items()}
               if self._stream is not None else {}),
            **{f"http_{k}": v for k, v in self.client.stats().items()},
        }

    async def refresh_now(self, sport_keys: list[str] | None = None) -> dict:
        t0 = datetime.now(timezone.utc)
        errors: list[str] = []
        try:
            await self.refresh_catalog()
        except Exception as e:  # surfaced to the caller, not swallowed
            errors.append(str(e))
        return {
            "status": "ok" if not errors else "partial",
            "sports_refreshed": self._enabled_sports(),
            "duration_s": round((datetime.now(timezone.utc) - t0).total_seconds(), 2),
            "errors": errors,
            "last_cycle_rows": dict(self._last_cycle_rows),
        }

    # ───────────────────────── catalog ─────────────────────────

    async def refresh_catalog(self) -> None:
        async with self._catalog_lock:
            await self._refresh_catalog()

    async def _refresh_catalog(self) -> None:
        now = datetime.now(timezone.utc)
        # Native odds_snapshot only ever holds OUR novig rows in betting_db
        # mode (betting-db's copy lives in its own file), so purging live
        # games here can't touch anyone else's data. In native mode the Odds
        # API fetcher shares the slot, so leave live rows to the 600s TTL.
        if _odds_source() == "betting_db":
            await self.cache.purge_live_rows_for_book_async(BOOK_KEY, now)
        # Maker quotes are ours alone in every mode, and Novig voids
        # resting orders at kickoff — drop them for started games.
        await self.cache.purge_live_rows_for_book_async(MAKER_BOOK_KEY, now)

        try:
            aliases = load_coral33_config(_CORAL33_CONFIG).team_aliases
        except Exception:
            logger.exception("novig: coral33 alias load failed; matching without aliases")
            aliases = {}

        sports = self._enabled_sports()
        leagues = sorted({lg for s in sports for lg in SPORT_TO_LEAGUES[s]})
        if not leagues:
            self._targets.clear()
            return
        before_ms = int((now + timedelta(hours=HORIZON_HOURS)).timestamp() * 1000)
        try:
            events = await self.client.list_events(
                league=",".join(leagues), status="OPEN_PREGAME",
                startsBefore=before_ms,
            )
            markets = await self.client.list_markets(
                league=",".join(leagues), eventStatus="OPEN_PREGAME",
                startsBefore=before_ms,
            )
        except NovigAPIError as e:
            logger.warning("novig catalog refresh failed: %s", e)
            self._last_catalog_stats = {"error": str(e)}
            return

        by_event: dict[str, list[dict]] = {}
        for m in markets:
            if m.get("status") == "OPEN":
                by_event.setdefault(m["eventId"], []).append(m)
        # An event subscription watches all of its markets, not just the ones
        # we target; the stream sizes its watch cap with these counts.
        self._event_market_counts = {eid: len(ms) for eid, ms in by_event.items()}

        new_targets: dict[str, _Target] = {}
        stats = {"events": 0, "events_matched": 0, "markets": len(markets),
                 "markets_targeted": 0}
        per_sport_targets: dict[str, int] = {}
        events_by_sport: dict[str, list[dict]] = {}
        for ev in events:
            sport = app_sport(ev)
            if sport in sports:
                events_by_sport.setdefault(sport, []).append(ev)

        for sport, novig_events in events_by_sport.items():
            cache_events = await self.cache.distinct_events_async(sport_key=sport)
            rows = await asyncio.to_thread(self._novig_rows, sport)
            events_by_id = {e["event_id"]: e for e in cache_events}
            index = build_sibling_index(rows, events_by_id)
            # Novig's own catalog decides coverage, not the Odds API's: a
            # market with no Novig sibling row takes its slot from the other
            # books on the same line. Existing Novig slots win per key.
            other_rows = self._other_book_rows(sport)
            if other_rows:
                fallback = await asyncio.to_thread(
                    build_sibling_index, other_rows, events_by_id,
                    exclude_books=frozenset({BOOK_KEY, MAKER_BOOK_KEY}),
                )
                stats["fallback_slots"] = stats.get("fallback_slots", 0) + sum(
                    1 for k in fallback if k not in index
                )
                index = {**fallback, **index}
            for nev in novig_events:
                stats["events"] += 1
                starts = datetime.fromtimestamp(nev["startsTs"] / 1000, tz=timezone.utc)
                if starts <= now:
                    continue
                hit = match_event(nev, sport, cache_events, aliases.get(sport))
                if hit is None:
                    continue
                stats["events_matched"] += 1
                cache_event, straight = hit
                for m in by_event.get(nev["eventId"], []):
                    plan = plan_market(m, sport, cache_event, straight, index)
                    if not plan:
                        continue
                    prev = self._targets.get(m["marketId"])
                    new_targets[m["marketId"]] = _Target(
                        market=m, sport=sport, cache_event=cache_event,
                        plan=plan, starts=starts,
                        next_due=prev.next_due if prev else now,
                        etag=prev.etag if prev else None,
                        quotes=prev.quotes if prev else {},
                        maker=prev.maker if prev else {},
                        maker_keys=prev.maker_keys if prev else set(),
                        written_at=prev.written_at if prev else None,
                    )
                    per_sport_targets[sport] = per_sport_targets.get(sport, 0) + 1

        self._targets = new_targets
        stats["markets_targeted"] = len(new_targets)
        stats["by_sport"] = per_sport_targets
        self._last_catalog_stats = stats
        self._last_catalog_at = now
        logger.info(
            "novig catalog: %d/%d events matched, %d/%d markets targeted %s",
            stats["events_matched"], stats["events"],
            stats["markets_targeted"], stats["markets"], per_sport_targets,
        )

    def _other_book_rows(self, sport: str) -> list[dict]:
        """This sport's rows from the published odds snapshot (no DB read)."""
        if self._snapshot_rows is None:
            return []
        rows = self._snapshot_rows()
        if not rows:
            return []
        return [r for r in rows if r.get("sport_key") == sport]

    def _novig_rows(self, sport: str) -> list[dict]:
        """Every Novig row currently readable for a sport: betting-db's copy
        (in betting_db mode) plus our own native rows. Book-filtered SQL —
        a full `all_current(sport)` is ~150k rows and stalls page loads."""
        with self.cache._conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM odds_snapshot WHERE bookmaker_key = ? AND sport_key = ?",
                (BOOK_KEY, sport),
            )]
        if _odds_source() == "betting_db":
            from ... import bettingdb_source
            rows.extend(bettingdb_source.book_rows(BOOK_KEY, sport))
        return rows

    # ───────────────────────── book poller ─────────────────────────

    async def _poll_loop(self) -> None:
        try:
            while self._running:
                if not self._targets:
                    await asyncio.sleep(2)
                    continue
                now = datetime.now(timezone.utc)
                stream = self._stream
                idle = [
                    kv for kv in self._targets.items()
                    if not kv[1].in_flight
                    and not (stream is not None and stream.covers(kv[0]))
                ]
                if not idle:
                    await asyncio.sleep(0.5)
                    continue
                due = [kv for kv in idle if kv[1].next_due <= now]
                if not due:
                    nxt = min(t.next_due for _, t in idle)
                    await asyncio.sleep(min(1.0, (nxt - now).total_seconds()))
                    continue
                # When more is due than the rate allows, the soonest game
                # wins; far-out games fall back to their betting-db copy.
                mid, t = min(due, key=lambda kv: kv[1].starts)
                if t.starts <= now:
                    self._targets.pop(mid, None)
                    continue
                # Claim before awaiting so sibling workers skip it.
                t.in_flight = True
                try:
                    await self._poll_one(mid, t)
                except Exception:
                    # A bad book payload must not kill the worker.
                    logger.exception("novig book %s: poll failed", mid)
                    t.next_due = now + timedelta(seconds=60)
                finally:
                    t.in_flight = False
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("novig book poller crashed")
            self._running = False

    async def _poll_one(self, market_id: str, t: _Target) -> None:
        try:
            book, etag = await self.client.get_book(market_id, t.etag)
        except NovigAPIError as e:
            logger.debug("novig book %s: %s", market_id, e)
            t.next_due = datetime.now(timezone.utc) + timedelta(seconds=30)
            return
        now = datetime.now(timezone.utc)
        self._books_polled += 1
        if book is None:
            self._books_unchanged += 1
        else:
            t.etag = etag
        self._last_book_at = now
        written = await self._write_quotes(t, book, now)
        self._rows_written += written
        hours = (t.starts - now).total_seconds() / 3600
        t.next_due = now + timedelta(seconds=poll_interval_s(hours))

    async def _write_quotes(self, t: _Target, book: dict | None, now: datetime) -> int:
        """Price `book` (None = unchanged, reuse the last quotes) and write the
        take + maker rows. Shared by the REST poller and the websocket stream."""
        if book is not None:
            t.quotes = take_quotes(t.market, book)
            t.maker = maker_quotes(t.market, book)
        rows = rows_for(t.market, t.plan, t.quotes, t.sport, t.cache_event, now)
        maker_rows = rows_for(
            t.market, t.plan, {k: (v, None) for k, v in t.maker.items()},
            t.sport, t.cache_event, now, book_key=MAKER_BOOK_KEY,
        )
        # A maker quote whose bid vanished has no betting-db copy to fall
        # back to — delete it now rather than show it for up to 600s.
        maker_keys = {
            (r["event_id"], r["bookmaker_key"], r["market_key"],
             r["outcome_name"], r["outcome_point"])
            for r in maker_rows
        }
        gone = t.maker_keys - maker_keys
        if gone:
            await self.cache.delete_rows_async(gone)
        t.maker_keys = maker_keys
        rows += maker_rows
        if rows:
            await self.cache.upsert_async(rows)
            self._last_cycle_rows[t.sport] = self._last_cycle_rows.get(t.sport, 0) + len(rows)
        t.written_at = now
        return len(rows)

    # ───────────────────────── maker candidates ─────────────────────────

    def maker_candidates(self, games: list[dict], now: datetime) -> list[dict]:
        """Every Novig outcome we hold a make quote for, with its fair
        probability (same devig as the EV page) and the live best bids.
        Read-only input for the auto-maker process; places nothing."""
        from ...ev import scan_all_ev
        ops = scan_all_ev(
            games, now, books_filter={MAKER_BOOK_KEY},
            min_ev_pct=-1000.0, max_longshot_american=100_000,
            stale_seconds=300.0, arb_keys=None, max_results=None,
        )
        index: dict[tuple, tuple[str, str, _Target]] = {}
        for mid, t in self._targets.items():
            for oid, mk, name, point in t.plan:
                index[(t.cache_event["event_id"], _join_market(mk), name, _join_point(point))] = (mid, oid, t)
        stream = self._stream
        out: dict[str, dict] = {}
        for op in ops:
            hit = index.get((op["event_id"], _join_market(op["market_kind"]),
                             op["outcome_name"], _join_point(op.get("point"))))
            if hit is None:
                continue
            mid, oid, t = hit
            if oid in out:
                continue
            others = [o["outcomeId"] for o in t.market.get("outcomes") or [] if o["outcomeId"] != oid]
            other = others[0] if len(others) == 1 else None
            live = stream is not None and stream.covers(mid)
            levels = stream.state.get(mid, {}) if live else {}
            own = levels.get(oid)
            opp = levels.get(other) if other else None
            out[oid] = {
                "event_id": op["event_id"],
                "sport_key": op["sport_key"],
                "home_team": op["home_team"],
                "away_team": op["away_team"],
                "commence_time": t.starts.isoformat(),
                "market_key": op["market_kind"],
                "outcome_name": op["outcome_name"],
                "point": op.get("point"),
                "market_id": mid,
                "novig_event_id": t.market.get("eventId"),
                "novig_event_market_count": getattr(self, "_event_market_counts", {}).get(
                    t.market.get("eventId"), 1),
                "outcome_id": oid,
                "other_outcome_id": other,
                "fair_probability": op["fair_probability"],
                "fair_source": op["source"],
                "anchor_book_count": op["anchor_book_count"],
                "confidence": op["confidence"],
                "fee_charged": (t.market.get("fee") or {}).get("charged"),
                "bbo_live": live,
                "own_best_bid": list(own) if own else None,
                "other_best_bid": list(opp) if opp else None,
            }
        return list(out.values())

    # ───────────────────────── websocket stream ─────────────────────────

    def _stream_desired(self) -> list[tuple[str, int]]:
        """(event_id, open market count) for events with targets, soonest
        game first (the stream's watch cap keeps the head)."""
        now = datetime.now(timezone.utc)
        starts: dict[str, datetime] = {}
        for t in self._targets.values():
            eid = t.market.get("eventId")
            if eid and t.starts > now and (eid not in starts or t.starts < starts[eid]):
                starts[eid] = t.starts
        counts = getattr(self, "_event_market_counts", {})
        return [
            (eid, counts.get(eid, 1))
            for eid, _ in sorted(starts.items(), key=lambda kv: kv[1])
        ]

    def _stream_new_market(self, mid: str) -> None:
        if mid not in self._targets:
            self._catalog_wanted = True

    def _refresh_offset(self, mid: str) -> float:
        return (zlib.crc32(mid.encode()) % 1000) / 1000 * STREAM_REFRESH_SPREAD_S

    def _stream_lost(self, mids: set[str]) -> None:
        """Markets the stream stopped covering go straight back to polling."""
        now = datetime.now(timezone.utc)
        for mid in mids:
            t = self._targets.get(mid)
            if t is not None:
                t.next_due = now

    async def _stream_flush_loop(self) -> None:
        """Write changed streamed markets once a second, and re-stamp quiet
        ones every STREAM_REFRESH_S so a book that simply didn't move never
        ages into the 600s stale purge while the socket vouches for it."""
        from .ws_feed import bbo_book
        try:
            while self._running:
                await asyncio.sleep(1.0)
                stream = self._stream
                now = datetime.now(timezone.utc)
                dirty, self._stream_dirty = self._stream_dirty, set()
                if (
                    getattr(self, "_catalog_wanted", False)
                    and not self._catalog_lock.locked()
                    and (self._last_catalog_at is None
                         or (now - self._last_catalog_at).total_seconds()
                         >= NEW_MARKET_CATALOG_DEBOUNCE_S)
                ):
                    self._catalog_wanted = False
                    asyncio.create_task(self.refresh_catalog())
                due = [
                    mid for mid in stream.live_ids() - dirty
                    if (t := self._targets.get(mid)) is not None
                    and (t.written_at is None
                         or (now - t.written_at).total_seconds()
                         >= STREAM_REFRESH_S - self._refresh_offset(mid))
                ]
                # Oldest first, capped: a fresh catalog (written_at reset)
                # spreads over a few ticks instead of one burst.
                due.sort(key=lambda m: self._targets[m].written_at
                         or datetime.min.replace(tzinfo=timezone.utc))
                refresh = set(due[:STREAM_REFRESH_MAX_PER_TICK])
                for mid in dirty | refresh:
                    t = self._targets.get(mid)
                    if t is None or t.in_flight or not stream.covers(mid):
                        continue
                    if t.starts <= now:
                        continue
                    try:
                        n = await self._write_quotes(t, bbo_book(stream.state.get(mid, {})), now)
                    except Exception:
                        logger.exception("novig ws %s: write failed", mid)
                        continue
                    self._ws_rows_written += n
                    self._rows_written += n
                    self._last_book_at = now
                    hours = (t.starts - now).total_seconds() / 3600
                    t.next_due = now + timedelta(seconds=poll_interval_s(hours))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("novig ws flush loop crashed")
