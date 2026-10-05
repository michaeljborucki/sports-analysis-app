from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from ..models import OddsResponse, Game
from ..odds.cache import OddsCache
from ..odds.normalize import rows_to_games
from ..odds.scanner_runtime import run_scanner
from ..odds.latest_snapshot import LatestOddsSnapshotService
from ..sports import SPORTS


PAST_WINDOW = timedelta(hours=6)
FUTURE_WINDOW = timedelta(hours=36)
SPORT_FUTURE_WINDOWS = {
    "ncaaf": timedelta(days=7),
}


def build_router(
    cache: OddsCache,
    snapshot_service: LatestOddsSnapshotService | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/odds/{sport}", response_model=OddsResponse)
    async def get_odds(sport: str) -> OddsResponse:
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        snapshot = await snapshot_service.get() if snapshot_service else None

        def compute() -> OddsResponse:
            now = datetime.now(timezone.utc)
            future_window = SPORT_FUTURE_WINDOWS.get(sport, FUTURE_WINDOW)
            if snapshot is not None:
                game_dicts = snapshot.non_prop_games_by_sport.get(sport, ())
            else:
                rows = cache.all_current_family(
                    sport,
                    prop_family=False,
                    commence_before=now + future_window,
                )
                game_dicts = rows_to_games(rows, now=now)

            def _in_window(g: dict) -> bool:
                ct = g["commence_time"]
                return (now - PAST_WINDOW) <= ct <= (now + future_window)

            game_dicts = [g for g in game_dicts if _in_window(g)]
            games = [Game.model_validate(g) for g in game_dicts]

            status = cache.get_status() or {}
            last_fetch = status.get("last_fetch_at")
            if isinstance(last_fetch, str):
                last_fetch_dt = datetime.fromisoformat(
                    last_fetch.replace("Z", "+00:00")
                )
                if last_fetch_dt.tzinfo is None:
                    last_fetch_dt = last_fetch_dt.replace(tzinfo=timezone.utc)
            else:
                last_fetch_dt = None

            # In betting-db mode the legacy fetcher_status row belongs to
            # betting-site's own poller and may be old even while the central
            # database is receiving current offers. Freshness must describe
            # the data actually rendered on this page.
            newest_offer = cache.newest_fetched_at()
            if newest_offer is not None and (
                last_fetch_dt is None or newest_offer > last_fetch_dt
            ):
                last_fetch_dt = newest_offer

            if last_fetch_dt is not None:
                stale = max(0, int((now - last_fetch_dt).total_seconds()))
            else:
                stale = max((g.stale_seconds for g in games), default=0)

            return OddsResponse(
                games=games, stale_seconds=stale, fetched_at=now,
            )

        return await run_scanner(f"odds:{sport}", compute)

    return router
