from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.arbitrage import scan_all_arbs
from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.normalize import rows_to_games
from ..odds.scanner_runtime import run_scanner
from ..odds.wager_filter import legs_pass_wager_filter, normalize_wager_filter
from ..odds.latest_snapshot import LatestOddsSnapshotService
from ..util import TTLCache


class ArbSide(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None
    stake_pct: float
    max_stake_dollars: float | None = None
    # Coral33-only betslip-eligibility tag; None for every other book.
    wager_type: str | None = None
    # Venue pairing: on a Novig take leg this is the maker price you could
    # post instead; on a `novig_maker` leg it's the take price. None else.
    counterpart_price_american: int | None = None


class ArbOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: str
    point: float | None = None
    roi_pct: float
    sides: list[ArbSide]
    max_total_stake_dollars: float | None = None


class ArbResponse(BaseModel):
    opportunities: list[ArbOpportunity]
    scanned_at: datetime
    book_count: int


def build_router(
    cache: OddsCache,
    snapshot_service: LatestOddsSnapshotService | None = None,
) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/arbitrage", response_model=ArbResponse)
    async def get_arbs(books: str = "", wager_filter: str = "any") -> ArbResponse:
        """Scan the cache for complete two- and three-way arbitrage opportunities.

        `books` is an optional comma-separated allowlist — only prices from
        these bookmaker keys are considered. Empty = all books in the cache.

        `wager_filter` ("any" | "straight" | "parlay") filters by Coral33
        betslip eligibility — see server/odds/wager_filter.py. For these
        cross-book pairs it keys off the opportunity's coral33 leg (if any):
        "straight" drops pairs whose coral33 leg is parlay-only; "parlay"
        keeps only pairs with a parlay-eligible coral33 leg.

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
        wf = normalize_wager_filter(wager_filter)
        snapshot = await snapshot_service.get() if snapshot_service else None
        source_version = (
            ("snapshot", snapshot.generation)
            if snapshot is not None else cache.read_version
        )
        cache_key = ("arb", str(cache.path), source_version, books, wf)

        async def _compute() -> ArbResponse:
            def compute() -> ArbResponse:
                books_set: set[str] | None = None
                if books.strip():
                    books_set = {b for b in books.split(",") if b}

                now = datetime.now(timezone.utc)
                if snapshot is not None:
                    game_dicts = snapshot.games
                else:
                    rows = cache.all_current()
                    game_dicts = rows_to_games(rows, now=now)
                opps = scan_all_arbs(game_dicts, books_filter=books_set)
                if wf != "any":
                    opps = [
                        o for o in opps
                        if legs_pass_wager_filter(o["sides"], wf)
                    ]

                return ArbResponse(
                    opportunities=[
                        ArbOpportunity.model_validate(o) for o in opps
                    ],
                    scanned_at=now,
                    book_count=len(books_set) if books_set is not None else -1,
                )

            return await run_scanner("arbitrage", compute)

        return await memoized_coalesced(memo, cache_key, _compute)

    return router
