"""Polymarket Gamma API HTTP client — public, no auth.

Three hosts in the Polymarket stack:
  - https://gamma-api.polymarket.com  — events + market metadata (we use this)
  - https://clob.polymarket.com       — orderbook + pricing (not needed in
                                          Phase 1: best bid/ask come back on
                                          the gamma /events response)
  - https://data-api.polymarket.com   — positions / leaderboards (not used)

Reads are completely public — no API key, no signing. We hammer `events`
on a 60s cycle pulling the full sports-tagged set; pagination via Gamma's
`limit` + `offset` parameters (the Gamma API doesn't cursor).
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx


logger = logging.getLogger(__name__)


BASE_URL = "https://gamma-api.polymarket.com"
TIMEOUT = 15.0

# Default page size for /events. Gamma caps individual responses near 500;
# we paginate via offset on top of that if needed.
DEFAULT_PAGE_LIMIT = 500
# Max pages per discovery cycle. 500 × 4 = 2000 events, well past the live
# sports universe (typically 200-400 active events worldwide at a time).
MAX_PAGES = 4


class PolymarketAPIError(Exception):
    pass


class PolymarketClient:
    """Async HTTP wrapper for Polymarket's Gamma API.

    Lazy `httpx.AsyncClient` — opened on first request, closed via aclose().
    No auth, no signing — just HTTP/1.1 with keep-alive.
    """

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=TIMEOUT,
                headers={
                    "accept": "application/json",
                    "user-agent": "betting-site/1.0 (+polymarket-direct)",
                },
                http2=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def list_sports_events(
        self,
        limit: int = DEFAULT_PAGE_LIMIT,
        tag_slug: str = "sports",
    ) -> list[dict]:
        """Return all active, non-closed events tagged `sports`.

        Sorted by `volume24hr` desc — early entries are the highest-liquidity
        games and we never miss them on small page sizes.

        Pagination: Gamma uses `limit` + `offset`. We paginate up to MAX_PAGES
        (capped to keep cycle time bounded — sports universe is small).

        Returns the raw list of event dicts; each event has a `markets`
        sub-array with the actual h2h / alt market objects we'll normalize.
        """
        out: list[dict] = []
        client = await self._get_client()
        for page in range(MAX_PAGES):
            params: dict[str, Any] = {
                "tag_slug": tag_slug,
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": page * limit,
                "order": "volume24hr",
                "ascending": "false",
            }
            # Mild 429-aware retry. Gamma is generous (no documented per-IP
            # cap) but a transient 429 shouldn't crash the whole cycle.
            _backoffs = (0.6, 1.5)
            resp = None
            for attempt in range(len(_backoffs) + 1):
                try:
                    resp = await client.get("/events", params=params)
                except httpx.HTTPError as e:
                    raise PolymarketAPIError(
                        f"polymarket list_sports_events: transport: {e}"
                    ) from e
                if resp.status_code != 429 or attempt == len(_backoffs):
                    break
                delay = _backoffs[attempt] + random.random() * 0.25
                logger.info(
                    "polymarket 429 page %d — retry %d/%d after %.2fs",
                    page, attempt + 1, len(_backoffs), delay,
                )
                await asyncio.sleep(delay)

            if resp.status_code != 200:
                raise PolymarketAPIError(
                    f"polymarket /events: {resp.status_code} {resp.text[:200]}"
                )
            try:
                data = resp.json()
            except Exception as e:
                raise PolymarketAPIError(
                    f"polymarket /events: non-JSON: {resp.text[:200]}"
                ) from e
            if not isinstance(data, list):
                raise PolymarketAPIError(
                    f"polymarket /events: expected list, got {type(data).__name__}"
                )
            out.extend(data)
            # Stop once a short page comes back — no more events.
            if len(data) < limit:
                break
        return out
