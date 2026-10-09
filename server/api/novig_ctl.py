from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..odds.books.novig import NovigFetcher


class NovigRefreshResponse(BaseModel):
    status: str
    sports_refreshed: list[str]
    duration_s: float
    errors: list[str]
    last_cycle_rows: dict[str, int]


def build_router(fetcher: NovigFetcher) -> APIRouter:
    router = APIRouter()

    @router.post("/api/novig/refresh", response_model=NovigRefreshResponse)
    async def refresh() -> NovigRefreshResponse:
        """Re-list Novig's catalog and rebuild the book-poll target set."""
        return NovigRefreshResponse(**(await fetcher.refresh_now()))

    @router.get("/api/novig/status")
    async def status() -> dict:
        """Fetcher health: targets, overdue count, books polled, 429s."""
        return fetcher.status

    return router
