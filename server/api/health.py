from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from ..models import FetcherStatus
from ..odds.cache import OddsCache


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health", response_model=FetcherStatus)
    async def health() -> FetcherStatus:
        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        if isinstance(last_fetch, str):
            last_fetch = datetime.fromisoformat(last_fetch)
        return FetcherStatus(
            last_fetch_at=last_fetch,
            requests_used=status.get("requests_used"),
            requests_remaining=status.get("requests_remaining"),
            last_error=status.get("last_error"),
        )

    return router
