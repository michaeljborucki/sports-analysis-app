from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from ..models import FetcherStatus, Game, Pick
from ..odds.arbitrage import scan_all_arbs
from ..odds.cache import OddsCache
from ..odds.fetcher import FetcherRegistry
from ..odds.market_config import is_prop_market
from ..odds.normalize import rows_to_games
from ..picks.reader import PicksReader
from ..sports import Sport
from .arbitrage import ArbOpportunity


class SportSummary(BaseModel):
    key: str
    label: str
    upcoming_games: int        # total games in the next 36h
    starting_in_3h: int        # starting within the props-window
    picks_today: int
    bet_card_date: str | None = None


class DashboardResponse(BaseModel):
    sports: list[SportSummary]
    top_arbs: list[ArbOpportunity]
    top_picks: list[Pick]          # highest-edge picks, cross-sport
    upcoming_games: list[Game]     # games starting in the next 3h, all sports
    fetcher: FetcherStatus
    scanned_at: datetime


FUTURE_WINDOW = timedelta(hours=36)
SOON_WINDOW = timedelta(hours=3)


def build_router(
    cache: OddsCache,
    fetcher: FetcherRegistry,
    picks_readers: dict[str, PicksReader],
    sports: list[Sport],
    picks_date_override: str = "",
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/dashboard", response_model=DashboardResponse)
    async def dashboard() -> DashboardResponse:
        now = datetime.now(timezone.utc)
        target_date = (
            date.fromisoformat(picks_date_override)
            if picks_date_override
            else date.today()
        )

        summaries: list[SportSummary] = []
        upcoming_all: list[dict] = []
        picks_all: list[dict] = []

        for sport in sports:
            sport_rows = [
                r for r in cache.all_current(sport_key=sport.key)
                if not is_prop_market(r["market_key"])
            ]
            sport_games = rows_to_games(sport_rows, now=now)
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

            reader = picks_readers.get(sport.key)
            picks_result = (
                reader.get_picks_for_date(target_date)
                if reader
                else {"picks": [], "bet_card_date": None}
            )
            for p in picks_result["picks"]:
                # Stamp sport_key so the dashboard can label cross-sport picks
                picks_all.append({**p, "sport_key": sport.key})

            summaries.append(
                SportSummary(
                    key=sport.key,
                    label=sport.label,
                    upcoming_games=len(upcoming),
                    starting_in_3h=len(starting_soon),
                    picks_today=len(picks_result["picks"]),
                    bet_card_date=picks_result.get("bet_card_date"),
                )
            )

        # Top 5 arbitrage opportunities across all sports, no book filter
        # (dashboard gives the full-market view; the dedicated /arbitrage
        # page applies the user's filter).
        arb_rows = [
            r for r in cache.all_current() if not is_prop_market(r["market_key"])
        ]
        arb_games = rows_to_games(arb_rows, now=now)
        all_arbs = scan_all_arbs(arb_games, books_filter=None)
        top_arbs = all_arbs[:5]

        # Top 10 picks by edge percentage
        picks_all.sort(key=lambda p: -p["edge_pct"])
        top_picks = picks_all[:10]

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
            top_picks=[Pick.model_validate(p) for p in top_picks],
            upcoming_games=[Game.model_validate(g) for g in upcoming_all[:12]],
            fetcher=fetcher_status,
            scanned_at=now,
        )

    return router
