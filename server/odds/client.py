from __future__ import annotations

import logging

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
MLB_SPORT_KEY = "baseball_mlb"
CORE_MARKETS = "h2h,spreads,totals"
REGIONS = "us,us2"
TIMEOUT = 15.0


class OddsAPIError(Exception):
    pass


class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_mlb_core(self) -> tuple[list[dict], dict]:
        """Fetch today's MLB games with h2h/spreads/totals."""
        params = {
            "apiKey": self.api_key,
            "regions": REGIONS,
            "oddsFormat": "american",
            "markets": CORE_MARKETS,
        }
        url = f"{BASE_URL}/sports/{MLB_SPORT_KEY}/odds"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            rate_info = {
                "requests_used": int(resp.headers.get("x-requests-used", 0) or 0),
                "requests_remaining": int(resp.headers.get("x-requests-remaining", 0) or 0),
            }
            if resp.status_code == 200:
                return resp.json(), rate_info
            if resp.status_code == 422:
                logger.warning("422 from odds API: %s", resp.text[:200])
                return [], rate_info
            raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")

    async def fetch_event_markets(
        self, event_id: str, markets: str
    ) -> tuple[dict, dict]:
        params = {
            "apiKey": self.api_key,
            "regions": REGIONS,
            "oddsFormat": "american",
            "markets": markets,
        }
        url = f"{BASE_URL}/sports/{MLB_SPORT_KEY}/events/{event_id}/odds"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            rate_info = {
                "requests_used": int(resp.headers.get("x-requests-used", 0) or 0),
                "requests_remaining": int(resp.headers.get("x-requests-remaining", 0) or 0),
            }
            if resp.status_code == 200:
                return resp.json(), rate_info
            if resp.status_code == 422:
                return {}, rate_info
            raise OddsAPIError(f"{resp.status_code}: {resp.text[:500]}")
