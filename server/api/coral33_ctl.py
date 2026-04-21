from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.books.coral33 import Coral33Fetcher


class Coral33RefreshResponse(BaseModel):
    status: str
    sports_refreshed: list[str]
    duration_s: float
    errors: list[str]
    last_cycle_rows: dict[str, int]


class Coral33StatusResponse(BaseModel):
    running: bool
    last_cycle_at: str | None = None
    last_cycle_rows: dict[str, int]
    captcha_backoff_remaining_s: int
    jwt_authenticated: bool


def build_router(fetcher: Coral33Fetcher) -> APIRouter:
    router = APIRouter()

    @router.post("/api/coral33/refresh", response_model=Coral33RefreshResponse)
    async def refresh() -> Coral33RefreshResponse:
        """Trigger one immediate coral33 cycle (main → alt/prop) across every
        configured sport. Sports run in parallel; tiers within a sport run
        sequentially."""
        result = await fetcher.refresh_now()
        return Coral33RefreshResponse(**result)

    @router.get("/api/coral33/status", response_model=Coral33StatusResponse)
    async def status() -> Coral33StatusResponse:
        return Coral33StatusResponse(**fetcher.status)

    return router
