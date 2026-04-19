from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import Config
from .cache import OddsCache
from .client import OddsAPIClient, OddsAPIError
from .market_config import MarketConfig, TierConfig
from .normalize import normalize_odds_response


logger = logging.getLogger(__name__)


class FetcherRegistry:
    """Multi-tier fetcher. Each [tier] in markets.toml gets its own APScheduler
    job. `main` uses the game-level endpoint (one call per tick); per-event
    tiers iterate today's cached events and call the per-event endpoint for
    each. All tiers write to the same cache.

    Runtime controls: start_all() / stop_all(). Backed by
    POST /api/fetcher/{start,stop} — no backend restart required to flip.
    """

    def __init__(
        self,
        config: Config,
        market_cfg: MarketConfig,
        cache: OddsCache,
        client: OddsAPIClient,
    ):
        self.config = config
        self.market_cfg = market_cfg
        self.cache = cache
        self.client = client
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._last_error: dict[str, str] = {}
        self._event_refresh_ts: dict[str, float] = {}  # for on-demand debounce

    @property
    def is_running(self) -> bool:
        return self._running

    # ---------- Scheduler control ----------

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        if not self.config.odds_api_key:
            logger.warning("ODDS_API_KEY empty; refusing to start fetcher")
            return {"status": "no_api_key"}

        enabled = self.market_cfg.enabled_tiers()
        if not enabled:
            logger.warning("No tiers enabled in markets.toml")
            return {"status": "no_tiers_enabled"}

        now = datetime.now(timezone.utc)
        for tier in enabled:
            self.scheduler.add_job(
                self._tier_runner(tier),
                trigger="interval",
                seconds=tier.interval_seconds,
                next_run_time=now,
                id=f"tier:{tier.name}",
                replace_existing=True,
                max_instances=1,
            )
        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        logger.info(
            "Fetcher started: %s",
            ", ".join(f"{t.name}@{t.interval_seconds}s" for t in enabled),
        )
        return {"status": "started", "tiers": [t.name for t in enabled]}

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("Error removing jobs")
        self._running = False
        logger.info("Fetcher stopped — serving frozen cache")
        return {"status": "stopped"}

    def shutdown(self) -> None:
        try:
            self.stop_all()
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ---------- Tier runners ----------

    def _tier_runner(self, tier: TierConfig) -> Callable:
        if tier.is_main:
            async def run():
                await self._run_main(tier)
            return run
        if tier.name == "player_props":
            async def run():
                await self._run_props(tier)
            return run
        # alternates, first_innings → poll all current events
        async def run():
            await self._run_per_event(tier, events_filter=None)
        return run

    async def _run_main(self, tier: TierConfig) -> None:
        now = datetime.now(timezone.utc)
        try:
            games, rate = await self.client.fetch_game_level(
                markets=tier.markets, regions=tier.regions
            )
            rows = normalize_odds_response(games, fetched_at=now)
            if rows:
                self.cache.upsert(rows)
            self.cache.purge_finished_games(now=now)
            self.cache.set_status(
                last_fetch_at=now,
                requests_used=rate.get("requests_used"),
                requests_remaining=rate.get("requests_remaining"),
                last_error=None,
            )
            self._last_error.pop(tier.name, None)
        except OddsAPIError as e:
            logger.exception("main tier error")
            self._last_error[tier.name] = str(e)
            self.cache.set_status(last_error=f"main: {e}")
        except Exception as e:
            logger.exception("main tier unhandled")
            self._last_error[tier.name] = repr(e)

    async def _run_per_event(self, tier: TierConfig, events_filter) -> None:
        """Poll per-event endpoint for every cached event; merge + upsert."""
        events = self.cache.distinct_events(within_hours_ahead=36)
        if events_filter:
            events = [e for e in events if events_filter(e)]
        if not events:
            return
        now = datetime.now(timezone.utc)
        total_rows = 0
        last_rate: dict = {}
        for ev in events:
            try:
                data, rate = await self.client.fetch_event_markets(
                    event_id=ev["event_id"],
                    markets=tier.markets,
                    regions=tier.regions,
                )
                last_rate = rate or last_rate
                if data:
                    rows = normalize_odds_response(data, fetched_at=now)
                    if rows:
                        self.cache.upsert(rows)
                        total_rows += len(rows)
            except OddsAPIError as e:
                logger.warning("tier %s event %s: %s", tier.name, ev["event_id"], e)
                self._last_error[tier.name] = str(e)
            except Exception as e:
                logger.exception("tier %s event %s unhandled", tier.name, ev["event_id"])
                self._last_error[tier.name] = repr(e)
        if last_rate:
            self.cache.set_status(
                requests_used=last_rate.get("requests_used"),
                requests_remaining=last_rate.get("requests_remaining"),
            )
        logger.info("tier %s: %d rows across %d events", tier.name, total_rows, len(events))

    async def _run_props(self, tier: TierConfig) -> None:
        """Same as per-event, filtered to games in [now, now+games_window_hours]."""
        window = tier.games_window_hours or 3
        events = self.cache.distinct_events(within_hours_ahead=window)
        if not events:
            return
        await self._run_per_event(tier, events_filter=lambda e: e in events)

    # ---------- On-demand per-event refresh ----------

    async def refresh_event(self, event_id: str) -> dict:
        cfg = self.market_cfg.on_demand
        if not cfg.enabled:
            return {"status": "disabled"}
        now_ts = time.time()
        last = self._event_refresh_ts.get(event_id, 0)
        if now_ts - last < cfg.debounce_seconds:
            return {
                "status": "debounced",
                "retry_after_seconds": int(cfg.debounce_seconds - (now_ts - last)),
            }
        self._event_refresh_ts[event_id] = now_ts

        polled: list[str] = []
        now = datetime.now(timezone.utc)
        for tier in self.market_cfg.enabled_tiers():
            if tier.is_main:
                continue
            try:
                data, _ = await self.client.fetch_event_markets(
                    event_id=event_id, markets=tier.markets, regions=tier.regions
                )
                if data:
                    rows = normalize_odds_response(data, fetched_at=now)
                    if rows:
                        self.cache.upsert(rows)
                polled.append(tier.name)
            except Exception:
                logger.exception("on-demand tier %s failed", tier.name)
        return {"status": "ok", "polled": polled, "event_id": event_id}
