from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ..odds.arbitrage import arb_key_set
from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.ev import SHARP_BOOKS, scan_all_ev
from ..odds.liquidity import resolve_min_liquidity
from ..odds.normalize import rows_to_games
from ..odds.scanner_runtime import run_scanner
from ..odds.latest_snapshot import LatestOddsSnapshotService, snapshot_memo
from ..util import TTLCache
from ..user_settings import UserSettingsStore
from .serialization import json_bytes_response, model_json_bytes


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
    anchor_age_s: int | None = None
    reference_delayed: bool = False
    offered_age_s: int
    also_in_arb: bool
    confidence: Literal["normal", "low"]
    # Coral33-only parlay-eligibility tag. NULL for every other book.
    #   "straight" — line is on coral33's Straight tab only
    #   "parlay"   — line is on coral33's Parlay tab only
    #   "both"     — line is on both tabs (the common case)
    wager_type: Literal["straight", "parlay", "both"] | None = None
    # Venue pairing: on a Novig take leg this is the maker price you could
    # post instead; on a `novig_maker` leg it's the take price. None else.
    counterpart_price_american: int | None = None
    # Top-of-book depth ($) at the offered price — exchanges only.
    max_stake_dollars: float | None = None


class EVResponse(BaseModel):
    opportunities: list[EVOpportunity]
    scanned_at: datetime
    min_ev_pct: float
    sharp_anchor_books: list[str]


def build_router(
    cache: OddsCache,
    snapshot_service: LatestOddsSnapshotService | None = None,
    settings_store: UserSettingsStore | None = None,
) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/ev", response_model=EVResponse)
    async def get_ev(
        books: str = "",
        sharp_books: str = "",
        min_ev: float = 1.0,
        max_longshot_odds: int = 800,
        stale_seconds: int = 300,
        max_results: int = 300,
        tag_arb: bool = True,
        sort: str = "desc",
        wager_filter: str = "any",
        min_liquidity: float | None = None,
    ) -> Response:
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
          - wager_filter: "any" (default) | "straight" | "parlay".
              "straight" → keep rows whose offered line is straight-bettable
                (coral33 wager_type ∈ {straight, both} OR row is non-coral33,
                since every Odds-API book is inherently straight-eligible).
              "parlay"   → keep ONLY coral33 rows whose offered line is
                parlay-eligible (wager_type ∈ {parlay, both}).
              "any"      → no filter.
          - min_liquidity: drop rows whose offered price has less top-of-book
              depth ($). Omitted = saved Settings value; 0 = off.

        Memoized for 20s — the Edges page fires arb + lh + ev + fb in the
        same SWR tick, so the second-third-fourth EV scan within a 20s
        window comes back from this cache instead of re-running the full
        devig pass over 1000+ rows.
        """
        # `cache.version` folds in the OddsCache's monotonic state version.
        # When no upserts/purges have happened since the last call, the
        # version is unchanged → same key → the memo hits even after its
        # 20s TTL expires, which is the common case during quiet stretches
        # (no Odds API poll cycles, no WS ticks, no coral pulls). Any
        # upsert anywhere bumps the version and the next request gets a
        # clean miss + fresh scan. Scanners read the full universe (no
        # sport filter), so a global counter is exactly the right
        # granularity.
        min_liq = resolve_min_liquidity(min_liquidity, settings_store)
        snapshot = await snapshot_service.get() if snapshot_service else None
        source_version = (
            ("snapshot", snapshot.generation)
            if snapshot is not None else cache.read_version
        )
        cache_key = (
            "ev", str(cache.path), source_version, books, sharp_books, min_ev,
            max_longshot_odds, stale_seconds, max_results, tag_arb, sort,
            wager_filter, min_liq,
        )

        async def _compute() -> bytes:
            return await run_scanner("ev", _compute_sync)

        def _compute_sync() -> bytes:
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
            # "<Player> Over/Under/Yes/No" and the scanner pairs per-player
            # via market-aware bucket logic in ev._pair_bucket.
            if snapshot is not None:
                games = snapshot.games
            else:
                rows = cache.all_current()
                games = rows_to_games(rows, now=now)

            arb_keys: frozenset[tuple] | None = None
            if tag_arb:
                # The unfiltered arb scan depends only on the snapshot, not
                # on any EV query param — compute it once per snapshot
                # generation and share it across every EV variant.
                if snapshot is not None:
                    arb_keys = snapshot_memo(
                        snapshot, "ev_arb_keys", lambda: arb_key_set(games),
                    )
                else:
                    arb_keys = arb_key_set(games)

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
                sort=sort if sort in ("desc", "asc", "bidir") else "desc",
                min_liquidity_dollars=min_liq,
            )

            wf = wager_filter if wager_filter in ("any", "straight", "parlay") else "any"
            if wf == "straight":
                # Keep non-coral33 rows (always straight-bettable) and coral33
                # rows tagged straight or both. Drops parlay-only.
                opps = [
                    o for o in opps
                    if o.get("book") != "coral33"
                    or o.get("wager_type") in ("straight", "both")
                ]
            elif wf == "parlay":
                # Coral33 rows with parlay tab presence only. Other books
                # can't be parlayed with coral33 anyway, so they're dropped.
                opps = [
                    o for o in opps
                    if o.get("book") == "coral33"
                    and o.get("wager_type") in ("parlay", "both")
                ]

            return model_json_bytes(EVResponse(
                opportunities=[EVOpportunity.model_validate(o) for o in opps],
                scanned_at=now,
                min_ev_pct=min_ev,
                sharp_anchor_books=sorted(sharp_set),
            ))

        return json_bytes_response(
            await memoized_coalesced(memo, cache_key, _compute)
        )

    return router
