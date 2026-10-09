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


def build_router(fetcher: NovigFetcher, snapshot_service=None) -> APIRouter:
    router = APIRouter()

    @router.get("/api/novig/maker-candidates")
    async def maker_candidates() -> dict:
        """Read-only feed for the Novig auto-maker process: each Novig outcome
        we can post on, its fair probability, and live best bids."""
        from datetime import datetime, timezone
        from starlette.concurrency import run_in_threadpool
        snap = await snapshot_service.get() if snapshot_service else None
        if snap is None:
            return {"candidates": [], "snapshot_age_s": None, "stream_connected": False}
        now = datetime.now(timezone.utc)
        cands = await run_in_threadpool(fetcher.maker_candidates, snap.games, now)
        return {
            "generated_at": now.isoformat(),
            "snapshot_generation": snap.generation,
            "snapshot_age_s": snapshot_service.age_seconds,
            "stream_connected": bool(fetcher.status.get("ws_connected")),
            "candidates": cands,
        }

    @router.post("/api/novig/refresh", response_model=NovigRefreshResponse)
    async def refresh() -> NovigRefreshResponse:
        """Re-list Novig's catalog and rebuild the book-poll target set."""
        return NovigRefreshResponse(**(await fetcher.refresh_now()))

    @router.get("/api/novig/status")
    async def status() -> dict:
        """Fetcher health: targets, overdue count, books polled, 429s."""
        return fetcher.status

    return router
