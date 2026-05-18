from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.books.kalshi import KalshiFetcher


class KalshiRefreshResponse(BaseModel):
    status: str
    sports_refreshed: list[str]
    duration_s: float
    errors: list[str]
    last_cycle_rows: dict[str, int]


class KalshiStatusResponse(BaseModel):
    """Status of the Kalshi direct-API fetcher.

    Mirrors Coral33StatusResponse so a single frontend component can poll
    both /api/coral33/status and /api/kalshi/status. `jwt_authenticated`
    is always True for Kalshi (read endpoints are unauthenticated) — the
    field is preserved purely for response-shape parity.
    """
    running: bool
    last_cycle_at: str | None = None
    last_cycle_rows: dict[str, int]
    jwt_authenticated: bool


def build_router(fetcher: KalshiFetcher) -> APIRouter:
    router = APIRouter()

    @router.post("/api/kalshi/refresh", response_model=KalshiRefreshResponse)
    async def refresh() -> KalshiRefreshResponse:
        """Trigger one immediate kalshi cycle across every configured sport."""
        result = await fetcher.refresh_now()
        return KalshiRefreshResponse(**result)

    @router.get("/api/kalshi/status", response_model=KalshiStatusResponse)
    async def status() -> KalshiStatusResponse:
        return KalshiStatusResponse(**fetcher.status)

    return router
