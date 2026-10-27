"""Polymarket US direct feed — the venue the user trades (polymarket.us).

Lifecycle mirrors PolymarketFetcher / KalshiFetcher (start_all / stop_all /
shutdown / refresh_now / status) so cache_mode.py flips it the same way.

Per league, every CYCLE_INTERVAL seconds:
  1. list the league's upcoming games (cheap summary call);
  2. fetch the FULL event (every market + each side's buy quote) for games
     that are new or whose last full fetch is older than the refresh age —
     5 min while the WebSocket streams prices, 60s when it doesn't;
  3. normalize -> odds_snapshot rows (normalizer.normalize_event), upsert,
     and delete rows for markets the event no longer lists.
The WebSocket (only when POLYMARKET_US_KEY_ID/SECRET are set) streams order
books for every registered market; book-derived buy prices + top-of-book size
are batched into one cache write per second.

Prices are always the BUY side (ask) after Polymarket US's taker fee.
"""
from __future__ import annotations

import asyncio
import collections
import functools
import logging
import os
import random
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ...cache import OddsCache
from ..coral33.event_matcher import _normalize_team
from ..polymarket.event_matcher import PolymarketEventMatcher
from .client import PolymarketUSAPIError, PolymarketUSClient
from .normalizer import BOOK_KEY, american_from_book, normalize_event
from .ws_client import PolymarketUSWSPool


logger = logging.getLogger(__name__)

CYCLE_INTERVAL = int(os.environ.get("POLYMARKET_US_CYCLE_SECONDS", "60"))
CYCLE_JITTER = int(os.environ.get("POLYMARKET_US_CYCLE_JITTER", "10"))
# Full-event refresh age while the WS is live vs when REST is the only source.
FULL_REFRESH_WS_S = 300
FULL_REFRESH_REST_S = 55
# A WS with no message for this long counts as down (REST takes over).
WS_STALE_S = 90
_FLUSH_INTERVAL_S = 1.0
_EVENT_FETCH_CONCURRENCY = 4
_STARTUP_STAGGER = (0, 15)
_UNBUYABLE = (None, None)


def _pk(row: dict) -> tuple:
    return (row["event_id"], row["bookmaker_key"], row["market_key"],
            row["outcome_name"], row.get("outcome_point"))


