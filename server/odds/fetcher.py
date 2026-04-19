from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import Config
from ..sports import Sport
from ..user_settings import UserSettingsStore
from .cache import OddsCache
from .client import OddsAPIClient, OddsAPIError
from .market_config import MarketConfig, TierConfig
from .normalize import normalize_odds_response


logger = logging.getLogger(__name__)


class FetcherRegistry:
    """Multi-sport, multi-tier fetcher. One APScheduler job per (sport, tier).

    `main` uses the game-level endpoint (one call per sport_key per tick —
    tennis has multiple sport keys, so the main tier iterates them all).
    Per-event tiers iterate the cached events for that sport and call the
    per-event endpoint for each. All writes go through the shared cache,
    tagged with `sport_key`.

    Runtime controls: start_all() / stop_all(). No backend restart needed.
    """

    def __init__(
        self,
        config: Config,
        sports: list[Sport],
        cache: OddsCache,
        client: OddsAPIClient,
        settings_store: UserSettingsStore,
    ):
        self.config = config
        self.sports = sports
        self.cache = cache
        self.client = client
        self.settings_store = settings_store
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._last_error: dict[str, str] = {}
        self._event_refresh_ts: dict[str, float] = {}
        self._resolved_keys: dict[str, list[str]] = {}
        self._market_cfg: dict[str, MarketConfig] = {}
        self._event_sport_map: dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    def _cfg_for(self, sport: Sport) -> MarketConfig:
        if sport.key not in self._market_cfg:
            self._market_cfg[sport.key] = MarketConfig.load(sport.markets_config)
        return self._market_cfg[sport.key]

    def all_enabled_tiers(self) -> list[tuple[Sport, TierConfig]]:
        """Tiers to schedule — honors both markets.<sport>.toml *and* user
        settings (disabled sports / markets). A tier whose markets list is
        entirely filtered out by the user is dropped."""
        settings = self.settings_store.get()
        out: list[tuple[Sport, TierConfig]] = []
        for sport in self.sports:
            if not settings.is_sport_enabled(sport.key):
                continue
            try:
                cfg = self._cfg_for(sport)
            except Exception:
                logger.exception("Failed to load markets config for %s", sport.key)
                continue
            for tier in cfg.enabled_tiers():
                filtered = settings.filter_markets(sport.key, tier.markets)
                if not filtered:
                    continue
                # Synthesize a TierConfig with the user-filtered market list
                effective = TierConfig(
                    name=tier.name,
                    enabled=tier.enabled,
                    interval_seconds=tier.interval_seconds,
                    regions=tier.regions,
                    markets=filtered,
                    games_window_hours=tier.games_window_hours,
                )
                out.append((sport, effective))
        return out

    def hot_reload(self) -> dict:
        """Call after settings change. If the fetcher is running, restart it so
        the new enabled-tier set takes effect on the next tick. No-op if
        stopped."""
        if not self._running:
            return {"status": "not_running"}
        self.stop_all()
        return self.start_all()

    # ---------- Scheduler control ----------

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        if not self.config.odds_api_key:
            logger.warning("ODDS_API_KEY empty; refusing to start fetcher")
            return {"status": "no_api_key"}

        # Drop cached per-sport MarketConfigs so hot_reload picks up TOML
        # edits that happened between stop and start.
        self._market_cfg.clear()

        enabled = self.all_enabled_tiers()
        if not enabled:
            return {"status": "no_tiers_enabled"}

        now = datetime.now(timezone.utc)
        for sport, tier in enabled:
            self.scheduler.add_job(
                self._tier_runner(sport, tier),
                trigger="interval",
                seconds=tier.interval_seconds,
                next_run_time=now,
                id=f"{sport.key}:{tier.name}",
                replace_existing=True,
                max_instances=1,
            )
        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        labels = [f"{sp.key}:{t.name}@{t.interval_seconds}s" for sp, t in enabled]
        logger.info("Fetcher started: %s", ", ".join(labels))
        return {
            "status": "started",
            "tiers": [f"{sp.key}:{t.name}" for sp, t in enabled],
        }

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

    def _tier_runner(self, sport: Sport, tier: TierConfig) -> Callable:
        if tier.is_main:
            async def run():
                await self._run_main(sport, tier)
            return run
        if tier.name == "player_props":
            async def run():
                await self._run_props(sport, tier)
            return run
        async def run():
            await self._run_per_event(sport, tier)
        return run

    async def _resolve_keys(self, sport: Sport) -> list[str]:
        cached = self._resolved_keys.get(sport.key)
        if cached is not None:
            return cached
        try:
            keys = await self.client.resolve_sport_keys(sport.odds_api_sport_keys)
        except Exception:
            logger.exception("resolve_sport_keys failed for %s", sport.key)
            keys = [k for k in sport.odds_api_sport_keys if not k.endswith("*")]
        self._resolved_keys[sport.key] = keys
        logger.info("sport %s resolves to Odds API keys: %s", sport.key, keys)
        return keys

    async def _run_main(self, sport: Sport, tier: TierConfig) -> None:
        keys = await self._resolve_keys(sport)
        if not keys:
            logger.warning("No Odds API keys active for %s — skipping", sport.key)
            return
        now = datetime.now(timezone.utc)
        total = 0
        last_rate: dict = {}
        for api_key in keys:
            try:
                games, rate = await self.client.fetch_game_level(
                    sport_key=api_key, markets=tier.markets, regions=tier.regions
                )
                last_rate = rate or last_rate
                rows = normalize_odds_response(
                    games, fetched_at=now, sport_key=sport.key
                )
                if rows:
                    self.cache.upsert(rows)
                    total += len(rows)
                # Remember which tournament each event belongs to, for
                # per-event fetches later.
                for game in games:
                    if isinstance(game, dict) and game.get("id"):
                        self._event_sport_map[game["id"]] = api_key
            except OddsAPIError as e:
                logger.warning("main %s key %s: %s", sport.key, api_key, e)
                self._last_error[f"{sport.key}:main"] = str(e)
        self.cache.purge_finished_games(now=now)
        if last_rate:
            self.cache.set_status(
                last_fetch_at=now,
                requests_used=last_rate.get("requests_used"),
                requests_remaining=last_rate.get("requests_remaining"),
                last_error=None,
            )
        logger.info("main %s: %d rows across %d sport keys", sport.key, total, len(keys))

    async def _run_per_event(self, sport: Sport, tier: TierConfig) -> None:
        events = self.cache.distinct_events(
            within_hours_ahead=36, sport_key=sport.key
        )
        if not events:
            return
        now = datetime.now(timezone.utc)
        total = 0
        last_rate: dict = {}
        for ev in events:
            api_key = self._event_sport_map.get(ev["event_id"])
            if not api_key:
                # Fallback to the first resolved key. Works for single-key
                # sports (MLB). For tennis, this may 404; skip if so.
                resolved = await self._resolve_keys(sport)
                if not resolved:
                    continue
                api_key = resolved[0]
            try:
                data, rate = await self.client.fetch_event_markets(
                    sport_key=api_key,
                    event_id=ev["event_id"],
                    markets=tier.markets,
                    regions=tier.regions,
                )
                last_rate = rate or last_rate
                if data:
                    rows = normalize_odds_response(
                        data, fetched_at=now, sport_key=sport.key
                    )
                    if rows:
                        self.cache.upsert(rows)
                        total += len(rows)
            except OddsAPIError as e:
                logger.warning(
                    "%s:%s event %s: %s", sport.key, tier.name, ev["event_id"], e
                )
                self._last_error[f"{sport.key}:{tier.name}"] = str(e)
        if last_rate:
            self.cache.set_status(
                requests_used=last_rate.get("requests_used"),
                requests_remaining=last_rate.get("requests_remaining"),
            )
        logger.info(
            "%s:%s: %d rows across %d events",
            sport.key, tier.name, total, len(events),
        )

    async def _run_props(self, sport: Sport, tier: TierConfig) -> None:
        window = tier.games_window_hours or 3
        events = self.cache.distinct_events(
            within_hours_ahead=window, sport_key=sport.key
        )
        if not events:
            return
        now = datetime.now(timezone.utc)
        total = 0
        last_rate: dict = {}
        for ev in events:
            api_key = self._event_sport_map.get(ev["event_id"])
            if not api_key:
                resolved = await self._resolve_keys(sport)
                if not resolved:
                    continue
                api_key = resolved[0]
            try:
                data, rate = await self.client.fetch_event_markets(
                    sport_key=api_key,
                    event_id=ev["event_id"],
                    markets=tier.markets,
                    regions=tier.regions,
                )
                last_rate = rate or last_rate
                if data:
                    rows = normalize_odds_response(
                        data, fetched_at=now, sport_key=sport.key
                    )
                    if rows:
                        self.cache.upsert(rows)
                        total += len(rows)
            except Exception:
                logger.exception("props event error: %s", ev["event_id"])
        if last_rate:
            self.cache.set_status(
                requests_used=last_rate.get("requests_used"),
                requests_remaining=last_rate.get("requests_remaining"),
            )
        logger.info(
            "%s:props: %d rows across %d events in %dh window",
            sport.key, total, len(events), window,
        )

    # ---------- On-demand per-event refresh ----------

    async def refresh_event(self, event_id: str) -> dict:
        # Debounce (first sport's on_demand config; they're all 60s by default)
        debounce = 60
        for sp in self.sports:
            try:
                cfg = self._cfg_for(sp)
                if cfg.on_demand.enabled:
                    debounce = cfg.on_demand.debounce_seconds
                    break
            except Exception:
                pass
        now_ts = time.time()
        last = self._event_refresh_ts.get(event_id, 0)
        if now_ts - last < debounce:
            return {
                "status": "debounced",
                "retry_after_seconds": int(debounce - (now_ts - last)),
            }
        self._event_refresh_ts[event_id] = now_ts

        # Find which sport this event belongs to
        row = self.cache.distinct_events()
        sport_key = next(
            (e["sport_key"] for e in row if e["event_id"] == event_id), None
        )
        if not sport_key:
            return {"status": "unknown_event", "event_id": event_id}
        sport = next((s for s in self.sports if s.key == sport_key), None)
        if not sport:
            return {"status": "unknown_sport", "event_id": event_id}

        api_key = self._event_sport_map.get(event_id)
        if not api_key:
            resolved = await self._resolve_keys(sport)
            if not resolved:
                return {"status": "no_api_keys"}
            api_key = resolved[0]

        cfg = self._cfg_for(sport)
        polled: list[str] = []
        now = datetime.now(timezone.utc)
        for tier in cfg.enabled_tiers():
            if tier.is_main:
                continue
            try:
                data, _ = await self.client.fetch_event_markets(
                    sport_key=api_key,
                    event_id=event_id,
                    markets=tier.markets,
                    regions=tier.regions,
                )
                if data:
                    rows = normalize_odds_response(
                        data, fetched_at=now, sport_key=sport.key
                    )
                    if rows:
                        self.cache.upsert(rows)
                polled.append(tier.name)
            except Exception:
                logger.exception("on-demand %s:%s failed", sport.key, tier.name)
        return {"status": "ok", "polled": polled, "event_id": event_id}
