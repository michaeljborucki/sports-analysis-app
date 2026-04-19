from __future__ import annotations

from fastapi import APIRouter

from ..models import FetcherControlResponse
from ..odds.fetcher import FetcherRegistry


def build_router(fetcher: FetcherRegistry) -> APIRouter:
    router = APIRouter()

    @router.post("/api/refresh/{event_id}", response_model=FetcherControlResponse)
    async def refresh(event_id: str) -> FetcherControlResponse:
        result = await fetcher.refresh_event(event_id)
        return FetcherControlResponse(**result)

    return router
