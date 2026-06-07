from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..models import OddsResponse, Game
from ..odds.cache import OddsCache
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..odds.raw import rows_to_odds_api_events
from ..sports import SPORTS


PAST_WINDOW = timedelta(hours=6)
FUTURE_WINDOW = timedelta(hours=36)


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/odds/{sport}", response_model=OddsResponse)
    async def get_odds(sport: str) -> OddsResponse:
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        now = datetime.now(timezone.utc)
        rows = [
            r for r in cache.all_current(sport_key=sport)
            if not is_prop_market(r["market_key"])
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
            stale = max((g.stale_seconds for g in games), default=0)

        return OddsResponse(games=games, stale_seconds=stale, fetched_at=now)

    @router.get("/api/odds/{sport}/raw")
    async def get_odds_raw(sport: str) -> dict:
        """Live odds for one sport in The Odds API's native event JSON shape.

        Backs the sibling agent pipelines: instead of each agent spending its
        own Odds API credits on the same games the backend is already polling,
        it pulls this endpoint and reuses the shared cache. The payload mirrors
        a direct `/sports/<key>/odds` response (all markets, including props),
        so an agent runs it through the exact same parsers it uses for a direct
        API pull. `data` is the event list; `stale_seconds` is how long ago the
        fetcher last completed a cycle (None if it hasn't run yet).
        """
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        now = datetime.now(timezone.utc)
        rows = cache.all_current(sport_key=sport)
        events = rows_to_odds_api_events(rows)

        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        stale: int | None = None
        if isinstance(last_fetch, str):
            last_fetch_dt = datetime.fromisoformat(last_fetch)
            if last_fetch_dt.tzinfo is None:
                last_fetch_dt = last_fetch_dt.replace(tzinfo=timezone.utc)
            stale = max(0, int((now - last_fetch_dt).total_seconds()))

        return {
            "data": events,
            "fetched_at": now.isoformat(),
            "stale_seconds": stale,
        }

    return router
