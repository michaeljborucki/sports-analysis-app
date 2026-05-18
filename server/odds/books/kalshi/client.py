from __future__ import annotations

import logging
from typing import Any, AsyncIterator

import httpx


logger = logging.getLogger(__name__)


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
TIMEOUT = 15.0


class KalshiAPIError(Exception):
    pass


class KalshiClient:
    """Async HTTP wrapper for Kalshi's public REST API.

    No auth required for read-only endpoints (catalog + market quotes).
    We poll /markets with `series_ticker=` filters at 15s cadence per sport.

    Kalshi paginates with an opaque `cursor` field — keep fetching until the
    response returns an empty cursor (or no markets).
    """

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        # Lazy client — opened on first request, closed on aclose().
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=TIMEOUT,
                headers={
                    "accept": "application/json",
                    "user-agent": "betting-site/1.0 (+kalshi-direct)",
                },
                # HTTP/2 keeps the connection pool warm between cycles —
                # important since we re-fetch every 15s.
                http2=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def list_markets(
        self,
        series_ticker: str,
        status: str = "open",
        limit: int = 1000,
    ) -> list[dict]:
        """Return ALL active markets for a series (auto-paginates).

        Kalshi's status filter values:
          - "open"   → markets accepting orders (what we want for live quotes).
          - "active" → catalog-level (series-event-market lifecycle); NOT a
                       valid filter param on /markets despite the doc shape.
                       Probed 2026-05-12: passing status=active 400s.
        Filter on `status == 'active'` later in the normalizer's quality
        check — that's the per-market status field, not the query param.
        """
        out: list[dict] = []
        cursor: str | None = None
        client = await self._get_client()
        # Safety cap — series under 50k markets, page 1000 each, max 100 pages.
        for _ in range(100):
            params: dict[str, Any] = {
                "series_ticker": series_ticker,
                "status": status,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            try:
                resp = await client.get("/markets", params=params)
            except httpx.HTTPError as e:
                raise KalshiAPIError(
                    f"kalshi list_markets {series_ticker}: transport: {e}"
                ) from e
            if resp.status_code != 200:
                raise KalshiAPIError(
                    f"kalshi list_markets {series_ticker}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
            try:
                data = resp.json()
            except Exception as e:
                raise KalshiAPIError(
                    f"kalshi list_markets {series_ticker}: non-JSON: "
                    f"{resp.text[:200]}"
                ) from e
            markets = data.get("markets") or []
            out.extend(markets)
            cursor = data.get("cursor") or None
            if not cursor or not markets:
                break
        return out

    async def iter_markets(
        self,
        series_ticker: str,
        status: str = "open",
        limit: int = 1000,
    ) -> AsyncIterator[dict]:
        """Streaming variant. Caller iterates one market at a time without
        materializing the full list. Useful if we ever scale to massive
        series; for current volume (under 100 markets/series) `list_markets`
        is simpler."""
        for m in await self.list_markets(series_ticker, status=status, limit=limit):
            yield m
