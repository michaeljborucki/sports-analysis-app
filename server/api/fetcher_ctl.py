from __future__ import annotations

from fastapi import APIRouter

from ..models import FetcherControlResponse
from ..odds.fetcher import FetcherRegistry


def build_router(fetcher: FetcherRegistry) -> APIRouter:
    router = APIRouter()

    @router.post("/api/fetcher/start", response_model=FetcherControlResponse)
    async def start() -> FetcherControlResponse:
        result = fetcher.start_all()
        return FetcherControlResponse(**result)

    @router.post("/api/fetcher/stop", response_model=FetcherControlResponse)
    async def stop() -> FetcherControlResponse:
        result = fetcher.stop_all()
        return FetcherControlResponse(**result)

    return router
