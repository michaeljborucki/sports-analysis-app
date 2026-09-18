from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ..models import FetcherStatus
from ..odds.cache import OddsCache, _odds_source
from ..odds.fetcher import FetcherRegistry


def build_router(cache: OddsCache, fetcher: FetcherRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health", response_model=FetcherStatus)
    async def health() -> FetcherStatus:
        status = cache.get_status() or {}
        last_fetch = status.get("last_fetch_at")
        if isinstance(last_fetch, str):
            last_fetch = datetime.fromisoformat(last_fetch.replace("Z", "+00:00"))
        if last_fetch is not None and last_fetch.tzinfo is None:
            last_fetch = last_fetch.replace(tzinfo=timezone.utc)
        newest_offer = cache.newest_fetched_at()
        if _odds_source() == "betting_db":
            # The native Odds API fetcher doesn't run in this mode, so its
            # `fetcher_status` row is frozen at whenever the cutover happened.
            # Reporting it whenever the local offer table is momentarily empty
            # showed a weeks-old "last fetch" on a perfectly healthy box.
            # The newest direct-book row (or nothing) is the honest answer.
            last_fetch = newest_offer
        elif newest_offer is not None and (
            last_fetch is None or newest_offer > last_fetch
        ):
            last_fetch = newest_offer
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
