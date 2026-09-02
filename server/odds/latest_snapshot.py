"""Application-scoped, normalized view of the latest odds."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from starlette.concurrency import run_in_threadpool

from .normalize import rows_to_games


@dataclass(frozen=True)
class OddsSnapshot:
    generation: int
    built_at: datetime
    source_version: tuple
    rows: tuple[dict, ...]
    games: tuple[dict, ...]


class LatestOddsSnapshotService:
    """Build one odds view and coalesce concurrent readers onto it."""

    def __init__(self, cache: Any) -> None:
        self._cache = cache
        self._current: OddsSnapshot | None = None
        self._build_task: asyncio.Task[OddsSnapshot] | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> OddsSnapshot:
        source_version = self._cache.read_version
        if self._current is not None and self._current.source_version == source_version:
            return self._current

        async with self._lock:
            if self._current is not None and self._current.source_version == source_version:
                return self._current
            if self._build_task is None or self._build_task.done():
                self._build_task = asyncio.create_task(
                    self._build(source_version)
                )
            task = self._build_task
        return await asyncio.shield(task)

    async def _build(self, source_version: tuple) -> OddsSnapshot:
        rows, games, built_at = await run_in_threadpool(self._build_sync)
        generation = 1 if self._current is None else self._current.generation + 1
        snapshot = OddsSnapshot(
            generation=generation,
            built_at=built_at,
            source_version=source_version,
            rows=rows,
            games=games,
        )
        self._current = snapshot
        return snapshot

    def _build_sync(self) -> tuple[tuple[dict, ...], tuple[dict, ...], datetime]:
        built_at = datetime.now(timezone.utc)
        rows = tuple(self._cache.all_current())
        games = tuple(rows_to_games(rows, now=built_at))
        return rows, games, built_at
