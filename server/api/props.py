from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..models import Game, OddsResponse
from ..odds.cache import OddsCache
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..sports import SPORTS


PAST_WINDOW = timedelta(hours=6)
FUTURE_WINDOW = timedelta(hours=36)


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/props/{sport}", response_model=OddsResponse)
    async def get_props(sport: str) -> OddsResponse:
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        now = datetime.now(timezone.utc)
        rows = [
            r for r in cache.all_current(sport_key=sport)
            if is_prop_market(r["market_key"])
        ]
        game_dicts = rows_to_games(rows, now=now)

        def _in_window(g: dict) -> bool:
            ct = g["commence_time"]
            return (now - PAST_WINDOW) <= ct <= (now + FUTURE_WINDOW)

        game_dicts = [g for g in game_dicts if _in_window(g)]
        games = [Game.model_validate(g) for g in game_dicts]

        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        if isinstance(last_fetch, str):
            last_fetch_dt = datetime.fromisoformat(last_fetch)
            if last_fetch_dt.tzinfo is None:
                last_fetch_dt = last_fetch_dt.replace(tzinfo=timezone.utc)
            stale = max(0, int((now - last_fetch_dt).total_seconds()))
        else:
            stale = 0

        return OddsResponse(games=games, stale_seconds=stale, fetched_at=now)

    return router
