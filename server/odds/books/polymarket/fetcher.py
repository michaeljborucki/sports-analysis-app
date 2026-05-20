"""Polymarket per-sport poller.

Mirrors `KalshiFetcher`'s lifecycle (start_all / stop_all / shutdown +
APScheduler-driven jobs + per-cycle status tracking + WS task) so
cache_mode.py can flip all three direct-API fetchers identically.

Differences from Kalshi:
  - No auth at all. Reads are 100% public.
  - REST cycle does ONE GET per cycle (not per sport) — Gamma's
    /events endpoint returns ALL sports at once with the
    `tag_slug=sports` filter. Each sport job filters the same response
    locally rather than re-fetching.
  - However the dispatch shape stays per-sport so refresh_now /
    per-sport stats stay symmetric with Kalshi's UI surface.
  - WS subscribes to specific asset_ids (vs Kalshi's "all-markets
    ticker channel"). The set updates on each REST cycle; new games
    are picked up at the next WS reconnect boundary.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ...cache import OddsCache
from .client import PolymarketAPIError, PolymarketClient
from .event_matcher import PolymarketEventMatcher
from .mapping import PolymarketConfig, load_polymarket_config
from .normalizer import normalize_events
from .ws_client import PolymarketWSClient, PolymarketWSError
from .ws_ingest import PolymarketIngestor


logger = logging.getLogger(__name__)


# REST safety-net cadence. WS handles real-time price updates; REST exists
# only to:
#   1. Discover NEW games (slug + asset_ids materialize when Polymarket
#      seeds a new event)
#   2. Recover from a WS disconnect window
#   3. Refresh metadata if a game gets rescheduled (commence_time shifts)
# 60s aligns with Kalshi's cycle. Increase if Gamma starts rate-limiting;
# decrease to reduce new-game discovery latency.
CYCLE_INTERVAL = int(os.environ.get("POLYMARKET_CYCLE_SECONDS", "60"))
CYCLE_JITTER   = int(os.environ.get("POLYMARKET_CYCLE_JITTER", "10"))

# Per-sport startup stagger so we don't fire all sport jobs in the same
# wallclock second on boot. Tight stagger (<5s) is fine — Polymarket has
# no documented rate limit.
_STARTUP_STAGGER = (0, max(2, min(15, CYCLE_INTERVAL)))

# Process-wide cache for the Gamma response. Multiple sport jobs in the
# same cycle window share this so we only hit /events once per ~CYCLE
# seconds. Stored as (timestamp, events_list); None entries are invalid.
_GAMMA_CACHE_TTL_S = max(5, CYCLE_INTERVAL // 2)


class PolymarketFetcher:
    """Per-sport poller for Polymarket's Gamma API + WebSocket.

    Phase 1: h2h moneyline discovery for NBA/MLB/NHL. The WS task is always
    on (no auth needed) — it starts after the first REST cycle has populated
    the ingestor with at least one asset_id.
    """

    def __init__(
        self,
        cache: OddsCache,
        config_path: Path,
    ):
        self.cache = cache
        self.config_path = config_path
        self.client = PolymarketClient()
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._config: PolymarketConfig | None = None
        # Observability for the Settings / manual-refresh UI.
        self._last_cycle_at: datetime | None = None
        self._last_cycle_rows: dict[str, int] = {}
        # Shared Gamma cache (events list + timestamp) to avoid N redundant
        # /events fetches when N sport jobs fire in the same window.
        self._gamma_cache: tuple[datetime, list[dict]] | None = None
        self._gamma_lock = asyncio.Lock()

        # WS stack — always on (no creds required).
        self._ingestor: PolymarketIngestor = PolymarketIngestor(cache)
        self._ws_client: PolymarketWSClient = PolymarketWSClient(
            get_asset_ids=self._ingestor.asset_ids,
        )
        self._ws_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _load_config(self) -> PolymarketConfig:
        if self._config is None:
            self._config = load_polymarket_config(self.config_path)
        return self._config

    def _matcher(self) -> PolymarketEventMatcher:
        cfg = self._load_config()

        def events_for(sport_key: str) -> list[dict]:
            return self.cache.distinct_events(sport_key=sport_key)

        return PolymarketEventMatcher(events_for, team_aliases=cfg.team_aliases)

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        self._config = None  # pick up TOML edits across restarts
        cfg = self._load_config()
        if not cfg.sports:
            return {"status": "no_sports_configured"}

        now = datetime.now(timezone.utc)
        scheduled: list[str] = []
        for sport_key in cfg.sports:
            first_fire = now + timedelta(seconds=random.uniform(*_STARTUP_STAGGER))
            self.scheduler.add_job(
                self._sport_cycle_runner(sport_key),
                trigger="interval",
                seconds=CYCLE_INTERVAL,
                jitter=CYCLE_JITTER,
                next_run_time=first_fire,
                id=f"polymarket:{sport_key}",
                replace_existing=True,
                max_instances=1,
            )
            scheduled.append(sport_key)

        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True

        # WS task — runs alongside the REST scheduler. Starts now; the
        # first connect attempt will raise PolymarketWSError if no assets
        # are registered yet (first REST cycle hasn't fired), and the
        # client's backoff loop will retry in a second.
        self._ws_task = asyncio.create_task(self._run_ws_consumer())

        logger.info(
            "polymarket fetcher started: %d sports (REST cycle %ds ±%ds, WS=on)",
            len(scheduled), CYCLE_INTERVAL, CYCLE_JITTER,
        )
        return {"status": "started", "sports": scheduled}

    @property
    def status(self) -> dict:
        """Snapshot of fetcher health for the UI. Mirrors kalshi/coral33
        shape so the frontend can poll all three with the same component."""
        out = {
            "running": self._running,
            "last_cycle_at": (
                self._last_cycle_at.isoformat() if self._last_cycle_at else None
            ),
            "last_cycle_rows": dict(self._last_cycle_rows),
            # Polymarket needs no auth → always "authenticated" for UI parity.
            "jwt_authenticated": True,
        }
        out.update(self._ws_client.status())
        out.update(self._ingestor.status())
        return out

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("polymarket: error removing jobs")
        # Stop the WS consumer too.
        self._ws_client.stop()
        if self._ws_task is not None and not self._ws_task.done():
            self._ws_task.cancel()
            self._ws_task = None
        self._running = False
        logger.info("polymarket fetcher stopped")
        return {"status": "stopped"}

    async def _run_ws_consumer(self) -> None:
        """Background task consuming the WebSocket market stream. Wraps
        the auto-reconnecting iterator from PolymarketWSClient and routes
        each message through the ingestor.
        """
        try:
            async for msg in self._ws_client.market_messages():
                try:
                    self._ingestor.process_message(msg)
                except Exception:
                    logger.exception("polymarket WS: process_message failed")
        except asyncio.CancelledError:
            logger.info("polymarket WS consumer cancelled")
            raise
        except PolymarketWSError as e:
            logger.error(
                "polymarket WS consumer terminated (REST fallback only): %s", e,
            )
        except Exception:
            logger.exception(
                "polymarket WS consumer crashed (REST fallback only)",
            )

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

    # ---------- Sport-cycle runner ----------

    def _sport_cycle_runner(self, sport_key: str):
        async def run():
            await self._run_sport_cycle(sport_key)
        return run

    async def _fetch_gamma_events(self) -> list[dict]:
        """Shared cache so concurrent sport jobs reuse one /events fetch.
        Cache TTL is half of the cycle interval, ensuring we always
        re-fetch at least once per cycle window."""
        now = datetime.now(timezone.utc)
        async with self._gamma_lock:
            if self._gamma_cache is not None:
                fetched_at, events = self._gamma_cache
                age = (now - fetched_at).total_seconds()
                if age <= _GAMMA_CACHE_TTL_S:
                    return events
            events = await self.client.list_sports_events()
            self._gamma_cache = (now, events)
            return events

    async def _run_sport_cycle(self, sport_key: str) -> None:
        cfg = self._load_config()
        sport_cfg = cfg.sports.get(sport_key)
        if sport_cfg is None:
            return

        now = datetime.now(timezone.utc)
        # Live-game purge mirroring Kalshi: drop in-play rows so the sharp-
        # devig model never sees uncalibrated live prices.
        purged = self.cache.purge_live_rows_for_book("polymarket", now)
        if purged:
            logger.info("polymarket %s: purged %d live rows", sport_key, purged)

        try:
            events = await self._fetch_gamma_events()
        except PolymarketAPIError as e:
            logger.warning("polymarket %s: %s", sport_key, e)
            return

        matcher = self._matcher()
        rows = normalize_events(
            events,
            sport_key=sport_key,
            slug_prefixes=sport_cfg.slug_prefixes,
            fetched_at=now,
            match_event=matcher.match,
        )

        if rows:
            self.cache.upsert(rows)
            # Register so the WS consumer picks up new asset_ids on its
            # next reconnect. Idempotent — known assets just refresh
            # their template (no duplicate subscribe attempts).
            self._ingestor.register_rows(rows)

        self._last_cycle_at = now
        self._last_cycle_rows[sport_key] = len(rows)

    async def refresh_now(self, sport_keys: list[str] | None = None) -> dict:
        """Trigger an immediate cycle for the given sports (or all configured
        sports if None). Sports run in parallel. Mirrors KalshiFetcher's
        for UI-button parity."""
        cfg = self._load_config()
        targets = sport_keys or list(cfg.sports.keys())
        t0 = datetime.now(timezone.utc)
        # Invalidate the shared Gamma cache so refresh actually re-fetches.
        async with self._gamma_lock:
            self._gamma_cache = None
        results = await asyncio.gather(
            *(self._run_sport_cycle(s) for s in targets if s in cfg.sports),
            return_exceptions=True,
        )
        errors = [str(r) for r in results if isinstance(r, Exception)]
        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        return {
            "status": "ok" if not errors else "partial",
            "sports_refreshed": targets,
            "duration_s": round(duration, 2),
            "errors": errors,
            "last_cycle_rows": dict(self._last_cycle_rows),
        }
