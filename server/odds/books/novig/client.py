"""Novig public REST client (no key, no signature).

The `/v3/public/*` routes are unauthenticated and throttled per IP at the
edge. Measured 2026-10-03: ~9-20 request burst, then ~2 req/s sustained
(4 req/s drew 429s on ~20% of calls). Every call goes through one token
bucket so the catalog refresh and the book poller share the budget.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx


logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("NOVIG_BASE_URL", "https://api.novig.com")
DEFAULT_RPS = float(os.environ.get("NOVIG_PUBLIC_RPS", "1.5"))
DEFAULT_BURST = int(os.environ.get("NOVIG_PUBLIC_BURST", "4"))


class NovigAPIError(Exception):
    pass


class _TokenBucket:
    def __init__(self, rate: float, burst: int):
        self.rate = max(rate, 0.1)
        self.capacity = max(burst, 1)
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self.blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.updated) * self.rate,
                )
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self.tokens) / self.rate)

    def block_for(self, seconds: float) -> None:
        """Server said 429 — stop everyone until Retry-After elapses."""
        self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)
        self.tokens = 0.0


class NovigClient:
    def __init__(self, rps: float = DEFAULT_RPS, burst: int = DEFAULT_BURST):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(15.0, connect=10.0),
            headers={"Accept": "application/json"},
        )
        self._bucket = _TokenBucket(rps, burst)
        self.requests = 0
        self.rate_limited = 0
        self.errors = 0

    async def _get(
        self, path: str, params: dict | None = None,
        etag: str | None = None, retries: int = 2,
    ) -> tuple[int, Any, str | None]:
        """(status, json-or-None, etag). 304 → (304, None, etag)."""
        headers = {"If-None-Match": etag} if etag else None
        for attempt in range(retries + 1):
            await self._bucket.acquire()
            self.requests += 1
            try:
                r = await self._http.get(path, params=params, headers=headers)
            except httpx.HTTPError as e:
                self.errors += 1
                if attempt == retries:
                    raise NovigAPIError(f"GET {path}: {e}") from e
                await asyncio.sleep(1.0 + attempt)
                continue
            if r.status_code == 429:
                self.rate_limited += 1
                try:
                    wait = float(r.headers.get("Retry-After") or 2)
                except ValueError:
                    wait = 2.0
                self._bucket.block_for(wait)
                if attempt == retries:
                    raise NovigAPIError(f"GET {path}: 429 after {retries + 1} tries")
                continue
            if r.status_code == 304:
                return 304, None, etag
            if r.status_code >= 400:
                self.errors += 1
                raise NovigAPIError(f"GET {path}: HTTP {r.status_code} {r.text[:200]}")
            return r.status_code, r.json(), r.headers.get("ETag")
        raise NovigAPIError(f"GET {path}: retries exhausted")

    async def _paged(self, path: str, params: dict) -> list[dict]:
        items: list[dict] = []
        after: str | None = None
        while True:
            p = dict(params, limit=5000)
            if after:
                p["after"] = after
            _, body, _ = await self._get(path, p)
            items.extend(body.get("items") or [])
            after = body.get("next")
            if not after:
                return items

    async def list_events(self, **params) -> list[dict]:
        return await self._paged("/v3/public/catalog/events", params)

    async def list_markets(self, **params) -> list[dict]:
        return await self._paged("/v3/public/catalog/markets", params)

    async def get_book(
        self, market_id: str, etag: str | None = None,
    ) -> tuple[dict | None, str | None]:
        """(book, etag). book is None when unchanged since `etag` (304)."""
        status, body, new_etag = await self._get(
            f"/v3/public/catalog/markets/{market_id}/book", etag=etag,
        )
        return (None if status == 304 else body), new_etag

    def stats(self) -> dict:
        return {
            "requests": self.requests,
            "rate_limited": self.rate_limited,
            "errors": self.errors,
            "rps": self._bucket.rate,
        }

    async def aclose(self) -> None:
        await self._http.aclose()
