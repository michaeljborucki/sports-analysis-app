from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from ..models import Game, OddsResponse
from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.latest_snapshot import LatestOddsSnapshotService
from ..odds.normalize import rows_to_games
from ..odds.scanner_runtime import run_scanner
from ..sports import SPORTS
from ..util import TTLCache
from .serialization import json_bytes_response, model_json_bytes


PAST_WINDOW = timedelta(hours=6)
FUTURE_WINDOW = timedelta(hours=36)


def build_router(
    cache: OddsCache,
    snapshot_service: LatestOddsSnapshotService | None = None,
) -> APIRouter:
    router = APIRouter()
    # Rendered once per (sport, data version) — see server/api/odds.py.
    # Props read the cache directly (not the snapshot); the snapshot's
    # generation is used only as the "data refreshed" clock (~5s), so a
    # props response is at most one overlay behind the cache.
    memo = TTLCache(ttl_seconds=60.0)

    @router.get("/api/props/{sport}", response_model=OddsResponse)
    async def get_props(sport: str) -> Response:
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        snapshot = await snapshot_service.get() if snapshot_service else None
        source_version = (
            ("snapshot", snapshot.generation)
            if snapshot is not None else cache.read_version
        )
        cache_key = ("props", str(cache.path), sport, source_version)

        def compute() -> bytes:
            now = datetime.now(timezone.utc)
            rows = cache.all_current_family(
                sport,
                prop_family=True,
                commence_before=now + FUTURE_WINDOW,
            )
            game_dicts = rows_to_games(rows, now=now)

            def _in_window(g: dict) -> bool:
                ct = g["commence_time"]
                return (now - PAST_WINDOW) <= ct <= (now + FUTURE_WINDOW)

            game_dicts = [g for g in game_dicts if _in_window(g)]
            games = [Game.model_validate(g) for g in game_dicts]

            # Direct-book props refresh independently of the legacy Odds API
            # poller. Report the oldest displayed offer, as game ages do.
            stale = max((g.stale_seconds for g in games), default=0)

            return model_json_bytes(OddsResponse(
                games=games, stale_seconds=stale, fetched_at=now,
            ))

        async def _compute() -> bytes:
            return await run_scanner(f"props:{sport}", compute)

        return json_bytes_response(
            await memoized_coalesced(memo, cache_key, _compute)
        )

    return router
