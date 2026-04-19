from __future__ import annotations

import logging

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
MLB_SPORT_KEY = "baseball_mlb"
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

    async def fetch_game_level(
        self, markets: list[str], regions: list[str]
    ) -> tuple[list[dict], dict]:
        """Game-level endpoint — one call covers every MLB event today.
        Used by the `main` tier. Quota cost = regions × markets.
        """
        params = {
            "apiKey": self.api_key,
            "regions": ",".join(regions),
            "oddsFormat": "american",
            "markets": ",".join(markets),
        }
        url = f"{BASE_URL}/sports/{MLB_SPORT_KEY}/odds"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            info = _rate_info(resp)
            if resp.status_code == 200:
                return resp.json(), info
            if resp.status_code == 422:
                logger.warning("422 from odds API (game-level): %s", resp.text[:200])
                return [], info
            raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")

    async def fetch_event_markets(
        self, event_id: str, markets: list[str], regions: list[str]
    ) -> tuple[dict, dict]:
        """Per-event endpoint — for alt lines, first-innings, player props.
        Quota cost = regions × markets **returned** (empties are free).
        """
        params = {
            "apiKey": self.api_key,
            "regions": ",".join(regions),
            "oddsFormat": "american",
            "markets": ",".join(markets),
        }
        url = f"{BASE_URL}/sports/{MLB_SPORT_KEY}/events/{event_id}/odds"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            info = _rate_info(resp)
            if resp.status_code == 200:
                return resp.json(), info
            if resp.status_code == 422:
                return {}, info
            raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")

    # Backwards-compat for any remaining callers
    async def fetch_mlb_core(self) -> tuple[list[dict], dict]:
        return await self.fetch_game_level(
            markets=["h2h", "spreads", "totals"],
            regions=["us", "us2", "us_ex", "eu", "uk"],
        )
