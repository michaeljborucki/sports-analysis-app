from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
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


# A5: re-resolve sport→Odds-API key mappings every 24h so tournament
# rotations (ATP draws, soccer matchdays) get picked up without a
# server restart. On refresh failure with a prior good cache, keep
# the cached set AND don't update the timestamp — next caller retries.
_RESOLVED_KEYS_TTL = timedelta(hours=24)


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
        self._resolved_keys: dict[str, tuple[list[str], datetime]] = {}
        self._market_cfg: dict[str, MarketConfig] = {}
        self._event_sport_map: dict[str, str] = {}
        # Single per-instance semaphore caps simultaneous in-flight Odds
        # API requests across the WHOLE fetcher — main-tier sport-key fan-
        # out, per-event tier event fan-out, props tier event fan-out, and
        # refresh_all_now's tier-runner fan-out all acquire it. One shared
        # cap is the only safe design: per-tier semaphores let parallel
        # tier ticks collectively exceed the plan's req/sec limit and
        # trigger 429 EXCEEDED_FREQ_LIMIT bans.
        self._sem = asyncio.Semaphore(ODDS_API_CONCURRENCY)

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
                # Default apscheduler grace is 1s — way too tight when the
                # event loop is busy with per-event tier HTTP I/O. With 1s
                # grace, main-tier firings get silently skipped whenever
                # they slip behind a previous instance, leaving the
                # `last_fetch_at` chip stale for 10-15 min stretches.
                # 120s lets the next slot pick up the deferred firing.
                misfire_grace_time=120,
                # Jitter (matches Kalshi + coral33). Without it, all 27
                # (sport × tier) jobs fire on the same wall-clock second
                # at startup and drift in lockstep — bursting the Odds
                # API's req/sec ceiling on cycle starts even though
                # _sem caps concurrent requests.
                jitter=30,
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
        """Fire every enabled tier once, right now — independent of the
        scheduled cadence. Fire-and-forget: returns a summary dict
        immediately while the tasks run in the background. Used by the UI
        refresh button so the user can force a pull without waiting for the
        next 5-minute tick.

        Safe to call while scheduled jobs are active — each tier runner
        writes via UPSERT, so concurrent pulls only cost a duplicate request
        at worst, they never corrupt the cache.

        Concurrency note: ~27 tiers × N events fan out to hundreds of
        Odds API requests. `self._sem` already caps the in-flight HTTP
        count, but we ALSO cap the number of concurrent TIER-RUNNERS at
        ODDS_API_CONCURRENCY so we don't queue 100+ semaphore-waiters at
        once (which would make every refresh click take 30s+ to drain).
        """
        enabled = self.all_enabled_tiers()
        if not enabled:
            return {"status": "no_tiers_enabled", "triggered": []}
        if not self.config.odds_api_key:
            return {"status": "no_api_key", "triggered": []}

        # Outer cap on simultaneous tier-runner tasks. Reuses the same
        # value as `_sem` — small enough to keep the request queue
        # tractable, large enough to actually parallelize across sports.
        runner_sem = asyncio.Semaphore(ODDS_API_CONCURRENCY)

        async def _bounded(sport: Sport, tier: TierConfig) -> None:
            async with runner_sem:
                try:
                    await self._tier_runner(sport, tier)()
                except Exception:
                    logger.exception(
                        "refresh_all_now: tier %s:%s failed",
                        sport.key, tier.name,
                    )

        triggered: list[str] = []
        for sport, tier in enabled:
            asyncio.create_task(_bounded(sport, tier))
            triggered.append(f"{sport.key}:{tier.name}")
        logger.info(
            "refresh_all_now: triggered %d tiers (outer cap=%d)",
            len(triggered), ODDS_API_CONCURRENCY,
        )
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

    async def _resolve_keys(
        self, sport: Sport, now: datetime | None = None,
    ) -> list[str]:
        """Resolve a sport's Odds-API key set, cached with 24h TTL.

        On refresh failure (cached entry exists, TTL expired, resolve
        raises), returns the previously-cached keys unchanged AND does
        not update the timestamp — next call retries on whatever
        cadence the caller runs.

        On first-time failure (no cached entry, resolve raises), falls
        back to the static-key subset (strips pattern entries) and
        caches that with the current timestamp to avoid retry-storming
        on every tier tick.

        `now` is injected for testability; production callers omit it.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        cached = self._resolved_keys.get(sport.key)
        if cached is not None:
            keys, cached_at = cached
            if now - cached_at < _RESOLVED_KEYS_TTL:
                return keys
        # Resolve fresh (first-time OR TTL expired).
        try:
            keys = await self.client.resolve_sport_keys(sport.odds_api_sport_keys)
        except Exception:
            logger.exception("resolve_sport_keys failed for %s", sport.key)
            if cached is not None:
                # Refresh failure with a prior good cache → keep it,
                # don't update timestamp. Next call retries.
                return cached[0]
            # First-time failure → fall back to static keys, cache to
            # avoid retry-storm on every tier tick.
            keys = [k for k in sport.odds_api_sport_keys if not k.endswith("*")]
        # Log when refresh changed the resolved set (new tournaments
        # rotated in, old ones out).
        if cached is not None and keys != cached[0]:
            logger.info(
                "sport %s key set changed: %s → %s",
                sport.key, cached[0], keys,
            )
        else:
            logger.info("sport %s resolves to Odds API keys: %s", sport.key, keys)
        self._resolved_keys[sport.key] = (keys, now)
        return keys

    async def _run_main(self, sport: Sport, tier: TierConfig) -> None:
        keys = await self._resolve_keys(sport)
        if not keys:
            logger.warning("No Odds API keys active for %s — skipping", sport.key)
            return
        now = datetime.now(timezone.utc)

        # Fan out across sport keys (tennis has 4-8 ATP/WTA tournament
        # keys; soccer has ~12 league keys). Serial iteration cost 3s+
        # of wall time per cycle even when each key returns in <500ms.
        # Same `self._sem` as per-event/props tiers, so cross-tier
        # concurrency stays under ODDS_API_CONCURRENCY.
        async def fetch_one(api_key: str) -> tuple[int, dict, list[dict]]:
            async with self._sem:
                try:
                    games, rate = await self.client.fetch_game_level(
                        sport_key=api_key,
                        markets=tier.markets,
                        regions=tier.regions,
                    )
                except OddsAPIError as e:
                    logger.warning("main %s key %s: %s", sport.key, api_key, e)
                    self._last_error[f"{sport.key}:main"] = str(e)
                    return 0, {}, []
            rows = normalize_odds_response(
                games, fetched_at=now, sport_key=sport.key
            )
            if rows:
                # Cache upsert is GIL-bound sqlite, safe to call from the
                # task body — lands rows as each key resolves rather than
                # buffering until the whole batch completes.
                self.cache.upsert(rows)
            return len(rows), rate or {}, games

        results = await asyncio.gather(
            *(fetch_one(k) for k in keys), return_exceptions=True,
        )

        total = 0
        last_rate: dict = {}
        for idx, r in enumerate(results):
            if isinstance(r, Exception):
                # An OddsAPIError is already logged + caught inside
                # fetch_one; anything reaching here is an unexpected
                # exception (normalize bug, OOM, etc.). Don't kill the
                # cycle — log and continue so a single bad key doesn't
                # block the others.
                logger.exception(
                    "main %s key %s: unexpected error", sport.key, keys[idx],
                )
                continue
            n_rows, rate, games = r
            total += n_rows
            if rate:
                last_rate = rate
            # Remember which tournament each event belongs to, for
            # per-event fetches later.
            for game in games:
                if isinstance(game, dict) and game.get("id"):
                    self._event_sport_map[game["id"]] = keys[idx]

        self.cache.purge_finished_games(now=now)
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
        window = tier.games_window_hours or 36
        events = self.cache.distinct_events(
            within_hours_ahead=window, sport_key=sport.key
        )
        if not events:
            return
        now = datetime.now(timezone.utc)
        # Resolve fallback API key once (vs once per event in the old loop).
        resolved_fallback = await self._resolve_keys(sport)

        # Per-event fetch: returns (rows_appended_count, rate_info). Wrapped
        # in `self._sem` so we cap simultaneous in-flight Odds API requests
        # ACROSS the whole fetcher (main + per-event + props).
        async def fetch_one(ev: dict) -> tuple[int, dict]:
            event_id = ev["event_id"]
            api_key = self._event_sport_map.get(event_id)
            if not api_key:
                if not resolved_fallback:
                    return 0, {}
                api_key = resolved_fallback[0]
            async with self._sem:
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
        # Shares `self._sem` with main + per-event tiers — the cap is global
        # across the fetcher, not per-tier.
        async def fetch_one(ev: dict) -> tuple[int, dict]:
            event_id = ev["event_id"]
            api_key = self._event_sport_map.get(event_id)
            if not api_key:
                if not resolved_fallback:
                    return 0, {}
                api_key = resolved_fallback[0]
            async with self._sem:
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

        # Find which sport this event belongs to. Indexed lookup against
        # the PK rather than the previous full-table `distinct_events()`
        # scan — refresh_event runs on every UI "refresh this game" click.
        sport_key = self.cache.event_sport_key(event_id)
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
