"""Fetch NBA team season stats via nba_api."""
import logging
from datetime import date
from config import nba_season

logger = logging.getLogger("mirofish.scrapers.team_stats")


def pythagorean_win_pct(pts_scored: float, pts_allowed: float, exp: float = 14) -> float:
    """Calculate Pythagorean expected win percentage. NBA exponent ~14."""
    if pts_scored == 0 and pts_allowed == 0:
        return 0.5
    return pts_scored ** exp / (pts_scored ** exp + pts_allowed ** exp)


def get_team_profile(team_abbrev: str, season: str = None) -> dict:
    """Get NBA team profile with advanced stats."""
    if season is None:
        season = nba_season(date.today().isoformat())

    try:
        from nba_api.stats.endpoints import LeagueDashTeamStats
        from nba_api.stats.static import teams as nba_teams
        team_info = nba_teams.find_team_by_abbreviation(team_abbrev)
        if not team_info:
            return {"team": team_abbrev, "error": "unknown abbreviation"}
        stats = LeagueDashTeamStats(season=season, per_mode_detailed="PerGame")
        df = stats.get_data_frames()[0]
    except Exception as e:
        logger.error("Failed to fetch team stats for %s: %s", team_abbrev, e)
        return {"team": team_abbrev, "error": str(e)}

    row = df[df["TEAM_ID"] == team_info["id"]]
    if row.empty:
        return {"team": team_abbrev, "error": "team not found"}

    r = row.iloc[0]
    wins = int(r.get("W", 0))
    losses = int(r.get("L", 0))
    ppg = float(r.get("PTS", 0))
    opp_ppg = float(r.get("OPP_PTS", ppg))

    return {
        "team": team_abbrev,
        "record": f"{wins}-{losses}",
        "pct": round(r.get("W_PCT", 0), 3),
        "home_record": "",
        "away_record": "",
        "ortg": round(r.get("OFF_RATING", 0), 1),
        "drtg": round(r.get("DEF_RATING", 0), 1),
        "net_rtg": round(r.get("NET_RATING", 0), 1),
        "pace": round(r.get("PACE", 0), 1),
        "efg_pct": round(r.get("EFG_PCT", 0), 3),
        "tov_pct": round(r.get("TM_TOV_PCT", 0), 3),
        "oreb_pct": round(r.get("OREB_PCT", 0), 3),
        "ft_rate": round(r.get("FTA_RATE", 0), 3),
        "three_rate": round(r.get("FG3A", 0) / max(r.get("FGA", 1), 1), 3),
        "three_pct": round(r.get("FG3_PCT", 0), 3),
        "last_10": "",
        "trend": "",
        "ppg": round(ppg, 1),
        "opp_ppg": round(opp_ppg, 1),
        "pythagorean_win_pct": round(pythagorean_win_pct(ppg, opp_ppg), 3),
    }
