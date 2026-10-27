"""NBA possession-efficiency projection endpoint (see server/nba/efficiency.py)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..nba.service import NbaPredictionService
from ..odds.latest_snapshot import LatestOddsSnapshotService


def build_router(snapshot_service: LatestOddsSnapshotService | None = None) -> APIRouter:
    router = APIRouter()
    service = NbaPredictionService(snapshot_service)

    @router.get("/api/nba/predictions")
    async def get_nba_predictions(day: date | None = Query(None, alias="date")) -> dict:
        """Projected scores for one slate day (default: ESPN's current day).

        Per team: avg(pace × own offensive efficiency, pace × opponent
        defensive efficiency), from regular-season games before that day —
        last season's numbers until a team has 10 games this season.
        """
        try:
            return await service.get(day)
        except Exception as exc:  # ESPN outage — surface, don't 500 silently
            raise HTTPException(status_code=502, detail=f"ESPN data unavailable: {exc}")

    @router.get("/api/nba/sgp")
    async def get_nba_sgp(day: date | None = Query(None, alias="date")) -> dict:
        """Same-game-parlay screen for one slate day: usage ≥ 24%, opponent
        bottom-10 vs the position (fantasy points allowed), and the highest
        points / rebounds / assists alt rungs that hit ≥ 93% — with the
        empirical joint hit rate and its break-even price."""
        try:
            return await service.get_sgp(day)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"ESPN data unavailable: {exc}")

    return router
