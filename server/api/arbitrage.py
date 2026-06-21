from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.arbitrage import scan_all_arbs
from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..util import TTLCache


class ArbSide(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None
    stake_pct: float
    max_stake_dollars: float | None = None


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
    max_total_stake_dollars: float | None = None


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
        # `cache.version` folds in the OddsCache's monotonic state version
        # so this memo can survive past its 20s TTL during quiet stretches.
        # See server/api/ev.py for the full rationale.
        # `memoized_coalesced` ALSO collapses simultaneous duplicate requests
        # into one underlying scan (e.g. the Edges page firing arb+lh+ev+fb
        # in the same SWR tick, or two tabs sharing a request burst). See
        # server/odds/coalesce.py for the in-flight registry semantics.
        cache_key = ("arb", str(cache.path), cache.version, books)

        async def _compute() -> ArbResponse:
            books_set: set[str] | None = None
            if books.strip():
                books_set = {b for b in books.split(",") if b}

            now = datetime.now(timezone.utc)
            # Skip prop markets at the scan stage — they're too noisy and a
            # different pairing model (pitcher Cole O/U 6.5 isn't an arb with
            # pitcher Cole O/U 7).
            rows = [
                r for r in cache.all_current()
                if not is_prop_market(r["market_key"])
            ]
            game_dicts = rows_to_games(rows, now=now)
            opps = scan_all_arbs(game_dicts, books_filter=books_set)

            return ArbResponse(
                opportunities=[ArbOpportunity.model_validate(o) for o in opps],
                scanned_at=now,
                book_count=len(books_set) if books_set is not None else -1,
            )

        return await memoized_coalesced(memo, cache_key, _compute)

    return router
