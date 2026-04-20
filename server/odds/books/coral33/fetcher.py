from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ...cache import OddsCache
from .client import Coral33APIError, Coral33Client
from .event_matcher import Coral33EventMatcher
from .mapping import Coral33Config, load_coral33_config
from .normalizer import normalize_league_lines


logger = logging.getLogger(__name__)


# Cadence defaults — overridable per sport via coral33.toml later if needed.
MAIN_PERIOD_INTERVAL = 60
ALT_INTERVAL = 90
CAPTCHA_BACKOFF = 300


class Coral33Fetcher:
    """Per-sport poller for coral33.com odds. Scoped to the same `OddsCache`
    used by the Odds API fetcher, so rows land alongside existing events under
    a shared event_id.

    Owned by main.create_app(); its start/stop lifecycle is independent of
    the Odds API `FetcherRegistry` so users can toggle it off via .env
    (`CORAL33_ENABLED=false`) without affecting the main fetcher.
    """

    def __init__(
        self,
        customer_id: str,
        password: str,
        cache: OddsCache,
        config_path: Path,
    ):
        self.customer_id = customer_id
        self.password = password
        self.cache = cache
        self.config_path = config_path
        self.client = Coral33Client(customer_id=customer_id, password=password)
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._config: Coral33Config | None = None
        self._captcha_until: float = 0.0  # epoch seconds

    @property
    def is_running(self) -> bool:
        return self._running

    def _load_config(self) -> Coral33Config:
        if self._config is None:
            self._config = load_coral33_config(self.config_path)
        return self._config

    def _matcher(self) -> Coral33EventMatcher:
        cfg = self._load_config()

        def events_for(sport_key: str) -> list[dict]:
            return self.cache.distinct_events(sport_key=sport_key)

        return Coral33EventMatcher(events_for, team_aliases=cfg.team_aliases)

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        if not self.customer_id or not self.password:
            return {"status": "no_credentials"}
        self._config = None  # pick up TOML edits
        cfg = self._load_config()
        if not cfg.sports:
            return {"status": "no_sports_configured"}

        now = datetime.now(timezone.utc)
        for sport_key, sc in cfg.sports.items():
            if sc.subtypes_main:
                self.scheduler.add_job(
                    self._runner(sport_key, "main"),
                    trigger="interval",
                    seconds=MAIN_PERIOD_INTERVAL,
                    next_run_time=now,
                    id=f"coral33:{sport_key}:main",
                    replace_existing=True,
                    max_instances=1,
                )
            if sc.subtypes_alt:
                self.scheduler.add_job(
                    self._runner(sport_key, "alt"),
                    trigger="interval",
                    seconds=ALT_INTERVAL,
                    next_run_time=now,
                    id=f"coral33:{sport_key}:alt",
                    replace_existing=True,
                    max_instances=1,
                )

        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        logger.info(
            "coral33 fetcher started: %d sports",
            len(cfg.sports),
        )
        return {"status": "started", "sports": list(cfg.sports.keys())}

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("coral33: error removing jobs")
        self._running = False
        logger.info("coral33 fetcher stopped")
        return {"status": "stopped"}

    def shutdown(self) -> None:
        try:
            self.stop_all()
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ---------- Tier runner ----------

    def _runner(self, sport_key: str, tier: str):
        async def run():
            await self._run_tier(sport_key, tier)
        return run

    async def _run_tier(self, sport_key: str, tier: str) -> None:
        import time
        if time.time() < self._captcha_until:
            logger.info("coral33 %s:%s: backing off (captcha)", sport_key, tier)
            return

        cfg = self._load_config()
        sport_cfg = cfg.sports.get(sport_key)
        if sport_cfg is None:
            return

        if tier == "main":
            calls = sport_cfg.main_period_calls
            is_alt = False
        elif tier == "alt":
            calls = sport_cfg.alt_calls
            is_alt = True
        else:
            return

        if not calls:
            return

        matcher = self._matcher()
        now = datetime.now(timezone.utc)
        total = 0
        captcha_hit = False
        for sport_type, subtype, period in calls:
            try:
                data = await self.client.get_league_lines(sport_type, subtype, period)
            except Coral33APIError as e:
                logger.warning(
                    "coral33 %s:%s %s/%s/%s: %s",
                    sport_key, tier, sport_type, subtype, period, e,
                )
                continue
            if data.get("CaptchaRequired"):
                captcha_hit = True
                logger.warning(
                    "coral33 captcha on %s/%s/%s — backing off",
                    sport_type, subtype, period,
                )
                continue
            rows = normalize_league_lines(
                data, period=period, sport_key=sport_key,
                fetched_at=now, match_event=matcher.match,
                is_alternate=is_alt,
            )
            if rows:
                self.cache.upsert(rows)
                total += len(rows)

        if captcha_hit:
            self._captcha_until = time.time() + CAPTCHA_BACKOFF

        logger.info(
            "coral33 %s:%s: %d rows across %d calls",
            sport_key, tier, total, len(calls),
        )
