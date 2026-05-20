from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.books.polymarket import PolymarketFetcher


class PolymarketRefreshResponse(BaseModel):
    status: str
    sports_refreshed: list[str]
    duration_s: float
    errors: list[str]
    last_cycle_rows: dict[str, int]


class PolymarketStatusResponse(BaseModel):
    """Status of the Polymarket direct-API fetcher.

    Mirrors KalshiStatusResponse shape so a single frontend component
    can poll both `/api/polymarket/status` and `/api/kalshi/status`.
    `jwt_authenticated` is always True for Polymarket (read endpoints
    are unauthenticated and require no key) — the field is preserved
    purely for response-shape parity with the auth-bearing books.
    """
    running: bool
    last_cycle_at: str | None = None
    last_cycle_rows: dict[str, int]
    jwt_authenticated: bool


def build_router(fetcher: PolymarketFetcher) -> APIRouter:
    router = APIRouter()

    @router.post("/api/polymarket/refresh", response_model=PolymarketRefreshResponse)
    async def refresh() -> PolymarketRefreshResponse:
        """Trigger one immediate polymarket cycle across every configured sport."""
        result = await fetcher.refresh_now()
        return PolymarketRefreshResponse(**result)

    @router.get("/api/polymarket/status", response_model=PolymarketStatusResponse)
    async def status() -> PolymarketStatusResponse:
        # Slice to the keys PolymarketStatusResponse declares — fetcher.status
        # also returns WS health fields, which we want available but exposed
        # via a separate untyped response in the future. Including them
        # here as extra fields would require model_config(extra="allow"); the
        # status method on Pydantic in this project rejects unknown keys.
        full = fetcher.status
        return PolymarketStatusResponse(
            running=bool(full.get("running")),
            last_cycle_at=full.get("last_cycle_at"),
            last_cycle_rows=full.get("last_cycle_rows") or {},
            jwt_authenticated=bool(full.get("jwt_authenticated", True)),
        )

    return router
