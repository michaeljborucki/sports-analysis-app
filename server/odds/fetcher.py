from __future__ import annotations

import asyncio
import logging
import os
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


# Bound on simultaneous per-event Odds API requests within one tier run.
# Set ODDS_API_CONCURRENCY=1 to fall back to pre-2026-05-12 serial behavior.
#
# Default 4 is calibrated to stay under the Odds API's per-second freq
# limit. Empirically 8 triggers 429 EXCEEDED_FREQ_LIMIT on MLB-sized
# slates — the persistent HTTP/2 client completes 8 requests in well
# under a second, exceeding the plan's req/sec ceiling. The client adds
# a 429-aware retry with backoff so transient bursts don't drop events,
# but the steady-state target is "comfortably under the limit." Raise
# this if your plan tier supports more (Odds API publishes per-tier
# req/sec caps on their pricing page).
ODDS_API_CONCURRENCY = max(1, int(os.environ.get("ODDS_API_CONCURRENCY", "4")))


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

        # ODDS_POLL_INTERVAL env overrides the main-tier cadence across every
        # sport. Per-event tiers (alternates / periods / player_props) keep
        # their TOML defaults — they iterate dozens of events sequentially
        # and can't keep up at sub-5-min cadence without overlapping. The
        # freshness chip in the UI reads `last_fetch_at`, which is only
        # stamped on main-tier completion, so this knob is what actually
        # controls how fresh the chip looks.
        main_override = (
            self.config.odds_poll_interval
            if self.config.odds_poll_interval
            and self.config.odds_poll_interval > 0
            else None
        )

        now = datetime.now(timezone.utc)
        scheduled: list[tuple[Sport, TierConfig, int]] = []
        for sport, tier in enabled:
            interval = tier.interval_seconds
            if tier.name == "main" and main_override:
                interval = main_override
            self.scheduler.add_job(
                self._tier_runner(sport, tier),
                trigger="interval",
                seconds=interval,
                next_run_time=now,
                id=f"{sport.key}:{tier.name}",
                replace_existing=True,
                max_instances=1,
            )
            scheduled.append((sport, tier, interval))
        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        labels = [f"{sp.key}:{t.name}@{i}s" for sp, t, i in scheduled]
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

    # ---------- Ad-hoc refresh ----------

    def refresh_all_now(self) -> dict:
        """Fire every enabled tier once, in parallel, right now — independent
        of the scheduled cadence. Fire-and-forget: returns a summary dict
        immediately while the tasks run in the background. Used by the UI
        refresh button so the user can force a pull without waiting for the
        next 5-minute tick.

        Safe to call while scheduled jobs are active — each tier runner
        writes via UPSERT, so concurrent pulls only cost a duplicate request
        at worst, they never corrupt the cache.
        """
        enabled = self.all_enabled_tiers()
        if not enabled:
            return {"status": "no_tiers_enabled", "triggered": []}
        if not self.config.odds_api_key:
            return {"status": "no_api_key", "triggered": []}
        triggered: list[str] = []
        for sport, tier in enabled:
            runner = self._tier_runner(sport, tier)
            # create_task schedules on the running event loop; returns
            # before the task actually executes. The task completes or
            # errors in the background; errors are already logged inside
            # each tier runner.
            asyncio.create_task(runner())
            triggered.append(f"{sport.key}:{tier.name}")
        logger.info("refresh_all_now: triggered %d tiers", len(triggered))
        return {"status": "triggered", "triggered": triggered}

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
        # Row-level TTL — clears rows whose book stopped posting (UPSERT
        # alone never removes them). Runs piggy-backed on each main-tier
        # cycle so it's frequent without a separate scheduler.
        stale = self.cache.purge_stale_rows(now=now)
        if stale:
            logger.info("purged %d stale rows (fetched_at older than TTL)", stale)
        # Stamp freshness regardless of whether the API returned rate-limit
        # headers — without this, the UI's "stale Nm" chip drifts arbitrarily
        # far when the API drops headers (cached responses, edge errors, etc.)
        # even though tiers are completing successfully.
        self.cache.set_status(
            last_fetch_at=now,
            requests_used=last_rate.get("requests_used") if last_rate else None,
            requests_remaining=last_rate.get("requests_remaining") if last_rate else None,
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
        # Resolve fallback API key once (vs once per event in the old loop).
        resolved_fallback = await self._resolve_keys(sport)

        # Per-event fetch: returns (rows_appended_count, rate_info). Wrapped
        # in a semaphore so we cap simultaneous in-flight Odds API requests.
        sem = asyncio.Semaphore(ODDS_API_CONCURRENCY)

        async def fetch_one(ev: dict) -> tuple[int, dict]:
            event_id = ev["event_id"]
            api_key = self._event_sport_map.get(event_id)
            if not api_key:
                if not resolved_fallback:
                    return 0, {}
                api_key = resolved_fallback[0]
            async with sem:
                try:
                    data, rate = await self.client.fetch_event_markets(
                        sport_key=api_key,
                        event_id=event_id,
                        markets=tier.markets,
                        regions=tier.regions,
                    )
                except OddsAPIError as e:
                    logger.warning(
                        "%s:%s event %s: %s",
                        sport.key, tier.name, event_id, e,
                    )
                    self._last_error[f"{sport.key}:{tier.name}"] = str(e)
                    return 0, {}
            if not data:
                return 0, rate or {}
            rows = normalize_odds_response(
                data, fetched_at=now, sport_key=sport.key
            )
            if not rows:
                return 0, rate or {}
            # Cache upsert is sqlite + GIL-bound; safe to call from the
            # task body since it's a fast synchronous operation. Keeping
            # it inside the task means rows land as each event resolves
            # rather than buffering until the whole batch completes.
            self.cache.upsert(rows)
            return len(rows), rate or {}

        results = await asyncio.gather(
            *(fetch_one(ev) for ev in events), return_exceptions=False,
        )
        total = sum(r[0] for r in results)
        # last_rate: pick the most recent rate-info dict (any non-empty one
        # is fine since they reflect the same plan-tier counters).
        last_rate: dict = {}
        for _, r in reversed(results):
            if r:
                last_rate = r
                break
        # Always stamp freshness — see _run_main note. last_rate may be
        # empty if the API skipped rate headers; we still want the chip to
        # know rows just landed.
        self.cache.set_status(
            last_fetch_at=datetime.now(timezone.utc),
            requests_used=last_rate.get("requests_used") if last_rate else None,
            requests_remaining=last_rate.get("requests_remaining") if last_rate else None,
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
        resolved_fallback = await self._resolve_keys(sport)

        # Same parallelism pattern as _run_per_event — props payloads are
        # the largest of any tier (a 12-market call on a big NBA slate can
        # be 100 KB+), so concurrency here has the biggest wall-clock impact.
        sem = asyncio.Semaphore(ODDS_API_CONCURRENCY)

        async def fetch_one(ev: dict) -> tuple[int, dict]:
            event_id = ev["event_id"]
            api_key = self._event_sport_map.get(event_id)
            if not api_key:
                if not resolved_fallback:
                    return 0, {}
                api_key = resolved_fallback[0]
            async with sem:
                try:
                    data, rate = await self.client.fetch_event_markets(
                        sport_key=api_key,
                        event_id=event_id,
                        markets=tier.markets,
                        regions=tier.regions,
                    )
                except Exception:
                    logger.exception("props event error: %s", event_id)
                    return 0, {}
            if not data:
                return 0, rate or {}
            rows = normalize_odds_response(
                data, fetched_at=now, sport_key=sport.key
            )
            if not rows:
                return 0, rate or {}
            self.cache.upsert(rows)
            return len(rows), rate or {}

        results = await asyncio.gather(
            *(fetch_one(ev) for ev in events), return_exceptions=False,
        )
        total = sum(r[0] for r in results)
        last_rate: dict = {}
        for _, r in reversed(results):
            if r:
                last_rate = r
                break
        # Always stamp freshness — see _run_main note.
        self.cache.set_status(
            last_fetch_at=datetime.now(timezone.utc),
            requests_used=last_rate.get("requests_used") if last_rate else None,
            requests_remaining=last_rate.get("requests_remaining") if last_rate else None,
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
