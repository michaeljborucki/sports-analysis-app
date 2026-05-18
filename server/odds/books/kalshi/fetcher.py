from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ...cache import OddsCache
from .client import KalshiAPIError, KalshiClient
from .event_matcher import KalshiEventMatcher
from .mapping import KalshiConfig, load_kalshi_config
from .normalizer import normalize_markets


logger = logging.getLogger(__name__)


# 15s base cadence — Kalshi's reads are free and unauthenticated, so we
# can be aggressive vs Odds API's metered 60s. Jitter ±3s prevents every
# series from polling on the exact same wallclock second.
CYCLE_INTERVAL = int(os.environ.get("KALSHI_CYCLE_SECONDS", "15"))
CYCLE_JITTER   = int(os.environ.get("KALSHI_CYCLE_JITTER", "3"))

# Per-sport startup stagger so we don't fire all 4 sport jobs in the same
# wallclock second on boot.
_STARTUP_STAGGER = (0, max(2, min(15, CYCLE_INTERVAL)))


class KalshiFetcher:
    """Per-sport poller for Kalshi's public REST API.

    Mirrors `Coral33Fetcher`'s lifecycle (start_all / stop_all / shutdown +
    APScheduler-driven jobs + per-cycle status tracking) so cache_mode.py
    can flip both fetchers identically. Differences from coral33:

      - No auth. No JWT refresh. No captcha back-off.
      - Cadence ~15s (vs coral33's 60s) — public API is free.
      - One HTTP call per sport per cycle (vs coral33's main/alt/prop tiers).
      - Phase 1: h2h only. Phase 2 will fan out into multiple series per
        sport (spreads, totals, team_totals, periods, NRFI, F5) — the
        config schema already carries empty stub lists for those.
    """

    def __init__(
        self,
        cache: OddsCache,
        config_path: Path,
    ):
        self.cache = cache
        self.config_path = config_path
        self.client = KalshiClient()
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._config: KalshiConfig | None = None
        # Observability for the Settings / manual-refresh UI.
        self._last_cycle_at: datetime | None = None
        self._last_cycle_rows: dict[str, int] = {}   # sport → row count

    @property
    def is_running(self) -> bool:
        return self._running

    def _load_config(self) -> KalshiConfig:
        if self._config is None:
            self._config = load_kalshi_config(self.config_path)
        return self._config

    def _matcher(self) -> KalshiEventMatcher:
        cfg = self._load_config()

        def events_for(sport_key: str) -> list[dict]:
            return self.cache.distinct_events(sport_key=sport_key)

        return KalshiEventMatcher(events_for, team_aliases=cfg.team_aliases)

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        self._config = None  # pick up TOML edits across restarts
        cfg = self._load_config()
        if not cfg.sports:
            return {"status": "no_sports_configured"}

        now = datetime.now(timezone.utc)
        scheduled: list[str] = []
        for sport_key, sc in cfg.sports.items():
            if not sc.series_main:
                continue
            first_fire = now + timedelta(seconds=random.uniform(*_STARTUP_STAGGER))
            self.scheduler.add_job(
                self._sport_cycle_runner(sport_key),
                trigger="interval",
                seconds=CYCLE_INTERVAL,
                jitter=CYCLE_JITTER,
                next_run_time=first_fire,
                id=f"kalshi:{sport_key}",
                replace_existing=True,
                max_instances=1,
            )
            scheduled.append(sport_key)

        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        logger.info(
            "kalshi fetcher started: %d sports (cycle %ds ±%ds)",
            len(scheduled), CYCLE_INTERVAL, CYCLE_JITTER,
        )
        return {"status": "started", "sports": scheduled}

    @property
    def status(self) -> dict:
        """Snapshot of fetcher health for the UI. Mirrors coral33's status
        shape (so the frontend can poll both endpoints with the same
        component). `jwt_authenticated` is True-by-fiat — Kalshi reads are
        unauthenticated, but we keep the field so any UI that displays an
        "auth" badge for coral33 also shows green for kalshi."""
        return {
            "running": self._running,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "last_cycle_rows": dict(self._last_cycle_rows),
            "jwt_authenticated": True,
        }

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("kalshi: error removing jobs")
        self._running = False
        logger.info("kalshi fetcher stopped")
        return {"status": "stopped"}

    def shutdown(self) -> None:
        try:
            self.stop_all()
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        # Drop the HTTP client too so we don't leak a connection pool on
        # process exit.
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

    async def _run_sport_cycle(self, sport_key: str) -> None:
        cfg = self._load_config()
        sport_cfg = cfg.sports.get(sport_key)
        if sport_cfg is None or not sport_cfg.series_main:
            return

        now = datetime.now(timezone.utc)
        # Live-game purge: Kalshi keeps trading after kickoff (their YES/NO
        # lifecycle is post-tip-off-trading-allowed). Mirror coral33's
        # behavior and drop rows for games that have started — our sharp-
        # devig model isn't calibrated against in-play prices.
        purged = self.cache.purge_live_rows_for_book("kalshi", now)
        if purged:
            logger.info("kalshi %s: purged %d live rows", sport_key, purged)

        matcher = self._matcher()
        total_rows = 0

        # Phase 1: only series_main (the h2h game-winner series). Phase 2
        # will iterate the other series_* slots and dispatch in the
        # normalizer.
        all_series = list(sport_cfg.series_main)
        for series_ticker in all_series:
            markets = await self._safe_list_markets(series_ticker, sport_key)
            if markets is None:
                continue
            rows = normalize_markets(
                markets,
                series_ticker=series_ticker,
                fetched_at=now,
                match_event=matcher.match,
            )
            if rows:
                self.cache.upsert(rows)
                total_rows += len(rows)

        self._last_cycle_at = now
        self._last_cycle_rows[sport_key] = total_rows

    async def _safe_list_markets(
        self, series_ticker: str, sport_key: str,
    ) -> list[dict] | None:
        try:
            return await self.client.list_markets(series_ticker)
        except KalshiAPIError as e:
            logger.warning(
                "kalshi %s %s: %s",
                sport_key, series_ticker, e,
            )
            return None

    async def refresh_now(self, sport_keys: list[str] | None = None) -> dict:
        """Trigger an immediate cycle for the given sports (or all configured
        sports if None). Sports run in parallel. Mirror of
        Coral33Fetcher.refresh_now for UI-button parity."""
        cfg = self._load_config()
        targets = sport_keys or list(cfg.sports.keys())
        t0 = datetime.now(timezone.utc)
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
