"""Fetch today's NBA schedule via nba_api."""
import logging
from datetime import date
from nba_api.stats.endpoints import ScoreboardV3

logger = logging.getLogger("mirofish.scrapers.schedule")


def get_todays_games(game_date: str = None) -> list[dict]:
    """Get today's NBA games.

    Returns list of dicts with game_id, home_team, away_team, game_time, arena, team IDs.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    try:
        sb = ScoreboardV3(game_date=game_date)
        data = sb.get_dict()
    except Exception as e:
        logger.error("Failed to fetch schedule for %s: %s", game_date, e)
        return []

    games = []
    for g in data.get("scoreboard", {}).get("games", []):
        home = g.get("homeTeam", {})
        away = g.get("awayTeam", {})
        games.append({
            "game_id": g.get("gameId", ""),
            "home_team": home.get("teamTricode", ""),
            "away_team": away.get("teamTricode", ""),
            "game_time": g.get("gameStatusText", ""),
            "arena": g.get("arenaName", ""),
            "home_team_id": home.get("teamId", 0),
            "away_team_id": away.get("teamId", 0),
        })

    logger.info("Found %d games for %s", len(games), game_date)
    return games
