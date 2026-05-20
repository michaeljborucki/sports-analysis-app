from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx


logger = logging.getLogger(__name__)


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
TIMEOUT = 15.0

# Kalshi auth header names. Per their docs: every authenticated request
# carries an HMAC-style signature computed over `timestamp || method || path`
# using the user's RSA private key (PSS-SHA256). The signed path is the
# FULL path from `/trade-api/v2/...` onward (NOT just the relative URL).
_AUTH_HEADER_KEY = "KALSHI-ACCESS-KEY"
_AUTH_HEADER_SIG = "KALSHI-ACCESS-SIGNATURE"
_AUTH_HEADER_TS  = "KALSHI-ACCESS-TIMESTAMP"


class KalshiAPIError(Exception):
    pass


class KalshiClient:
    """Async HTTP wrapper for Kalshi's REST API.

    Read endpoints (catalog + market quotes) work without auth. When
    `api_key` + `private_key_path` are provided, every request is signed
    with the RSA-PSS scheme Kalshi requires — unlocks higher rate
    limits, the portfolio/positions/orders endpoints, and WebSocket
    auth (handled separately).

    Polls `/markets` with `series_ticker=` filters at the cadence set by
    the fetcher. Pagination uses Kalshi's opaque `cursor` field — keep
    fetching until empty.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        api_key: str | None = None,
        private_key_path: Path | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        # Lazy client — opened on first request, closed on aclose().
        self._client: httpx.AsyncClient | None = None
        self._api_key = api_key or None
        # Lazy-loaded RSA private key. We hold the path and only load the
        # key on first signed request — avoids paying the parse cost if
        # the client only does unauth'd reads.
        self._private_key_path = private_key_path
        self._private_key: Any = None

    @property
    def is_authenticated(self) -> bool:
        """True iff both an API key and a private-key path are configured.
        Note: doesn't actually verify the key is loadable or the API
        accepts our signature — `aprobe()` does that with a live call."""
        return bool(self._api_key and self._private_key_path)

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key
        if self._private_key_path is None:
            raise KalshiAPIError("kalshi auth requested but no private key configured")
        try:
            from cryptography.hazmat.primitives import serialization
        except ImportError as e:
            raise KalshiAPIError(
                "kalshi auth needs `cryptography`; pip install cryptography"
            ) from e
        try:
            data = self._private_key_path.read_bytes()
        except OSError as e:
            raise KalshiAPIError(
                f"kalshi private key {self._private_key_path}: {e}"
            ) from e
        self._private_key = serialization.load_pem_private_key(data, password=None)
        return self._private_key

    def _sign_headers(self, method: str, path: str) -> dict[str, str]:
        """Build the three Kalshi auth headers for the given request.

        `path` MUST start with `/trade-api/v2/...` — the docs are
        explicit that the signature is over the FULL canonical path,
        not the relative URL we hand httpx. We derive it from the
        base_url's URL path + the endpoint path.
        """
        if not self._api_key:
            raise KalshiAPIError("kalshi auth requested but no api key configured")
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        pk = self._load_private_key()
        ts = str(int(time.time() * 1000))
        msg = (ts + method.upper() + path).encode()
        sig = pk.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            _AUTH_HEADER_KEY: self._api_key,
            _AUTH_HEADER_SIG: base64.b64encode(sig).decode(),
            _AUTH_HEADER_TS:  ts,
        }

    def _canonical_path(self, relative: str) -> str:
        """The signing payload uses the full path from `/trade-api/v2/...`.
        httpx is configured with a base_url that already includes that
        prefix, so we have to reconstruct it for the signature."""
        # base_url like "https://api.elections.kalshi.com/trade-api/v2"
        from urllib.parse import urlparse
        prefix = urlparse(self.base_url).path or ""
        rel = relative if relative.startswith("/") else "/" + relative
        return prefix.rstrip("/") + rel

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
            # Sign the request when credentials are configured — Kalshi
            # gives auth'd requests a much higher rate limit on /markets
            # (the public-anonymous cap throttles us at ~26 calls/cycle
            # across our Phase 2 series, producing 429s + stale data).
            # Falls back to unauth on signing failure so a bad key
            # doesn't take down the fetcher entirely.

            # 429-aware retry: even with auth, transient rate-limit spikes
            # are common when many series fire in close succession. Retry
            # 2× with exponential backoff (0.6s, 1.5s) + jitter. Sign
            # headers per retry — signatures bake in the timestamp.
            _backoffs = (0.6, 1.5)
            resp = None
            for attempt in range(len(_backoffs) + 1):
                headers = None
                if self.is_authenticated:
                    try:
                        headers = self._sign_headers("GET", self._canonical_path("/markets"))
                    except KalshiAPIError as e:
                        logger.warning("kalshi sign failed (continuing unauth): %s", e)
                try:
                    resp = await client.get("/markets", params=params, headers=headers)
                except httpx.HTTPError as e:
                    raise KalshiAPIError(
                        f"kalshi list_markets {series_ticker}: transport: {e}"
                    ) from e
                if resp.status_code != 429 or attempt == len(_backoffs):
                    break
                delay = _backoffs[attempt] + random.random() * 0.25
                logger.info(
                    "kalshi 429 %s — retry %d/%d after %.2fs",
                    series_ticker, attempt + 1, len(_backoffs), delay,
                )
                await asyncio.sleep(delay)

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

    # ────────────────────── Authenticated endpoints ─────────────────────

    async def _signed_get(self, path: str, params: dict | None = None) -> dict:
        """Authenticated GET. `path` is the relative endpoint (e.g.
        `/portfolio/balance`); we prepend the canonical `/trade-api/v2`
        prefix for the signature. Raises KalshiAPIError on non-200."""
        if not self.is_authenticated:
            raise KalshiAPIError(
                "kalshi: authenticated endpoint called but no credentials configured"
            )
        canonical = self._canonical_path(path)
        headers = self._sign_headers("GET", canonical)
        client = await self._get_client()
        try:
            resp = await client.get(path, params=params or None, headers=headers)
        except httpx.HTTPError as e:
            raise KalshiAPIError(f"kalshi {path}: transport: {e}") from e
        if resp.status_code != 200:
            raise KalshiAPIError(
                f"kalshi {path}: {resp.status_code} {resp.text[:200]}"
            )
        try:
            return resp.json()
        except Exception as e:
            raise KalshiAPIError(
                f"kalshi {path}: non-JSON response: {resp.text[:200]}"
            ) from e

    async def get_portfolio_balance(self) -> dict:
        """Returns {balance, balance_breakdown, portfolio_value, updated_ts}.
        All amounts are in cents. Requires auth."""
        return await self._signed_get("/portfolio/balance")

    async def get_portfolio_positions(
        self,
        limit: int = 200,
        settlement_status: str | None = None,
    ) -> list[dict]:
        """Returns paginated list of open positions. Each entry has
        `ticker, position, market_exposure, realized_pnl, fees_paid, ...`.
        Requires auth."""
        out: list[dict] = []
        cursor: str | None = None
        for _ in range(50):  # safety cap — typical portfolios under a few hundred positions
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            if settlement_status:
                params["settlement_status"] = settlement_status
            data = await self._signed_get("/portfolio/positions", params=params)
            # Kalshi returns `market_positions` (or `event_positions`) — collect both
            for key in ("market_positions", "event_positions", "positions"):
                items = data.get(key) or []
                if items:
                    out.extend(items)
            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out

    async def get_portfolio_fills(self, limit: int = 200) -> list[dict]:
        """Returns paginated trade fills (executions). Useful for
        tracking what bets were actually placed + at what price."""
        out: list[dict] = []
        cursor: str | None = None
        for _ in range(50):
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            data = await self._signed_get("/portfolio/fills", params=params)
            out.extend(data.get("fills") or [])
            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out
