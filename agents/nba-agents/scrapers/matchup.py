"""Fetch NBA matchup-specific data."""
import logging
from datetime import date
from config import nba_season

logger = logging.getLogger("mirofish.scrapers.matchup")


def compute_pace_matchup(pace_home: float, pace_away: float) -> dict:
    """Compute pace matchup projection."""
    projected_pace = round((pace_home + pace_away) / 2, 1)
    projected_possessions = round(projected_pace)
    diff = abs(pace_home - pace_away)
    if diff < 2:
        mismatch = "Both teams play at similar pace"
    elif diff < 5:
        mismatch = "Moderate pace differential"
    else:
        fast = "home" if pace_home > pace_away else "away"
        mismatch = f"Significant pace mismatch — {fast} team plays much faster"
    return {
        "projected_pace": projected_pace,
        "projected_possessions": projected_possessions,
        "mismatch": mismatch,
    }


def get_matchup_data(home_abbrev: str, away_abbrev: str, season: str = None) -> dict:
    """Get head-to-head and pace matchup data."""
    if season is None:
        season = nba_season(date.today().isoformat())

    result = {
        "h2h_record": "",
        "last_meeting": "",
        "pace_matchup": compute_pace_matchup(100.0, 100.0),
    }

    try:
        from nba_api.stats.endpoints import LeagueGameLog
        logs = LeagueGameLog(season=season, season_type_all_star="Regular Season")
        df = logs.get_data_frames()[0]

        home_games = df[df["TEAM_ABBREVIATION"] == home_abbrev]
        h2h = home_games[home_games["MATCHUP"].str.contains(away_abbrev, na=False)]

        if not h2h.empty:
            wins = int((h2h["WL"] == "W").sum())
            losses = int((h2h["WL"] == "L").sum())
            result["h2h_record"] = f"{wins}-{losses}"
            last = h2h.iloc[0]
            result["last_meeting"] = f"{last['MATCHUP']} ({last.get('GAME_DATE', '')})"

    except Exception as e:
        logger.warning("Failed to fetch matchup data for %s vs %s: %s", home_abbrev, away_abbrev, e)

    return result
