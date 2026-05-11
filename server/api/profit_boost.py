"""Profit-boost API endpoint.

Two-leg conversion scanner: applies a configurable boost to one side of a
two-way market and hedges the opposite side at a different book, surfacing
pairs that lock in guaranteed profit. Mirrors the `/api/free-bets` shape
since the math kernel is similar (same equal-profit-hedge derivation), just
with the boost applied to a cash bet rather than treating one side as a
free bet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.cache import OddsCache
from ..odds.normalize import rows_to_games
from ..odds.profit_boost import scan_all_profit_boost
from ..util import TTLCache


class ProfitBoostLeg(BaseModel):
    outcome_name: str
    book: str
    point: float | None = None


class ProfitBoostBoostLeg(ProfitBoostLeg):
    """Boosted leg carries both the original and post-boost prices so the
    UI can show the price improvement (e.g., "+200 → +260")."""
    original_price_american: int
    boosted_price_american: int


class ProfitBoostHedgeLeg(ProfitBoostLeg):
    price_american: int


class ProfitBoostOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: str
    point: float | None = None
    # Guaranteed profit as % of total stake (boost stake + hedge stake).
    conversion_pct: float
    # Implied-prob hold of the boosted pair. Negative = profitable.
    hold_pct: float
    boost_pct: float
    # How much to put on the hedge leg per $100 placed on the boosted leg.
    hedge_stake_per_100_boost: float
    boost_leg: ProfitBoostBoostLeg
    hedge_leg: ProfitBoostHedgeLeg


class ProfitBoostResponse(BaseModel):
    opportunities: list[ProfitBoostOpportunity]
    scanned_at: datetime
    boost_pct: float
    min_conversion_pct: float


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/profit_boost", response_model=ProfitBoostResponse)
    async def get_profit_boost(
        boost_pct: float = 30.0,
        books: str = "",
        boost_books: str = "",
        min_conversion: float = 0.0,
        min_boost_odds: int = -10_000,
    ) -> ProfitBoostResponse:
        """Scan for profit-boost conversion opportunities.

        Query params:
          - boost_pct: percentage boost applied to winnings (default 30).
            Range [0, 100]. 0 = no boost, conversion will rarely clear.
          - books: csv of books usable for either leg (empty = all visible).
          - boost_books: csv of books the user holds a boost token at — the
            boosted leg will ALWAYS land at one of these. Empty = same set
            as `books`.
          - min_conversion: floor on guaranteed conversion %. Default 0
            surfaces every break-even-or-better pair. Set higher to
            filter to clearly-profitable pairs only.
          - min_boost_odds: floor on the BOOSTED leg's ORIGINAL American
            price. Default -10000 = unlimited. Raise to +100 to scope to
            plus-odds lines only (typical "longshot boost" promo behavior).
        """
        boost_pct = max(0.0, min(100.0, float(boost_pct)))
        cache_key = (
            "pb", str(cache.path), boost_pct, books, boost_books,
            min_conversion, min_boost_odds,
        )
        hit = memo.get(cache_key)
        if hit is not None:
            return hit

        hedge_books_set: set[str] | None = None
        if books.strip():
            hedge_books_set = {b for b in books.split(",") if b}
        boost_books_set: set[str] | None = None
        if boost_books.strip():
            boost_books_set = {b for b in boost_books.split(",") if b}

        now = datetime.now(timezone.utc)
        rows = cache.all_current()
        games = rows_to_games(rows, now=now)

        opps = scan_all_profit_boost(
            games,
            hedge_books_filter=hedge_books_set,
            boost_books_filter=boost_books_set,
            boost_pct=boost_pct,
            min_boost_odds=min_boost_odds,
            min_conversion_pct=min_conversion,
        )

        response = ProfitBoostResponse(
            opportunities=[
                ProfitBoostOpportunity.model_validate(o) for o in opps
            ],
            scanned_at=now,
            boost_pct=boost_pct,
            min_conversion_pct=min_conversion,
        )
        memo.set(cache_key, response)
        return response

    return router
