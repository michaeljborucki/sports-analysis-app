from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from ..models import Pick, PicksResponse
from ..picks.reader import PicksReader
from ..sports import SPORTS


def build_router(
    readers: dict[str, PicksReader],
    date_override: str = "",
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/picks/{sport}", response_model=PicksResponse)
    async def get_picks(sport: str) -> PicksResponse:
        if sport not in SPORTS:
            raise HTTPException(404, f"unknown sport '{sport}'")
        reader = readers.get(sport)
        if reader is None:
            raise HTTPException(404, f"no picks reader for sport '{sport}'")
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
