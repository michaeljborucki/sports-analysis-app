from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..models import Game, OddsResponse
from ..odds.cache import OddsCache
from ..odds.normalize import rows_to_games
from ..odds.scanner_runtime import run_scanner
from ..sports import SPORTS


PAST_WINDOW = timedelta(hours=6)
FUTURE_WINDOW = timedelta(hours=36)


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/props/{sport}", response_model=OddsResponse)
    async def get_props(sport: str) -> OddsResponse:
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        def compute() -> OddsResponse:
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

            return OddsResponse(
                games=games, stale_seconds=stale, fetched_at=now,
            )

        return await run_scanner(f"props:{sport}", compute)

    return router
