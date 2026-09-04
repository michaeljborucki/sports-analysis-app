from __future__ import annotations

from datetime import date as date_type, datetime, timedelta, timezone
import time
from typing import Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from ..odds.cache import OddsCache
from ..systems.context import Enricher, build_evaluation_games
from ..systems.context_cache import SystemContextCache
from ..systems.evaluator import deduplicate_wagers, evaluate_systems
from ..systems.models import SystemsResponse, SystemsSummary
from ..systems.store import SystemSignalStore
from ..odds.latest_snapshot import LatestOddsSnapshotService


def build_router(
    cache: OddsCache,
    *,
    signal_store: SystemSignalStore | None = None,
    context_enricher: Enricher | None = None,
    now_fn: Callable[[], datetime] | None = None,
    snapshot_service: LatestOddsSnapshotService | None = None,
) -> APIRouter:
    router = APIRouter()
    store = signal_store or SystemSignalStore(cache.path)
    persistent_context = SystemContextCache(cache.path)
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    response_cache: dict[tuple, tuple[float, SystemsResponse]] = {}

    @router.get("/api/systems", response_model=SystemsResponse)
    async def get_systems(
        date: date_type | None = Query(default=None),
        timeframe: Literal["today", "tomorrow", "upcoming"] | None = Query(default=None),
        timezone_name: str = Query(default="America/Denver", alias="timezone"),
    ) -> SystemsResponse:
        now = clock()
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(400, f"unknown timezone '{timezone_name}'") from exc
        local_today = now.astimezone(zone).date()
        if timeframe == "tomorrow":
            requested_date = local_today + timedelta(days=1)
        elif timeframe == "upcoming":
            requested_date = local_today + timedelta(days=2)
        else:
            requested_date = date or local_today
        response_timeframe = timeframe or ("date" if date is not None else "today")
        snapshot = await snapshot_service.get() if snapshot_service else None
        source_generation = (
            ("snapshot", snapshot.generation)
            if snapshot is not None else cache.version
        )
        memo_key = (
            requested_date.isoformat(), response_timeframe, timezone_name,
            source_generation, persistent_context.generation,
        )
        memoized = response_cache.get(memo_key)
        if memoized and time.monotonic() - memoized[0] < 30:
            return memoized[1]
        games, warnings = await build_evaluation_games(
            cache, requested_date, timezone_name, now,
            enrich=context_enricher,
            include_after=timeframe == "upcoming",
            source_rows=snapshot.system_rows if snapshot is not None else None,
        )
        result = evaluate_systems(
            games, evaluated_at=now, requested_date=requested_date,
        )
        wagers = deduplicate_wagers(result.signals)
        try:
            store.record(result.signals)
        except Exception as exc:
            warnings.append(f"Signal persistence unavailable: {exc}")
        counts = {status: 0 for status in (
            "qualified", "no_match", "no_slate", "unable_to_evaluate", "disabled"
        )}
        for evaluation in result.evaluations:
            counts[evaluation.status] += 1
        response = SystemsResponse(
            requested_date=requested_date,
            timeframe=response_timeframe,
            timezone=timezone_name,
            evaluated_at=now,
            evaluations=result.evaluations,
            signals=result.signals,
            wagers=wagers,
            summary=SystemsSummary(
                qualifying_systems=counts["qualified"],
                qualifying_wagers=len(wagers),
                no_match=counts["no_match"],
                no_slate=counts["no_slate"],
                unable_to_evaluate=counts["unable_to_evaluate"],
                disabled=counts["disabled"],
            ),
            context_warnings=warnings,
        )
        final_key = (
            requested_date.isoformat(), response_timeframe, timezone_name,
            source_generation, persistent_context.generation,
        )
        response_cache.clear()
        response_cache[final_key] = (time.monotonic(), response)
        return response

    return router
