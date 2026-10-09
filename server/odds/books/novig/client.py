"""Novig REST client — read-only.

Two modes, chosen at construction:

  * public (default): unsigned `/v3/public/*` routes, throttled per IP at the
    edge. Measured 2026-10-03: ~9-20 request burst, then ~2 req/s sustained
    (4 req/s drew 429s on ~20% of calls).
  * signed: when NOVIG_KEY_ID + NOVIG_KEY_PEM are set, the same reads go to
    the authenticated `/v3/catalog/*` routes with a NOVIG-V3 Ed25519
    signature. Those draw from the account's `read` bucket (live limits read
    2026-10-09: capacity 64, refill 16/s), so the poller can run far faster.

READ-ONLY BY CONSTRUCTION: this client only issues GETs. The configured key
may carry `trading` scope (it can place real-money orders), so nothing here
may ever send POST/DELETE or touch /v3/orders — the signer refuses any
method but GET. Every call goes through one token bucket so the catalog
refresh and the book poller share the budget.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("NOVIG_BASE_URL", "https://api.novig.com")
# 1.8 (was 1.5): Novig's own catalog now drives coverage (~940 targets vs
# ~730), and at 1.5 req/s one pass over every target took ~627s, past the
# 600s stale-row purge. 1.8 keeps a pass near ~520s, under the ~2 req/s
# measured sustained limit. Watch `http_rate_limited` on /api/novig/status.
DEFAULT_RPS = float(os.environ.get("NOVIG_PUBLIC_RPS", "1.8"))
DEFAULT_BURST = int(os.environ.get("NOVIG_PUBLIC_BURST", "4"))
# Signed reads: half the account's 16/s `read` refill, leaving headroom for
# anything else using the same key.
SIGNED_RPS = float(os.environ.get("NOVIG_SIGNED_RPS", "8"))
SIGNED_BURST = int(os.environ.get("NOVIG_SIGNED_BURST", "16"))


def _enc(part: str) -> str:
    # NOVIG-V3 query canonicalization: unreserved chars stay, everything else
    # is %XX (uppercase). quote() never emits '+' for spaces.
    return quote(part, safe="-._~")


def canonical_query(params: dict | None) -> str:
    """Encoded `k=v` pairs sorted by name then value — the exact string both
    signed and sent, so the server's canonical form matches ours."""
    if not params:
        return ""
    pairs = sorted((_enc(str(k)), _enc(str(v))) for k, v in params.items())
    return "&".join(f"{k}={v}" for k, v in pairs)


class _Signer:
    """NOVIG-V3 request signer. GET only — see module docstring."""

    def __init__(self, key_id: str, pem_path: Path):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        self.key_id = key_id
        self._key = load_pem_private_key(pem_path.read_bytes(), None)

    def headers(self, method: str, path: str, query: str) -> dict[str, str]:
        if method != "GET":
            raise NovigAPIError(f"refusing to sign {method} {path}: client is read-only")
        ts = str(int(time.time() * 1000))
        canon = "\n".join(
            ["NOVIG-V3", ts, method, path, query, hashlib.sha256(b"").hexdigest()]
        )
        return {
            "Novig-Key-Id": self.key_id,
            "Novig-Timestamp": ts,
            "Novig-Signature": base64.b64encode(self._key.sign(canon.encode())).decode(),
        }


def _signer_from_env() -> "_Signer | None":
    key_id = (os.environ.get("NOVIG_KEY_ID") or "").strip()
    pem = (os.environ.get("NOVIG_KEY_PEM") or "").strip()
    if not key_id or not pem:
        return None
    path = Path(pem).expanduser()
    try:
        return _Signer(key_id, path)
    except Exception:
        logger.exception("novig: signing key unusable (%s); using public routes", path)
        return None


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
    def __init__(
        self, rps: float | None = None, burst: int | None = None,
        signer: "_Signer | None | bool" = True,
    ):
        """`signer=True` loads one from the environment (None when unset);
        pass None/False to force the public routes."""
        self._signer = _signer_from_env() if signer is True else (signer or None)
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(15.0, connect=10.0),
            headers={"Accept": "application/json"},
        )
        if self._signer is not None:
            logger.info("novig: signed read-only mode (/v3/catalog)")
            rps = SIGNED_RPS if rps is None else rps
            burst = SIGNED_BURST if burst is None else burst
        else:
            rps = DEFAULT_RPS if rps is None else rps
            burst = DEFAULT_BURST if burst is None else burst
        self._bucket = _TokenBucket(rps, burst)
        self.requests = 0
        self.rate_limited = 0
        self.errors = 0

    async def _get(
        self, path: str, params: dict | None = None,
        etag: str | None = None, retries: int = 2,
    ) -> tuple[int, Any, str | None]:
        """(status, json-or-None, etag). 304 → (304, None, etag)."""
        if self._signer is not None:
            # /v3/public/catalog/... -> /v3/catalog/... (same shapes, signed).
            path = path.replace("/v3/public/", "/v3/", 1)
        query = canonical_query(params)
        url = f"{path}?{query}" if query else path
        for attempt in range(retries + 1):
            await self._bucket.acquire()
            self.requests += 1
            headers = {"If-None-Match": etag} if etag else {}
            if self._signer is not None:
                # Re-signed per attempt: the timestamp must be within ±30s.
                headers.update(self._signer.headers("GET", path, query))
            try:
                r = await self._http.get(url, headers=headers or None)
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
            "signed": self._signer is not None,
        }

    async def aclose(self) -> None:
        await self._http.aclose()
