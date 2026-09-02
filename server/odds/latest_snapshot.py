"""Application-scoped, normalized view of the latest odds."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any

from starlette.concurrency import run_in_threadpool

from .normalize import rows_to_games


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OddsSnapshot:
    generation: int
    built_at: datetime
    source_version: tuple
    rows: tuple[dict, ...]
    games: tuple[dict, ...]


class LatestOddsSnapshotService:
    """Build one odds view and coalesce concurrent readers onto it."""

    def __init__(
        self,
        cache: Any,
        *,
        refresh_interval_seconds: float = 15.0,
        hard_stale_seconds: float = 90.0,
    ) -> None:
        self._cache = cache
        self._refresh_interval_seconds = refresh_interval_seconds
        self._hard_stale_seconds = hard_stale_seconds
        self._current: OddsSnapshot | None = None
        self._build_task: asyncio.Task[OddsSnapshot] | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def current(self) -> OddsSnapshot | None:
        return self._current

    @property
    def refreshing(self) -> bool:
        return self._build_task is not None and not self._build_task.done()

    @property
    def running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def age_seconds(self) -> float | None:
        if self._current is None:
            return None
        return max(
            0.0,
            (datetime.now(timezone.utc) - self._current.built_at).total_seconds(),
        )

    @property
    def is_hard_stale(self) -> bool:
        age = self.age_seconds
        return age is None or age > self._hard_stale_seconds

    async def get(self) -> OddsSnapshot:
        source_version = self._cache.read_version
        if self._current is not None and self._current.source_version == source_version:
            return self._current
        if self._current is not None:
            await self._ensure_refresh(source_version)
            return self._current
        task = await self._ensure_refresh(source_version)
        return await asyncio.shield(task)

    async def _ensure_refresh(
        self, source_version: tuple,
    ) -> asyncio.Future[OddsSnapshot]:
        async with self._lock:
            if self._current is not None and self._current.source_version == source_version:
                completed = asyncio.get_running_loop().create_future()
                completed.set_result(self._current)
                return completed
            if self._build_task is None or self._build_task.done():
                self._build_task = asyncio.create_task(
                    self._build(source_version)
                )
            return self._build_task

    async def wait_until_idle(self) -> None:
        task = self._build_task
        if task is not None:
            await asyncio.shield(task)

    async def start(self) -> None:
        if self.running:
            return
        await self.get()
        self._loop_task = asyncio.create_task(self._refresh_loop())

    async def stop(self) -> None:
        task = self._loop_task
        self._loop_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval_seconds)
            if (
                self._current is None
                or self._current.source_version != self._cache.read_version
            ):
                await self._ensure_refresh(self._cache.read_version)

    async def _build(self, source_version: tuple) -> OddsSnapshot:
        started = time.perf_counter()
        try:
            rows, games, built_at = await run_in_threadpool(self._build_sync)
            generation = (
                1 if self._current is None else self._current.generation + 1
            )
            snapshot = OddsSnapshot(
                generation=generation,
                built_at=built_at,
                source_version=source_version,
                rows=rows,
                games=games,
            )
            self._current = snapshot
            self._last_error = None
            logger.info(
                "odds snapshot published generation=%d rows=%d games=%d "
                "build_ms=%.1f",
                generation,
                len(rows),
                len(games),
                (time.perf_counter() - started) * 1000,
            )
            return snapshot
        except Exception as exc:
            self._last_error = str(exc).strip() or type(exc).__name__
            logger.exception("odds snapshot refresh failed")
            if self._current is not None:
                return self._current
            raise

    def _build_sync(self) -> tuple[tuple[dict, ...], tuple[dict, ...], datetime]:
        built_at = datetime.now(timezone.utc)
        rows = tuple(self._cache.all_current())
        games = tuple(rows_to_games(rows, now=built_at))
        return rows, games, built_at
