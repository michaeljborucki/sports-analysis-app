"""Fetch NCAAB roster context from ESPN/CBBData."""
import requests
import logging
from config import ESPN_CBB_BASE, CBBDATA_API_KEY, CBBDATA_BASE

logger = logging.getLogger("mirofish.scrapers.roster")


def get_roster_context(team_name: str, team_id: str = None, season: int = None) -> dict:
    """Get roster profile for a team.

    Returns dict with keys: team, returning_minutes_pct, top_scorers,
    transfers_in, coach, coach_tenure, new_coach
    """
    result = {
        "team": team_name,
        "returning_minutes_pct": None,
        "top_scorers": [],
        "transfers_in": [],
        "freshman_impact": [],
        "coach": "Unknown",
        "coach_tenure": 0,
        "new_coach": False,
    }

    # Try ESPN roster for coach info
    if team_id:
        try:
            url = f"{ESPN_CBB_BASE}/teams/{team_id}/roster"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                coach_list = data.get("coach", [])
                if coach_list:
                    c = coach_list[0] if isinstance(coach_list, list) else coach_list
                    result["coach"] = c.get("firstName", "") + " " + c.get("lastName", "")

                # Extract top players from roster
                athletes = data.get("athletes", [])
                for a in sorted(athletes, key=lambda x: x.get("id", 0))[:5]:
                    result["top_scorers"].append({
                        "name": a.get("displayName", ""),
                        "position": a.get("position", {}).get("abbreviation", ""),
                    })
        except Exception as e:
            logger.warning("ESPN roster fetch failed for %s: %s", team_name, e)

    # Try CBBData for player stats
    if CBBDATA_API_KEY and season:
        try:
            url = f"{CBBDATA_BASE}/torvik/player/season"
            params = {"year": season, "team": team_name, "key": CBBDATA_API_KEY}
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                players = resp.json()
                # Sort by PPG or minutes
                players_sorted = sorted(players, key=lambda p: p.get("ppg", 0), reverse=True)
                result["top_scorers"] = [
                    {
                        "name": p.get("player", ""),
                        "ppg": p.get("ppg", 0),
                        "rpg": p.get("rpg", 0),
                        "apg": p.get("apg", 0),
                        "efg": p.get("efg", 0),
                        "mpg": p.get("mpg", 0),
                    }
                    for p in players_sorted[:5]
                ]
        except Exception as e:
            logger.warning("CBBData player stats fetch failed for %s: %s", team_name, e)

    return result
