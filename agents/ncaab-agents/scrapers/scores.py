"""Pull final scores from ESPN API for NCAAB."""
import requests
import logging
from datetime import date
from config import ESPN_CBB_BASE

logger = logging.getLogger("mirofish.scrapers.scores")


def get_final_scores(game_date: str = None) -> list[dict]:
    """Get final scores for all completed NCAAB games on a date.

    Returns list of dicts with keys:
    away, home, away_score, home_score, away_score_h1, home_score_h1,
    total_points, total_points_h1, status, game_id
    """
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{ESPN_CBB_BASE}/scoreboard"
    params = {"dates": game_date.replace("-", "")}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Failed to fetch scores: %s", e)
        return []

    scores = []
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status = competition.get("status", {}).get("type", {}).get("name", "")

        if status != "STATUS_FINAL":
            continue

        competitors = competition.get("competitors", [])
        if len(competitors) != 2:
            continue

        home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_team = home_comp.get("team", {})
        away_team = away_comp.get("team", {})

        home_score = int(home_comp.get("score", 0))
        away_score = int(away_comp.get("score", 0))

        # Extract first half scores from linescores
        home_linescores = home_comp.get("linescores", [])
        away_linescores = away_comp.get("linescores", [])

        home_score_h1 = int(home_linescores[0].get("value", 0)) if home_linescores else 0
        away_score_h1 = int(away_linescores[0].get("value", 0)) if away_linescores else 0

        scores.append({
            "away": away_team.get("abbreviation", away_team.get("displayName", "")),
            "home": home_team.get("abbreviation", home_team.get("displayName", "")),
            "away_score": away_score,
            "home_score": home_score,
            "away_score_h1": away_score_h1,
            "home_score_h1": home_score_h1,
            "total_points": away_score + home_score,
            "total_points_h1": away_score_h1 + home_score_h1,
            "status": "Final",
            "game_id": event.get("id", ""),
        })

    logger.info("Found %d final scores for %s", len(scores), game_date)
    return scores
