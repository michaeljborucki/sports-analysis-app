from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.cache import OddsCache
from ..odds.free_bet import scan_all_free_bets
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games


class FreeBetLeg(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None


class FreeBetOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: Literal["h2h", "spreads", "totals"]
    point: float | None = None
    conversion_pct: float
    hedge_stake_per_100: float
    free_leg: FreeBetLeg
    hedge_leg: FreeBetLeg


class FreeBetResponse(BaseModel):
    opportunities: list[FreeBetOpportunity]
    scanned_at: datetime
    min_free_odds: int


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/free-bets", response_model=FreeBetResponse)
    async def get_free_bets(
        books: str = "",
        min_free_odds: int = 100,
        max_results: int = 150,
    ) -> FreeBetResponse:
        books_set: set[str] | None = None
        if books.strip():
            books_set = {b for b in books.split(",") if b}

        now = datetime.now(timezone.utc)
        rows = [
            r for r in cache.all_current() if not is_prop_market(r["market_key"])
        ]
        games = rows_to_games(rows, now=now)
        ops = scan_all_free_bets(
            games, books_filter=books_set, min_free_odds=min_free_odds
        )
        ops = ops[:max_results]

        return FreeBetResponse(
            opportunities=[FreeBetOpportunity.model_validate(o) for o in ops],
            scanned_at=now,
            min_free_odds=min_free_odds,
        )

    return router