def _as_utc(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


# Fuzzy fallback: Polymarket US's real start time vs the Odds API's.
_FUZZY_WINDOW_S = 90 * 60


def _same_team(cand: str, canon: str, sport_key: str) -> bool:
    """Same mascot (last token) plus at least one other shared token:
    "K-State Wildcats" ~ "Kansas State Wildcats", "Miami (FL) Hurricanes" ~
    "Miami Hurricanes", "Louisiana-Monroe Warhawks" ~ "UL Monroe Warhawks"."""
    a = _normalize_team(cand, {}, sport_key).split()
    b = _normalize_team(canon, {}, sport_key).split()
    return len(a) > 1 and len(b) > 1 and a[-1] == b[-1] and bool(set(a[:-1]) & set(b[:-1]))


def fuzzy_matcher(cache_events: list[dict]):
    """match_event fallback for names the exact matcher misses (mostly CFB).
    Both teams must fuzzy-match one event starting within 90 min; an
    ambiguous hit returns None."""
    def match(sport_key: str, team_a: str, team_b: str, commence: datetime) -> dict | None:
        hits = []
        for ev in cache_events:
            ts = _as_utc(ev.get("commence_time"))
            if ts is None or abs((ts - commence).total_seconds()) > _FUZZY_WINDOW_S:
                continue
            h, a = ev.get("home_team") or "", ev.get("away_team") or ""
            if ((_same_team(team_a, h, sport_key) and _same_team(team_b, a, sport_key))
                    or (_same_team(team_a, a, sport_key) and _same_team(team_b, h, sport_key))):
                hits.append(ev)
        if len({e["event_id"] for e in hits}) != 1:
            return None
        ev = hits[0]
        return {"event_id": ev["event_id"], "home_team": ev["home_team"],
                "away_team": ev["away_team"], "commence_time": _as_utc(ev["commence_time"])}
    return match


@dataclass
class PolymarketUSConfig:
    leagues: dict[str, str]                       # league slug -> app sport_key
    horizon_hours: int = 72
    team_aliases: dict[str, dict[str, str]] = field(default_factory=dict)


def load_config(path: Path) -> PolymarketUSConfig:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return PolymarketUSConfig(
        leagues={str(k): str(v) for k, v in (raw.get("leagues") or {}).items()},
        horizon_hours=int(raw.get("horizon_hours", 72)),
        team_aliases={
            sport: dict(table or {})
            for sport, table in (raw.get("team_aliases") or {}).items()
        },
    )


@dataclass
class _EventState:
    league: str
    fetched_at: float                    # monotonic time of last full fetch
    commence: datetime | None
    rows: list[dict]                     # last normalized rows (templates)


class PolymarketUSFetcher:
    def __init__(
        self,
        cache: OddsCache,
        config_path: Path,
        key_id: str | None = None,
        secret_key: str | None = None,
    ):
        self.cache = cache
        self.config_path = config_path
        self.client = PolymarketUSClient()
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._config: PolymarketUSConfig | None = None
        self._last_cycle_at: datetime | None = None
        self._last_cycle_rows: dict[str, int] = {}
        self._last_cycle_unmatched: dict[str, int] = {}
        self._unmapped: dict[str, collections.Counter] = {}
        self._events: dict[str, _EventState] = {}          # event slug -> state
        self._templates: dict[str, list[dict]] = {}       # market slug -> rows
        self._last_ws_price: dict[tuple, tuple] = {}      # pk -> (price, size)
        self._pending_upserts: dict[tuple, dict] = {}
        self._pending_deletes: set[tuple] = set()
        self._ws_rows_written = 0
        self._ws: PolymarketUSWSPool | None = None
        self._ws_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self.ws_disabled_reason: str | None = None
        if key_id and secret_key:
            try:
                self._ws = PolymarketUSWSPool(
                    key_id, secret_key,
                    get_slugs=self.registered_slugs,
                    on_market_data=self._on_market_data,
                )
            except Exception as e:   # malformed secret: REST-only, say so
                self.ws_disabled_reason = f"bad credentials: {type(e).__name__}"
                logger.error("polymarket_us: WS disabled — %s", self.ws_disabled_reason)
        else:
            self.ws_disabled_reason = "POLYMARKET_US_KEY_ID / POLYMARKET_US_SECRET_KEY not set"

    # ───────────────────────── lifecycle ─────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def _load_config(self) -> PolymarketUSConfig:
        if self._config is None:
            self._config = load_config(self.config_path)
        return self._config

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        self._config = None
        cfg = self._load_config()
        if not cfg.leagues:
            return {"status": "no_leagues_configured"}
        now = datetime.now(timezone.utc)
        for league in cfg.leagues:
            self.scheduler.add_job(
                self._league_cycle_runner(league),
                trigger="interval",
                seconds=CYCLE_INTERVAL,
                jitter=CYCLE_JITTER,
                next_run_time=now + timedelta(seconds=random.uniform(*_STARTUP_STAGGER)),
                id=f"polymarket_us:{league}",
                replace_existing=True,
                max_instances=1,
            )
        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        if self._ws is not None:
            self._ws._stop = False
            self._ws_task = asyncio.create_task(self._ws.run())
        logger.info(
            "polymarket_us fetcher started: leagues=%s (REST %ds, WS=%s)",
            ",".join(cfg.leagues), CYCLE_INTERVAL,
            "on" if self._ws else f"off ({self.ws_disabled_reason})",
        )
        return {"status": "started", "leagues": list(cfg.leagues)}

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("polymarket_us: error removing jobs")
        if self._ws is not None:
            self._ws.stop()
        for task in (self._ws_task, self._flush_task):
            if task is not None and not task.done():
                task.cancel()
        self._ws_task = self._flush_task = None
        self._running = False
        logger.info("polymarket_us fetcher stopped")
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
        except Exception:
            pass

    # ───────────────────────── status ─────────────────────────

    def _ws_live(self) -> bool:
        ws = self._ws
        return bool(
            ws is not None and ws.is_connected and ws.last_message_at is not None
            and time.time() - ws.last_message_at < WS_STALE_S
            and ws.unstreamed == 0
        )

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "last_cycle_rows": dict(self._last_cycle_rows),
            # "authenticated" here means the signed market-data WS is live.
            "jwt_authenticated": self._ws_live(),
            "ws_enabled": self._ws is not None,
            "ws_disabled_reason": self.ws_disabled_reason,
            "events_tracked": len(self._events),
            "markets_registered": len(self._templates),
            "unmatched_events": dict(self._last_cycle_unmatched),
            "unmapped_market_types": {
                league: dict(c.most_common()) for league, c in self._unmapped.items()
            },
        }

    def debug_stats(self) -> dict:
        return {
            "events_tracked": len(self._events),
            "markets_registered": len(self._templates),
            "template_rows": sum(len(r) for r in self._templates.values()),
            "last_ws_price_entries": len(self._last_ws_price),
            "pending_upserts": len(self._pending_upserts),
            "ws_rows_written": self._ws_rows_written,
            "rest": {"requests": self.client.requests, "errors": self.client.errors},
            "ws": self._ws.stats() if self._ws is not None else None,
        }

    def registered_slugs(self) -> set[str]:
        return set(self._templates)

    # ───────────────────────── REST cycle ─────────────────────────

    def _league_cycle_runner(self, league: str):
        async def run():
            await self._run_league_cycle(league)
        return run

    def _rebuild_templates(self) -> None:
        templates: dict[str, list[dict]] = {}
        for state in self._events.values():
            for row in state.rows:
                templates.setdefault(row["_market_slug"], []).append(row)
        self._templates = templates
        live = {(_pk(r)) for rows in templates.values() for r in rows}
        for pk in [pk for pk in self._last_ws_price if pk not in live]:
            del self._last_ws_price[pk]

    async def _run_league_cycle(self, league: str, force: bool = False) -> None:
        cfg = self._load_config()
        sport_key = cfg.leagues.get(league)
        if sport_key is None:
            return
        now = datetime.now(timezone.utc)
        purged = await self.cache.purge_live_rows_for_book_async(BOOK_KEY, now)
        if purged:
            logger.info("polymarket_us %s: purged %d started-game rows", league, purged)

        try:
            listed = await self.client.list_league_events(league)
        except PolymarketUSAPIError as e:
            logger.warning("polymarket_us %s: %s", league, e)
            return
        horizon = now + timedelta(hours=cfg.horizon_hours)
        wanted: dict[str, datetime] = {}
        for ev in listed:
            start = _as_utc(ev.get("startTime") or ev.get("startDate"))
            if (start is None or start <= now or start > horizon
                    or ev.get("live") or ev.get("ended") or ev.get("closed")):
                continue
            wanted[ev["slug"]] = start

        # Drop this league's events that are no longer upcoming / listed. An
        # empty listing is treated as an API glitch: keep what we had.
        stale_deletes: list[tuple] = []
        if listed:
            for slug in [s for s, st in self._events.items()
                         if st.league == league and s not in wanted]:
                stale_deletes.extend(_pk(r) for r in self._events.pop(slug).rows)

        max_age = FULL_REFRESH_WS_S if self._ws_live() else FULL_REFRESH_REST_S
        mono = time.monotonic()
        due = [
            s for s in wanted
            if force or s not in self._events or mono - self._events[s].fetched_at >= max_age
        ]

        # Event discovery is a full scan of the sport's rows — only pay for it
        # when some game actually needs a full fetch (with the WS live, most
        # cycles have nothing due).
        cache_events = (
            await self.cache.distinct_events_async(sport_key=sport_key)
            if due else []
        )
        matcher = PolymarketEventMatcher(
            lambda _sport: cache_events, team_aliases=cfg.team_aliases,
        )
        fuzzy = fuzzy_matcher(cache_events)
        sem = asyncio.Semaphore(_EVENT_FETCH_CONCURRENCY)
        unmapped: collections.Counter = collections.Counter()
        unmatched = 0
        upserts: list[dict] = []

        async def refresh(slug: str) -> None:
            nonlocal unmatched
            async with sem:
                try:
                    event = await self.client.get_event(slug)
                except PolymarketUSAPIError as e:
                    logger.warning("polymarket_us %s: %s", slug, e)
                    return
            if not event:
                return
            fetched_at = datetime.now(timezone.utc)
            result = await asyncio.to_thread(
                functools.partial(normalize_event, sport_key=sport_key),
                event, league, fetched_at, matcher.match,
            )
            if result.event_id is None and result.skipped.get("unmatched_event"):
                result = await asyncio.to_thread(
                    functools.partial(normalize_event, sport_key=sport_key),
                    event, league, fetched_at, fuzzy,
                )
            unmapped.update(result.unmapped)
            if result.event_id is None:
                unmatched += 1
                logger.info("polymarket_us %s: no app event matched", slug)
            old = self._events.get(slug)
            if old is not None:
                new_pks = {_pk(r) for r in result.rows}
                stale_deletes.extend(pk for pk in map(_pk, old.rows) if pk not in new_pks)
            self._events[slug] = _EventState(
                league=league, fetched_at=time.monotonic(),
                commence=wanted.get(slug), rows=result.rows,
            )
            upserts.extend(result.rows)

        await asyncio.gather(*(refresh(s) for s in due))

        if upserts:
            # REST quotes are current buy prices too; size stays from the WS
            # book (upsert COALESCEs a None max_stake_dollars).
            await self.cache.upsert_async(upserts)
        if stale_deletes:
            await self.cache.delete_rows_async(stale_deletes)
        self._rebuild_templates()
        if due:
            self._unmapped[league] = unmapped
            self._last_cycle_unmatched[league] = unmatched
        self._last_cycle_at = now
        self._last_cycle_rows[league] = sum(
            len(st.rows) for st in self._events.values() if st.league == league
        )

    async def refresh_now(self, leagues: list[str] | None = None) -> dict:
        cfg = self._load_config()
        targets = [l for l in (leagues or list(cfg.leagues)) if l in cfg.leagues]
        t0 = time.monotonic()
        results = await asyncio.gather(
            *(self._run_league_cycle(l, force=True) for l in targets),
            return_exceptions=True,
        )
        errors = [str(r) for r in results if isinstance(r, Exception)]
        return {
            "status": "ok" if not errors else "partial",
            "sports_refreshed": targets,
            "duration_s": round(time.monotonic() - t0, 2),
            "errors": errors,
            "last_cycle_rows": dict(self._last_cycle_rows),
        }

    # ───────────────────────── WS overlay ─────────────────────────

    def _on_market_data(self, md: dict) -> None:
        rows = self._templates.get(md.get("marketSlug"))
        if not rows:
            return
        now = datetime.now(timezone.utc)
        open_ = md.get("state") in (None, "MARKET_STATE_OPEN")
        bids, offers = md.get("bids") or [], md.get("offers") or []
        for row in rows:
            commence = _as_utc(row.get("commence_time"))
            if commence is not None and commence <= now:
                continue                      # started: purge owns it
            pk = _pk(row)
            price, size = (
                american_from_book(bids, offers, row["_long"], row["_fee"])
                if open_ else (None, None)
            )
            if price is None:
                # Side can't be bought right now: pull the quote once.
                if self._last_ws_price.get(pk) != _UNBUYABLE:
                    self._last_ws_price[pk] = _UNBUYABLE
                    self._pending_upserts.pop(pk, None)
                    self._pending_deletes.add(pk)
                continue
            if self._last_ws_price.get(pk) == (price, size):
                continue
            self._last_ws_price[pk] = (price, size)
            self._pending_deletes.discard(pk)
            self._pending_upserts[pk] = {
                **row, "price_american": price,
                "max_stake_dollars": size, "fetched_at": now,
            }

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL_S)
            try:
                if self._pending_upserts:
                    batch = list(self._pending_upserts.values())
                    self._pending_upserts = {}
                    await self.cache.upsert_async(batch)
                    self._ws_rows_written += len(batch)
                if self._pending_deletes:
                    keys = list(self._pending_deletes)
                    self._pending_deletes = set()
                    await self.cache.delete_rows_async(keys)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("polymarket_us: WS flush failed")
