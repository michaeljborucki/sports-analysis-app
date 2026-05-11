from __future__ import annotations

from fastapi import APIRouter

from ..models import FetcherControlResponse
from ..odds.cache_mode import CacheMode, CacheModeStore
from ..odds.fetcher import FetcherRegistry


def build_router(
    fetcher: FetcherRegistry,
    mode_store: CacheModeStore | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/fetcher/start", response_model=FetcherControlResponse)
    async def start() -> FetcherControlResponse:
        result = fetcher.start_all()
        return FetcherControlResponse(**result)

    @router.post("/api/fetcher/stop", response_model=FetcherControlResponse)
    async def stop() -> FetcherControlResponse:
        result = fetcher.stop_all()
        return FetcherControlResponse(**result)

    @router.post("/api/fetcher/refresh-now", response_model=FetcherControlResponse)
    async def refresh_now() -> FetcherControlResponse:
        """Ad-hoc: fire every enabled tier once right now, async. Returns
        immediately with the list of triggered tier names. Tasks run in the
        background on the event loop. Refused in snapshot mode — writing
        fresh rows to the snapshot file would corrupt the reproducible
        reference set."""
        if mode_store is not None and mode_store.get() == CacheMode.SNAPSHOT:
            return FetcherControlResponse(
                status="refused_snapshot_mode",
                tiers=[],
            )
        result = fetcher.refresh_all_now()
        return FetcherControlResponse(
            status=result["status"],
            tiers=result.get("triggered", []),
        )

    return router
