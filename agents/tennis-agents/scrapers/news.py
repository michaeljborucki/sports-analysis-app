"""Tennis news and injury reports.

NOTE: API-Tennis does not expose a `get_injuries` method (returns 404). The
`get_player_news` function below is retained for backward compatibility but
currently returns `[]` on every call. See INVESTIGATE_LATER.md item "Injury
data source" for follow-up.
"""
import logging
import requests
from config import API_TENNIS_KEY, API_TENNIS_BASE

logger = logging.getLogger("mirofish.scrapers.news")


def get_player_news(player_name: str = None) -> list[dict]:
    if not API_TENNIS_KEY:
        logger.warning("API_TENNIS_KEY not set, no news available")
        return []
    params = {"method": "get_injuries", "APIkey": API_TENNIS_KEY}
    try:
        resp = requests.get(API_TENNIS_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("News fetch error: %s", e)
        return []
    news = []
    for item in data.get("result", []):
        player = item.get("player_name", "")
        if player_name and player_name.lower() not in player.lower():
            continue
        news.append({"player": player, "type": item.get("type", "injury"), "description": item.get("description", ""), "date": item.get("date", "")})
    return news
