from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ..sports import all_sports


class MarketGroupModel(BaseModel):
    label: str
    main_key: str
    alt_key: str | None = None
    display: Literal["moneyline", "spread", "total"] = "moneyline"


class SportModel(BaseModel):
    key: str
    label: str
    market_groups: list[MarketGroupModel]


class SportsResponse(BaseModel):
    sports: list[SportModel]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/sports", response_model=SportsResponse)
    async def get_sports() -> SportsResponse:
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
                for sp in all_sports()
            ]
        )

    return router
