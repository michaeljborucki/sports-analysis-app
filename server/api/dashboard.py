from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..models import FetcherStatus
from ..odds.arbitrage import scan_all_arbs
from ..odds.cache import OddsCache
from ..odds.coalesce import memoized_coalesced
from ..odds.fetcher import FetcherRegistry
from ..odds.latest_snapshot import LatestOddsSnapshotService, OddsSnapshot
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..sports import Sport
from ..util import TTLCache
from .arbitrage import ArbOpportunity
from .serialization import json_bytes_response, model_json_bytes


class SportSummary(BaseModel):
    key: str
    label: str
    upcoming_games: int        # total games in the next 36h
    starting_in_3h: int        # starting within the props-window


class UpcomingGame(BaseModel):
    """Slim game header for the dashboard's "Starting soon" card. The full
    `Game` (with its markets tree) made /api/dashboard ~366KB; the card only
    reads these fields."""
    event_id: str
    sport_key: str = "mlb"
    home_team: str
    away_team: str
    commence_time: datetime


class DashboardResponse(BaseModel):
    sports: list[SportSummary]
    top_arbs: list[ArbOpportunity]
    upcoming_games: list[UpcomingGame]  # games starting in the next 3h, all sports
    fetcher: FetcherStatus
    scanned_at: datetime


FUTURE_WINDOW = timedelta(hours=36)
SOON_WINDOW = timedelta(hours=3)


def build_router(
    cache: OddsCache,
    fetcher: FetcherRegistry,
    sports: list[Sport],
    snapshot_service: LatestOddsSnapshotService | None = None,
) -> APIRouter:
    router = APIRouter()
    memo = TTLCache(ttl_seconds=20.0)

    @router.get("/api/dashboard", response_model=DashboardResponse)
    async def dashboard(books: str = "") -> Response:
        """Cross-sport summary. The full-cache read + arb scan is CPU/SQLite
        heavy, so it runs in the threadpool (never on the event loop, which
        used to stall every other request for 30-60s), and the result is
        memoized + coalesced like the scanner endpoints: concurrent polls
        from several tabs or SSE-driven revalidations share one computation.
        Deliberately NOT routed through run_scanner — its single slot would
        queue the dashboard behind the page's own concurrent /api/ev scan.

        When the shared odds snapshot is available (always, in the running
        app) the dashboard reuses its pre-normalized non-prop games — the
        same data the Edges scanners read — instead of re-reading ~350k
        cache rows per request.
        """
        snapshot = await snapshot_service.get() if snapshot_service else None
        source_version = (
            ("snapshot", snapshot.generation)
            if snapshot is not None else cache.read_version
        )
        cache_key = ("dashboard", str(cache.path), source_version, books)

        async def _compute() -> bytes:
            return await run_in_threadpool(_build_json, books, snapshot)

        return json_bytes_response(
            await memoized_coalesced(memo, cache_key, _compute)
        )

    def _build_json(books: str, snapshot: OddsSnapshot | None) -> bytes:
        # Rendered in the threadpool and memoized as bytes, so memo hits
        # skip FastAPI's per-request re-validation + re-serialization.
        return model_json_bytes(_build(books, snapshot))

    def _build(books: str, snapshot: OddsSnapshot | None) -> DashboardResponse:
        books_set: set[str] | None = None
        if books.strip():
            books_set = {b for b in books.split(",") if b}
        now = datetime.now(timezone.utc)

        if snapshot is not None:
            arb_games = list(snapshot.non_prop_games)
            games_by_sport = snapshot.non_prop_games_by_sport
        else:
            # Fallback (tests / no snapshot service): one cache pass,
            # partitioned by sport in memory.
            all_non_prop_rows = [
                r for r in cache.all_current()
                if not is_prop_market(r["market_key"])
            ]
            arb_games = rows_to_games(all_non_prop_rows, now=now)
            by_sport: dict[str, list[dict]] = {}
            for g in arb_games:
                by_sport.setdefault(g["sport_key"], []).append(g)
            games_by_sport = by_sport

        summaries: list[SportSummary] = []
        upcoming_all: list[dict] = []

        for sport in sports:
            sport_games = games_by_sport.get(sport.key, ())
            upcoming = [
                g for g in sport_games
                if now - timedelta(hours=6) <= g["commence_time"] <= now + FUTURE_WINDOW
            ]
            starting_soon = [
                g for g in upcoming
                if now <= g["commence_time"] <= now + SOON_WINDOW
            ]
            for g in starting_soon:
                upcoming_all.append(g)

            summaries.append(
                SportSummary(
                    key=sport.key,
                    label=sport.label,
                    upcoming_games=len(upcoming),
                    starting_in_3h=len(starting_soon),
                )
            )

        # Top 5 arbitrage opportunities across all sports. When the caller
        # passes ?books=..., filter to those books to keep the dashboard
        # consistent with global book-visibility.
        all_arbs = scan_all_arbs(arb_games, books_filter=books_set)
        top_arbs = all_arbs[:5]

        # Upcoming games sorted by start time
        upcoming_all.sort(key=lambda g: g["commence_time"])

        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        if isinstance(last_fetch, str):
            last_fetch = datetime.fromisoformat(last_fetch)
        fetcher_status = FetcherStatus(
            last_fetch_at=last_fetch,
            requests_used=status.get("requests_used"),
            requests_remaining=status.get("requests_remaining"),
            last_error=status.get("last_error"),
            fetcher_running=fetcher.is_running,
            enabled_tiers=[
                f"{sp.key}:{t.name}" for sp, t in fetcher.all_enabled_tiers()
            ],
        )

        return DashboardResponse(
            sports=summaries,
            top_arbs=[ArbOpportunity.model_validate(o) for o in top_arbs],
            upcoming_games=[
                UpcomingGame.model_validate(g) for g in upcoming_all[:12]
            ],
            fetcher=fetcher_status,
            scanned_at=now,
        )

    return router
