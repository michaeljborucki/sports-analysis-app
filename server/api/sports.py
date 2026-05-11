from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..sports import all_sports
from ..user_settings import UserSettingsStore


class MarketGroupModel(BaseModel):
    label: str
    main_key: str
    alt_key: str | None = None
    display: Literal["moneyline", "spread", "total", "yes_no"] = "moneyline"


class SportModel(BaseModel):
    key: str
    label: str
    market_groups: list[MarketGroupModel]


class SportsResponse(BaseModel):
    sports: list[SportModel]


def build_router(settings_store: UserSettingsStore | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/api/sports", response_model=SportsResponse)
    async def get_sports() -> SportsResponse:
        settings = settings_store.get() if settings_store else None
        sports = all_sports()
        if settings:
            sports = [s for s in sports if settings.is_sport_enabled(s.key)]
        return SportsResponse(
            sports=[
                SportModel(
                    key=sp.key,
                    label=sp.label,
                    market_groups=[
                        MarketGroupModel(
                            label=mg.label,
                            main_key=mg.main_key,
                            alt_key=mg.alt_key,
                            display=mg.display,
                        )
                        for mg in sp.market_groups
                    ],
                )
                for sp in sports
            ]
        )

    return router
