from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.arbitrage import scan_all_arbs
from ..odds.cache import OddsCache
from ..odds.ev import SHARP_BOOKS, scan_all_ev
from ..odds.normalize import rows_to_games


class EVOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: str
    point: float | None = None
    outcome_name: str
    book: str
    offered_price_american: int
    fair_price_american: int
    fair_probability: float
    ev_pct: float
    kelly_full_pct: float
    kelly_quarter_pct: float
    source: Literal["pinnacle", "consensus"]
    anchor_book_count: int
    offered_age_s: int
    also_in_arb: bool
    confidence: Literal["normal", "low"]


class EVResponse(BaseModel):
    opportunities: list[EVOpportunity]
    scanned_at: datetime
    min_ev_pct: float
    sharp_anchor_books: list[str]


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/ev", response_model=EVResponse)
    async def get_ev(
        books: str = "",
        sharp_books: str = "",
        min_ev: float = 1.0,
        max_longshot_odds: int = 800,
        stale_seconds: int = 300,
        max_results: int = 300,
        tag_arb: bool = True,
    ) -> EVResponse:
        """Scan the cache for +EV opportunities.

        Query params:
          - books: csv of offered-side bookmaker keys (empty = all)
          - sharp_books: csv of sharp anchor books (empty = SHARP_BOOKS default)
          - min_ev: minimum EV percentage (ROI per $1) to include, default 1.0
          - max_longshot_odds: filter out offered prices above this American
            value; default +800 to avoid devig noise on longshots
          - stale_seconds: drop offered prices older than this; default 60
          - max_results: server-side cap after sort; default 300
          - tag_arb: also_in_arb flag — set false to skip arb pre-scan
        """
        books_set: set[str] | None = None
        if books.strip():
            books_set = {b for b in books.split(",") if b}

        sharp_set = SHARP_BOOKS
        if sharp_books.strip():
            candidate = {b for b in sharp_books.split(",") if b}
            if candidate:
                sharp_set = frozenset(candidate)

        now = datetime.now(timezone.utc)
        # Player props are included: outcomes are encoded as
        # "<Player> Over/Under/Yes/No" and the scanner pairs per-player via
        # market-aware bucket logic in ev._pair_bucket.
        rows = cache.all_current()
        games = rows_to_games(rows, now=now)

        arb_keys: set[tuple] | None = None
        if tag_arb:
            arb_rows = scan_all_arbs(games)
            arb_keys = {
                (a["event_id"], a["market_kind"], a["point"])
                for a in arb_rows
            }

        opps = scan_all_ev(
            games,
            now=now,
            books_filter=books_set,
            sharp_books=sharp_set,
            min_ev_pct=min_ev,
            max_longshot_american=max_longshot_odds,
            stale_seconds=float(stale_seconds),
            arb_keys=arb_keys,
            max_results=max_results,
        )

        return EVResponse(
            opportunities=[EVOpportunity.model_validate(o) for o in opps],
            scanned_at=now,
            min_ev_pct=min_ev,
            sharp_anchor_books=sorted(sharp_set),
        )

    return router
