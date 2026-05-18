from __future__ import annotations

import asyncio
import logging
import random

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
TIMEOUT = 15.0

# Persistent-client connection pool sizing. The fetcher fans out per-event
# requests via asyncio.gather + a semaphore; `max_keepalive_connections`
# governs how many idle TCP sockets we keep around between bursts, and
# `max_connections` caps simultaneously in-flight. Both are generous
# enough that the asyncio semaphore (typically 8) is the effective limit;
# this just prevents the underlying pool from forcing connection teardown
# between bursts (which would re-add the handshake cost we're eliminating).
_KEEPALIVE_CONNECTIONS = 20
_MAX_CONNECTIONS = 40


class OddsAPIError(Exception):
    pass


def _rate_info(resp: httpx.Response) -> dict:
    return {
        "requests_used": int(resp.headers.get("x-requests-used", 0) or 0),
        "requests_remaining": int(resp.headers.get("x-requests-remaining", 0) or 0),
    }


class OddsAPIClient:
    """Persistent-client wrapper around the Odds API v4.

    Holds a single `httpx.AsyncClient` over the lifetime of the process so
    that:
      - TCP + TLS handshakes happen ~once instead of per-call (saves
        100-200ms per request on per-event tiers that fan out 15+ calls).
      - HTTP/2 multiplexing lets multiple concurrent requests share one
        TCP connection — so the fetcher's per-event parallelism actually
        translates to wall-clock speedup instead of being bottlenecked
        on the TLS handshake queue.

    Call `aclose()` on shutdown to release the pool cleanly. The client
    is created lazily on first use so test code can construct an instance
    without spinning up a connection pool.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT,
                http2=True,
                limits=httpx.Limits(
                    max_keepalive_connections=_KEEPALIVE_CONNECTIONS,
                    max_connections=_MAX_CONNECTIONS,
                ),
            )
        return self._client

    async def aclose(self) -> None:
        """Release the underlying connection pool. Safe to call multiple
        times. Called from main.py's shutdown hook."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.exception("OddsAPIClient.aclose error")
            self._client = None

    async def _get_with_retry(
        self, url: str, params: dict,
    ) -> httpx.Response:
        """GET with 429-aware retry. The fetcher fans out per-event calls
        in bursts of up to ODDS_API_CONCURRENCY, which on small slates
        completes under a second and can transiently exceed the plan's
        per-second freq limit. Retry up to twice with jittered backoff so
        a stray 429 doesn't drop the event from the cycle's row set.

        Any non-429 status (including 200, 422, 5xx) returns immediately
        — only the freq-limit case retries.
        """
        backoffs = (0.5, 1.5)  # seconds; total worst-case wait ~2s + jitter
        for attempt in range(len(backoffs) + 1):
            # NOTE: this call must hit the raw HTTPX client — recursing
            # back through _get_with_retry would infinite-loop. The
            # callers (list_sports / fetch_game_level / fetch_event_
            # markets) use the wrapped helper; this is the one place that
            # talks to the network directly.
            resp = await self._http().get(url, params=params)
            if resp.status_code != 429 or attempt == len(backoffs):
                return resp
            delay = backoffs[attempt] + random.random() * 0.25
            logger.info(
                "Odds API 429 freq limit — retry %d/%d after %.2fs (url=%s)",
                attempt + 1, len(backoffs), delay,
                url.split("/v4/")[-1].split("?")[0],
            )
            await asyncio.sleep(delay)
        # Unreachable — the loop above always returns.
        return resp  # pragma: no cover

    async def list_sports(self, active_only: bool = True) -> list[dict]:
        """GET /v4/sports — lists every available sport key. Free (no quota)."""
        params = {"apiKey": self.api_key}
        if active_only:
            params["all"] = "false"
        resp = await self._http().get(f"{BASE_URL}/sports", params=params)
        if resp.status_code != 200:
            raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")
        return resp.json()

    async def resolve_sport_keys(
        self, patterns: tuple[str, ...] | list[str]
    ) -> list[str]:
        """Expand sport key patterns (exact or prefix ending with '*') against
        the live /sports list. Used for tennis tournament discovery."""
        need_list = any(p.endswith("*") for p in patterns)
        if not need_list:
            return list(patterns)
        all_sports = await self.list_sports(active_only=True)
        live = {s["key"] for s in all_sports}
        out: list[str] = []
        for p in patterns:
            if p.endswith("*"):
                prefix = p[:-1]
                out.extend(sorted(k for k in live if k.startswith(prefix)))
            elif p in live:
                out.append(p)
        return out

    async def fetch_game_level(
        self, sport_key: str, markets: list[str], regions: list[str]
    ) -> tuple[list[dict], dict]:
        """Game-level endpoint — one call covers every event today for this
        sport key. Quota cost = regions × markets returned.
        """
        params = {
            "apiKey": self.api_key,
            "regions": ",".join(regions),
            "oddsFormat": "american",
            "markets": ",".join(markets),
        }
        url = f"{BASE_URL}/sports/{sport_key}/odds"
        resp = await self._get_with_retry(url, params)
        info = _rate_info(resp)
        if resp.status_code == 200:
            return resp.json(), info
        if resp.status_code == 422:
            logger.warning("422 %s (game-level): %s", sport_key, resp.text[:200])
            return [], info
        raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")

    async def fetch_event_markets(
        self,
        sport_key: str,
        event_id: str,
        markets: list[str],
        regions: list[str],
    ) -> tuple[dict, dict]:
        """Per-event endpoint — for alt lines, first-innings, player props."""
        params = {
            "apiKey": self.api_key,
            "regions": ",".join(regions),
            "oddsFormat": "american",
            "markets": ",".join(markets),
        }
        url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        resp = await self._get_with_retry(url, params)
        info = _rate_info(resp)
        if resp.status_code == 200:
            return resp.json(), info
        if resp.status_code == 422:
            return {}, info
        raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")

    # ───────────────────── Historical endpoints ─────────────────────
    #
    # The historical API returns the live-shape payload wrapped in
    # {timestamp, previous_timestamp, next_timestamp, data}. We unwrap
    # `data` and surface the wrapper's `timestamp` as a secondary field
    # so the caller can record the actual snapshot moment (the Odds API
    # rounds to its archive cadence — typically the closest 5 / 10 min).

    async def fetch_historical_events(
        self,
        sport_key: str,
        date: str,
    ) -> tuple[list[dict], dict]:
        """List events on `sport_key` at archive snapshot `date` (ISO).

        Each list entry is `{id, sport_key, commence_time, home_team,
        away_team}` — same shape as the live `/events` endpoint. Used to
        discover event_ids for past wagers when the live cache no longer
        carries them.
        """
        params = {
            "apiKey": self.api_key,
            "date": date,
        }
        url = f"{BASE_URL}/historical/sports/{sport_key}/events"
        resp = await self._get_with_retry(url, params)
        info = _rate_info(resp)
        if resp.status_code == 200:
            payload = resp.json() or {}
            data = payload.get("data", payload)
            info["snapshot_timestamp"] = payload.get("timestamp")
            return data if isinstance(data, list) else [], info
        if resp.status_code == 422:
            logger.warning(
                "422 historical events %s @ %s: %s",
                sport_key, date, resp.text[:200],
            )
            return [], info
        raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")

    async def fetch_historical_event_odds(
        self,
        sport_key: str,
        event_id: str,
        date: str,
        markets: list[str],
        regions: list[str],
    ) -> tuple[dict, dict]:
        """Per-event archived odds at snapshot `date`. Same response
        shape as `fetch_event_markets`, with the historical wrapper
        unwrapped. Cost: roughly regions × markets returned, same as
        the live per-event call (per Odds API docs)."""
        params = {
            "apiKey": self.api_key,
            "date": date,
            "regions": ",".join(regions),
            "oddsFormat": "american",
            "markets": ",".join(markets),
        }
        url = (
            f"{BASE_URL}/historical/sports/{sport_key}"
            f"/events/{event_id}/odds"
        )
        resp = await self._get_with_retry(url, params)
        info = _rate_info(resp)
        if resp.status_code == 200:
            payload = resp.json() or {}
            data = payload.get("data") or {}
            info["snapshot_timestamp"] = payload.get("timestamp")
            return data if isinstance(data, dict) else {}, info
        if resp.status_code == 422:
            return {}, info
        raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")
