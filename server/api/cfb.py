"""College-football PPP projection endpoint (see server/cfb/ppp.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..cfb.service import CfbPredictionService
from ..odds.latest_snapshot import LatestOddsSnapshotService


def build_router(snapshot_service: LatestOddsSnapshotService | None = None) -> APIRouter:
    router = APIRouter()
    service = CfbPredictionService(snapshot_service)

    @router.get("/api/cfb/predictions")
    async def get_cfb_predictions(week: int | None = Query(None, ge=1, le=20)) -> dict:
        """Projected scores for one regular-season week (default: current).

        Per team: avg(plays × own off PPP, plays × opponent def PPP), with
        season-to-date stats from games completed before that week.
        """
        try:
            return await service.get(week)
        except Exception as exc:  # ESPN outage — surface, don't 500 silently
            raise HTTPException(status_code=502, detail=f"ESPN data unavailable: {exc}")

    return router
