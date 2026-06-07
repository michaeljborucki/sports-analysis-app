"""Pull final NBA scores via nba_api (ScoreboardV3)."""
import logging
from datetime import date

from nba_api.stats.endpoints import ScoreboardV3

logger = logging.getLogger("mirofish.scrapers.scores")


def get_final_scores(game_date: str = None) -> list[dict]:
    """Get final scores for all NBA games on a date.

    Returns list of dicts with:
        game_id, away, home, away_score, home_score,
        away_score_h1, home_score_h1,
        home_score_q1-q4, away_score_q1-q4,
        total_points, total_points_h1, status
    """
    if game_date is None:
        game_date = date.today().isoformat()

    try:
        sb = ScoreboardV3(game_date=game_date)
        data = sb.get_dict()
    except Exception as e:
        logger.error("Failed to fetch scores for %s: %s", game_date, e)
        return []

    scoreboard = data.get("scoreboard", {})
    games = scoreboard.get("games", [])

    scores = []
    for g in games:
        if g.get("gameStatus") != 3:  # 3 = Final
            continue

        home = g.get("homeTeam", {})
        away = g.get("awayTeam", {})

        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        # Extract quarter scores from periods array
        home_periods = {p["period"]: int(p["score"]) for p in home.get("periods", [])}
        away_periods = {p["period"]: int(p["score"]) for p in away.get("periods", [])}

        home_h1 = home_periods.get(1, 0) + home_periods.get(2, 0)
        away_h1 = away_periods.get(1, 0) + away_periods.get(2, 0)

        score_dict = {
            "game_id": g.get("gameId", ""),
            "away": away.get("teamTricode", ""),
            "home": home.get("teamTricode", ""),
            "away_score": away_score,
            "home_score": home_score,
            "away_score_h1": away_h1,
            "home_score_h1": home_h1,
            "total_points": away_score + home_score,
            "total_points_h1": away_h1 + home_h1,
            "status": "Final",
        }
        for q in range(1, 5):
            score_dict[f"home_score_q{q}"] = home_periods.get(q, 0)
            score_dict[f"away_score_q{q}"] = away_periods.get(q, 0)
        scores.append(score_dict)

    return scores
