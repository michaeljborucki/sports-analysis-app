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
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
# Team/fighter alias tables are shared with coral33 — same folding rules,
# and its hand-curated entries (e.g. "mick parkin" → "michael parkin") are
# exactly the name drift Novig shows too.
_CORAL33_CONFIG = Path(__file__).resolve().parents[3] / "config" / "coral33.toml"


def poll_interval_s(hours_to_start: float) -> int:
    if hours_to_start < 1:
        return 60
    if hours_to_start < 3:
        return 120
    if hours_to_start < 6:
        return 240
    return 480


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


class NovigFetcher:
    def __init__(self, cache: OddsCache, settings_store=None):
        self.cache = cache
        self.settings_store = settings_store
        self.client = NovigClient()
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
        for task in self._poll_tasks:
            if not task.done():
                task.cancel()
        self._poll_tasks = []
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
            self.cache.purge_live_rows_for_book(BOOK_KEY, now)
        # Maker quotes are ours alone in every mode, and Novig voids
        # resting orders at kickoff — drop them for started games.
        self.cache.purge_live_rows_for_book(MAKER_BOOK_KEY, now)

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
                idle = [kv for kv in self._targets.items() if not kv[1].in_flight]
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
            t.quotes = take_quotes(t.market, book)
            t.maker = maker_quotes(t.market, book)
            t.etag = etag
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
            self.cache.delete_rows(gone)
        t.maker_keys = maker_keys
        rows += maker_rows
        if rows:
            self.cache.upsert(rows)
            self._rows_written += len(rows)
            self._last_cycle_rows[t.sport] = self._last_cycle_rows.get(t.sport, 0) + len(rows)
        self._last_book_at = now
        hours = (t.starts - now).total_seconds() / 3600
        t.next_due = now + timedelta(seconds=poll_interval_s(hours))
