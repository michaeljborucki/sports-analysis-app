from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from ..models import Pick, PicksResponse
from ..picks.reader import PicksReader


def build_router(reader: PicksReader, date_override: str = "") -> APIRouter:
    router = APIRouter()

    @router.get("/api/picks/mlb", response_model=PicksResponse)
    async def get_mlb_picks() -> PicksResponse:
        target = date.fromisoformat(date_override) if date_override else date.today()
        result = reader.get_picks_for_date(target)
        picks = [Pick.model_validate(p) for p in result["picks"]]
        return PicksResponse(
            picks=picks,
            status=result["status"],
            last_checked_at=result["last_checked_at"],
            bet_card_date=result["bet_card_date"],
        )

    return router
