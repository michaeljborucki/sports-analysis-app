from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.arbitrage import scan_all_arbs
from ..odds.cache import OddsCache
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..util import TTLCache


class ArbSide(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None
    stake_pct: float


class ArbOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: Literal["h2h", "spreads", "totals"]
    point: float | None = None
    roi_pct: float
    sides: list[ArbSide]


class ArbResponse(BaseModel):
    opportunities: list[ArbOpportunity]
    scanned_at: datetime
    book_count: int


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/arbitrage", response_model=ArbResponse)
    async def get_arbs(books: str = "") -> ArbResponse:
        """Scan the cache for two-way arbitrage opportunities.

        `books` is an optional comma-separated allowlist — only prices from
        these bookmaker keys are considered. Empty = all books in the cache.

        Memoized for 20s so the Edges page's burst-of-four simultaneous
        SWR pulls collapses to one actual scan.
        """
        cache_key = ("arb", str(cache.path), books)
        hit = memo.get(cache_key)
        if hit is not None:
            return hit

        books_set: set[str] | None = None
        if books.strip():
            books_set = {b for b in books.split(",") if b}

        now = datetime.now(timezone.utc)
        # Skip prop markets at the scan stage — they're too noisy and a different
        # pairing model (pitcher Cole O/U 6.5 isn't an arb with pitcher Cole O/U 7).
        rows = [
            r for r in cache.all_current()
            if not is_prop_market(r["market_key"])
        ]
        game_dicts = rows_to_games(rows, now=now)
        opps = scan_all_arbs(game_dicts, books_filter=books_set)

        response = ArbResponse(
            opportunities=[ArbOpportunity.model_validate(o) for o in opps],
            scanned_at=now,
            book_count=len(books_set) if books_set is not None else -1,
        )
        memo.set(cache_key, response)
        return response

    return router
