from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from ..models import FetcherStatus
from ..odds.cache import OddsCache
from ..odds.fetcher import FetcherRegistry


def build_router(cache: OddsCache, fetcher: FetcherRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health", response_model=FetcherStatus)
    async def health() -> FetcherStatus:
        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        if isinstance(last_fetch, str):
            last_fetch = datetime.fromisoformat(last_fetch)
        enabled = [
            f"{sp.key}:{t.name}" for sp, t in fetcher.all_enabled_tiers()
        ]
        return FetcherStatus(
            last_fetch_at=last_fetch,
            requests_used=status.get("requests_used"),
            requests_remaining=status.get("requests_remaining"),
            last_error=status.get("last_error"),
            fetcher_running=fetcher.is_running,
            enabled_tiers=enabled,
        )

    return router
