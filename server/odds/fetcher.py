from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import Config
from .cache import OddsCache
from .client import OddsAPIClient, OddsAPIError
from .normalize import normalize_odds_response


logger = logging.getLogger(__name__)


class OddsFetcher:
    def __init__(self, config: Config, cache: OddsCache, client: OddsAPIClient):
        self.config = config
        self.cache = cache
        self.client = client
        self.scheduler = AsyncIOScheduler()
        self._backoff_seconds = 0

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            if self._backoff_seconds > 0:
                await asyncio.sleep(self._backoff_seconds)
            games, rate = await self.client.fetch_mlb_core()
            rows = normalize_odds_response(games, fetched_at=now)
            if rows:
                self.cache.upsert(rows)
            self.cache.set_status(
                last_fetch_at=now,
                requests_used=rate.get("requests_used"),
                requests_remaining=rate.get("requests_remaining"),
                last_error=None,
            )
            self._backoff_seconds = 0
        except OddsAPIError as e:
            logger.exception("Odds API error")
            self.cache.set_status(last_error=str(e))
            self._backoff_seconds = min(30, max(1, self._backoff_seconds * 2 or 1))
        except Exception as e:
            logger.exception("Fetcher unhandled error")
            self.cache.set_status(last_error=repr(e))

    def start(self) -> None:
        self.scheduler.add_job(
            self.tick,
            trigger="interval",
            seconds=self.config.odds_poll_interval,
            next_run_time=datetime.now(timezone.utc),
        )
        self.scheduler.start()

    def stop(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
