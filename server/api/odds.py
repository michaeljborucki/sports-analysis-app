from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ..models import OddsResponse, Game
from ..odds.cache import OddsCache
from ..odds.normalize import rows_to_games


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/odds/mlb", response_model=OddsResponse)
    async def get_mlb_odds() -> OddsResponse:
        now = datetime.now(timezone.utc)
        rows = cache.all_current()
        game_dicts = rows_to_games(rows, now=now)
        games = [Game.model_validate(g) for g in game_dicts]
        stale = max((g.stale_seconds for g in games), default=0)
        return OddsResponse(games=games, stale_seconds=stale, fetched_at=now)

    return router
