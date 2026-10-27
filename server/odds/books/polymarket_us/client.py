"""Polymarket US public market-data client (https://gateway.polymarket.us).

Read-only and unauthenticated: league event listings and full event payloads
(every market with each side's buy price). Rate limit is 25 req/s per IP,
shared with everything else on this machine — requests are paced well under it.

Deliberately has NO order / portfolio / account methods. The API key in .env
can trade; nothing here sends it (only ws_client signs, and only the
market-data WebSocket handshake).
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://gateway.polymarket.us"
TIMEOUT = 20.0
PAGE_LIMIT = 100
MAX_PAGES = 10
# Spacing between request starts, process-wide for this client: 8 req/s.
_MIN_INTERVAL_S = 0.125


class PolymarketUSAPIError(Exception):
    pass


class PolymarketUSClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self._client: httpx.AsyncClient | None = None
        self._pace_lock = asyncio.Lock()
        self._next_slot = 0.0
        self.requests = 0
        self.errors = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=TIMEOUT,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _pace(self) -> None:
        async with self._pace_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + _MIN_INTERVAL_S
        if wait > 0:
            await asyncio.sleep(wait)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        client = await self._get_client()
        for attempt in range(3):
            await self._pace()
            self.requests += 1
            try:
                resp = await client.get(path, params=params)
            except httpx.HTTPError as e:
                self.errors += 1
                if attempt == 2:
                    raise PolymarketUSAPIError(f"{path}: transport: {e}") from e
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                self.errors += 1
                if attempt == 2:
                    raise PolymarketUSAPIError(f"{path}: HTTP {resp.status_code}")
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            if resp.status_code != 200:
                self.errors += 1
                raise PolymarketUSAPIError(f"{path}: HTTP {resp.status_code}")
            return resp.json()
        raise PolymarketUSAPIError(f"{path}: retries exhausted")

    async def list_league_events(self, league_slug: str) -> list[dict]:
        """Upcoming game events for a league (summary rows: slug, startTime,
        live/ended flags; markets here are only the moneyline)."""
        out: list[dict] = []
        for page in range(MAX_PAGES):
            data = await self._get(
                f"/v2/leagues/{league_slug}/events",
                {"limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT},
            )
            events = data.get("events") or []
            out.extend(events)
            if len(events) < PAGE_LIMIT:
                break
        return out

    async def get_event(self, slug: str) -> dict | None:
        """Full event: every market with marketSides (each side's buy quote)."""
        data = await self._get(f"/v1/events/slug/{slug}")
        return data.get("event")
