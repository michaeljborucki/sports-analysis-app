"""Compute rest, back-to-back, and travel data for NBA teams."""
import logging
from datetime import date, datetime, timedelta
from config import nba_season

logger = logging.getLogger("mirofish.scrapers.rest")


def compute_rest_from_dates(game_date: str, recent_game_dates: list[str]) -> dict:
    """Compute rest metrics from a list of recent game dates."""
    today = datetime.strptime(game_date, "%Y-%m-%d").date()

    if not recent_game_dates:
        return {
            "days_rest": 3,
            "is_b2b": False,
            "games_last_7": 0,
            "road_trip_length": 0,
            "travel_miles": 0,
            "tz_change": 0,
        }

    last_game = datetime.strptime(recent_game_dates[0], "%Y-%m-%d").date()
    days_rest = (today - last_game).days - 1

    week_ago = today - timedelta(days=7)
    games_last_7 = sum(
        1 for d in recent_game_dates
        if datetime.strptime(d, "%Y-%m-%d").date() >= week_ago
    )

    return {
        "days_rest": max(days_rest, 0),
        "is_b2b": days_rest == 0,
        "games_last_7": games_last_7,
        "road_trip_length": 0,
        "travel_miles": 0,
        "tz_change": 0,
    }


def get_rest_data(team_abbrev: str, game_date: str) -> dict:
    """Fetch rest and schedule data for a team."""
    season = nba_season(game_date)

    try:
        from nba_api.stats.endpoints import LeagueGameLog
        logs = LeagueGameLog(season=season, season_type_all_star="Regular Season")
        df = logs.get_data_frames()[0]
        team_games = df[df["TEAM_ABBREVIATION"] == team_abbrev].copy()

        team_games["GAME_DT"] = team_games["GAME_DATE"].apply(
            lambda x: datetime.strptime(x[:10], "%Y-%m-%d").date()
        )
        today = datetime.strptime(game_date, "%Y-%m-%d").date()
        past_games = team_games[team_games["GAME_DT"] < today]
        past_games = past_games.sort_values("GAME_DT", ascending=False)

        recent_dates = [d.strftime("%Y-%m-%d") for d in past_games["GAME_DT"].head(10)]
        return compute_rest_from_dates(game_date, recent_dates)

    except Exception as e:
        logger.warning("Failed to fetch rest data for %s: %s", team_abbrev, e)
        return compute_rest_from_dates(game_date, [])
