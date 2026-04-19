from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from ..models import OddsResponse, Game
from ..odds.cache import OddsCache
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games


# Window of games to display: not more than 6 hours past start (finished games),
# not more than 36 hours ahead (tomorrow's games at most).
PAST_WINDOW = timedelta(hours=6)
FUTURE_WINDOW = timedelta(hours=36)


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/odds/mlb", response_model=OddsResponse)
    async def get_mlb_odds() -> OddsResponse:
        now = datetime.now(timezone.utc)
        # Exclude player prop markets — they live on /api/props/mlb.
        rows = [r for r in cache.all_current() if not is_prop_market(r["market_key"])]
        game_dicts = rows_to_games(rows, now=now)

        # Filter out finished games (zombies from prior days) and far-future games
        def _in_window(g: dict) -> bool:
            ct = g["commence_time"]
            return (now - PAST_WINDOW) <= ct <= (now + FUTURE_WINDOW)

        game_dicts = [g for g in game_dicts if _in_window(g)]
        games = [Game.model_validate(g) for g in game_dicts]

        # Prefer fetcher's last successful tick for the response-level staleness —
        # matches /api/health and avoids poisoning from "zombie" book rows that
        # stop updating because the book pulled a line.
        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        if isinstance(last_fetch, str):
            last_fetch_dt = datetime.fromisoformat(last_fetch)
            if last_fetch_dt.tzinfo is None:
                last_fetch_dt = last_fetch_dt.replace(tzinfo=timezone.utc)
            stale = max(0, int((now - last_fetch_dt).total_seconds()))
        else:
            stale = max((g.stale_seconds for g in games), default=0)

        return OddsResponse(games=games, stale_seconds=stale, fetched_at=now)

    return router
