"""Fetch soccer fixture schedules from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

logger = logging.getLogger("mirofish.scrapers.schedule")

LEAGUE_SLUGS = {
    "MLS": "usa.1",
    "Eredivisie": "ned.1",
    "Serie A": "ita.1",
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "La Liga": "esp.1",
    "Ligue 1": "fra.1",
}


def get_fixtures(league: str = "MLS", game_date: str = None) -> list[dict]:
    slug = LEAGUE_SLUGS.get(league)
    if not slug:
        logger.warning("Unknown league slug for: %s", league)
        return []

    url = f"{ESPN_API_BASE}/{slug}/scoreboard"
    params = {}
    if game_date:
        params["dates"] = game_date.replace("-", "")

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("ESPN API error for %s: %s", league, e)
        return []

    data = resp.json()
    fixtures = []

    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])

        home = away = None
        for team_entry in competitors:
            if team_entry.get("homeAway") == "home":
                home = team_entry.get("team", {})
            else:
                away = team_entry.get("team", {})

        if not home or not away:
            continue

        fixtures.append({
            "event_id": event.get("id"),
            "home_team": home.get("displayName", ""),
            "away_team": away.get("displayName", ""),
            "venue": comp.get("venue", {}).get("fullName", ""),
            "kickoff_time": event.get("date", ""),
            "league": league,
        })

    logger.info("[schedule] %s on %s: %d fixtures", league, game_date, len(fixtures))
    return fixtures
