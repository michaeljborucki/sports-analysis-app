from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.low_hold import scan_all_low_hold
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..util import TTLCache


class LowHoldSide(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None


class LowHoldOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: Literal["h2h", "spreads", "totals"]
    point: float | None = None
    hold_pct: float
    sides: list[LowHoldSide]


class LowHoldResponse(BaseModel):
    opportunities: list[LowHoldOpportunity]
    scanned_at: datetime
    max_hold_pct: float


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/low-hold", response_model=LowHoldResponse)
    async def get_low_hold(
        books: str = "",
        max_hold_pct: float = 1.0,
    ) -> LowHoldResponse:
        # `cache.version` folds in the OddsCache's monotonic state version
        # so this memo can survive past its 20s TTL during quiet stretches.
        # `memoized_coalesced` additionally collapses simultaneous duplicate
        # requests into one underlying scan. See server/api/ev.py + the
        # docstring on server/odds/coalesce.py for the full rationale.
        cache_key = ("low_hold", str(cache.path), cache.version, books, max_hold_pct)

        async def _compute() -> LowHoldResponse:
            books_set: set[str] | None = None
            if books.strip():
                books_set = {b for b in books.split(",") if b}

            now = datetime.now(timezone.utc)
            rows = [
                r for r in cache.all_current() if not is_prop_market(r["market_key"])
            ]
            games = rows_to_games(rows, now=now)
            ops = scan_all_low_hold(games, books_filter=books_set, max_hold_pct=max_hold_pct)

            return LowHoldResponse(
                opportunities=[LowHoldOpportunity.model_validate(o) for o in ops],
                scanned_at=now,
                max_hold_pct=max_hold_pct,
            )

        return await memoized_coalesced(memo, cache_key, _compute)

    return router
