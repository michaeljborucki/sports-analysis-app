from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.books.polymarket_us.fetcher import PolymarketUSFetcher


class PolymarketUSRefreshResponse(BaseModel):
    status: str
    sports_refreshed: list[str]
    duration_s: float
    errors: list[str]
    last_cycle_rows: dict[str, int]


class PolymarketUSStatusResponse(BaseModel):
    """Polymarket US direct feed health. `jwt_authenticated` = the signed
    market-data WebSocket is connected and streaming. `unmapped_market_types`
    lists every Polymarket US market type skipped in the last full fetch per
    league (no matching app market key) — nothing is dropped silently."""
    running: bool
    last_cycle_at: str | None = None
    last_cycle_rows: dict[str, int]
    jwt_authenticated: bool
    ws_enabled: bool
    ws_disabled_reason: str | None = None
    events_tracked: int
    markets_registered: int
    unmatched_events: dict[str, int]
    unmapped_market_types: dict[str, dict[str, int]]


def build_router(fetcher: PolymarketUSFetcher) -> APIRouter:
    router = APIRouter()

    @router.post("/api/polymarket-us/refresh", response_model=PolymarketUSRefreshResponse)
    async def refresh() -> PolymarketUSRefreshResponse:
        """Force a full re-fetch of every configured league's upcoming games."""
        return PolymarketUSRefreshResponse(**(await fetcher.refresh_now()))

    @router.get("/api/polymarket-us/status", response_model=PolymarketUSStatusResponse)
    async def status() -> PolymarketUSStatusResponse:
        return PolymarketUSStatusResponse(**fetcher.status)

    return router
