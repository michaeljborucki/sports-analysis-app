from __future__ import annotations

import logging

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
TIMEOUT = 15.0


class OddsAPIError(Exception):
    pass


def _rate_info(resp: httpx.Response) -> dict:
    return {
        "requests_used": int(resp.headers.get("x-requests-used", 0) or 0),
        "requests_remaining": int(resp.headers.get("x-requests-remaining", 0) or 0),
    }


class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def list_sports(self, active_only: bool = True) -> list[dict]:
        """GET /v4/sports — lists every available sport key. Free (no quota)."""
        params = {"apiKey": self.api_key}
        if active_only:
            params["all"] = "false"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{BASE_URL}/sports", params=params)
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
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
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
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            info = _rate_info(resp)
            if resp.status_code == 200:
                return resp.json(), info
            if resp.status_code == 422:
                return {}, info
            raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")
