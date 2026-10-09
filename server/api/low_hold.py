from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Response
from pydantic import BaseModel

from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.low_hold import scan_all_low_hold
from ..odds.normalize import rows_to_games
from ..odds.scanner_runtime import run_scanner
from ..odds.wager_filter import legs_pass_wager_filter, normalize_wager_filter
from ..odds.latest_snapshot import LatestOddsSnapshotService
from ..util import TTLCache
from .serialization import json_bytes_response, model_json_bytes


class LowHoldSide(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None
    # Coral33-only betslip-eligibility tag; None for every other book.
    wager_type: str | None = None
    # Venue pairing: on a Novig take leg this is the maker price you could
    # post instead; on a `novig_maker` leg it's the take price. None else.
    counterpart_price_american: int | None = None


class LowHoldOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: str
    point: float | None = None
    hold_pct: float
    sides: list[LowHoldSide]


class LowHoldResponse(BaseModel):
    opportunities: list[LowHoldOpportunity]
    scanned_at: datetime
    max_hold_pct: float


def build_router(
    cache: OddsCache,
    snapshot_service: LatestOddsSnapshotService | None = None,
) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/low-hold", response_model=LowHoldResponse)
    async def get_low_hold(
        books: str = "",
        max_hold_pct: float = 1.0,
        wager_filter: str = "any",
    ) -> Response:
        # `cache.version` folds in the OddsCache's monotonic state version
        # so this memo can survive past its 20s TTL during quiet stretches.
        # `memoized_coalesced` additionally collapses simultaneous duplicate
        # requests into one underlying scan. See server/api/ev.py + the
        # docstring on server/odds/coalesce.py for the full rationale.
        # `wager_filter` ("any"|"straight"|"parlay") — Coral33 betslip filter,
        # see server/odds/wager_filter.py.
        wf = normalize_wager_filter(wager_filter)
        snapshot = await snapshot_service.get() if snapshot_service else None
        source_version = (
            ("snapshot", snapshot.generation)
            if snapshot is not None else cache.read_version
        )
        cache_key = (
            "low_hold", str(cache.path), source_version, books, max_hold_pct, wf,
        )

        async def _compute() -> bytes:
            def compute() -> bytes:
                books_set: set[str] | None = None
                if books.strip():
                    books_set = {b for b in books.split(",") if b}

                now = datetime.now(timezone.utc)
                if snapshot is not None:
                    games = snapshot.games
                else:
                    rows = cache.all_current()
                    games = rows_to_games(rows, now=now)
                ops = scan_all_low_hold(
                    games, books_filter=books_set, max_hold_pct=max_hold_pct,
                )
                if wf != "any":
                    ops = [
                        o for o in ops
                        if legs_pass_wager_filter(o["sides"], wf)
                    ]

                return model_json_bytes(LowHoldResponse(
                    opportunities=[
                        LowHoldOpportunity.model_validate(o) for o in ops
                    ],
                    scanned_at=now,
                    max_hold_pct=max_hold_pct,
                ))

            return await run_scanner("low-hold", compute)

        return json_bytes_response(
            await memoized_coalesced(memo, cache_key, _compute)
        )

    return router
