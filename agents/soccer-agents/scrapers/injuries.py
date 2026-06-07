# scrapers/injuries.py
"""Fetch squad availability (injuries, suspensions) from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

logger = logging.getLogger("mirofish.scrapers.injuries")

LEAGUE_SLUGS = {
    "MLS": "usa.1", "Eredivisie": "ned.1", "Serie A": "ita.1",
    "EPL": "eng.1", "Bundesliga": "ger.1", "La Liga": "esp.1", "Ligue 1": "fra.1",
}


def get_squad_injuries(team_name: str, league: str = "MLS") -> list[dict]:
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"{ESPN_API_BASE}/{slug}/teams"

    try:
        resp = requests.get(url, params={"limit": 100}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("ESPN injuries error for %s: %s", team_name, e)
        return []

    for group in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        team_data = group.get("team", {})
        if team_data.get("displayName") == team_name:
            injuries_raw = team_data.get("injuries", [])
            return [
                {
                    "player": inj.get("athlete", {}).get("displayName", "Unknown"),
                    "status": inj.get("status", "Unknown"),
                    "injury": inj.get("type", {}).get("description", "Unknown"),
                    "team": team_name,
                }
                for inj in injuries_raw
            ]

    logger.debug("No injury data found for %s", team_name)
    return []
