"""Fetch soccer final scores from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

logger = logging.getLogger("mirofish.scrapers.scores")

LEAGUE_SLUGS = {
    "MLS": "usa.1", "Eredivisie": "ned.1", "Serie A": "ita.1",
    "EPL": "eng.1", "Bundesliga": "ger.1", "La Liga": "esp.1", "Ligue 1": "fra.1",
}


def get_final_scores(game_date: str = None, league: str = "MLS") -> list[dict]:
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"{ESPN_API_BASE}/{slug}/scoreboard"
    params = {}
    if game_date:
        params["dates"] = game_date.replace("-", "")

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("ESPN scores error: %s", e)
        return []

    data = resp.json()
    results = []

    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")

        if status != "STATUS_FINAL":
            continue

        home = away = None
        home_score = away_score = 0

        for team_entry in comp.get("competitors", []):
            team_info = team_entry.get("team", {})
            score = int(team_entry.get("score", 0))
            if team_entry.get("homeAway") == "home":
                home = team_info.get("displayName", "")
                home_score = score
            else:
                away = team_info.get("displayName", "")
                away_score = score

        if home and away:
            results.append({
                "home": home, "away": away,
                "home_score": home_score, "away_score": away_score,
                "total_goals": home_score + away_score,
                "both_scored": home_score > 0 and away_score > 0,
            })

    logger.info("[scores] %s on %s: %d final scores", league, game_date, len(results))
    return results
