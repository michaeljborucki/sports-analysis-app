"""Fetch soccer team season stats from ESPN standings API."""
import logging
import requests

logger = logging.getLogger("mirofish.scrapers.team_stats")

LEAGUE_SLUGS = {
    "MLS": "usa.1",
    "Eredivisie": "ned.1",
    "Serie A": "ita.1",
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "La Liga": "esp.1",
    "Ligue 1": "fra.1",
}

STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/soccer"

# Cache standings per league to avoid repeated API calls within a pipeline run
_standings_cache: dict[str, list[dict]] = {}


def _find_stat(stats: list[dict], name: str, default=0):
    for s in stats:
        if s.get("name") == name:
            val = s.get("value", default)
            return val if val is not None else default
    return default


def _load_standings(league: str) -> list[dict]:
    """Fetch and cache league standings."""
    if league in _standings_cache:
        return _standings_cache[league]

    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"{STANDINGS_BASE}/{slug}/standings"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("ESPN standings error for %s: %s", league, e)
        _standings_cache[league] = []
        return []

    entries = []
    for child in data.get("children", []):
        entries.extend(child.get("standings", {}).get("entries", []))

    _standings_cache[league] = entries
    logger.info("[team_stats] %s: loaded %d teams from standings", league, len(entries))
    return entries


def get_team_profile(team_name: str, league: str = "MLS") -> dict:
    """Fetch team record and stats from standings."""
    entries = _load_standings(league)

    for entry in entries:
        team_data = entry.get("team", {})
        if team_data.get("displayName") == team_name:
            stats = entry.get("stats", [])

            wins = int(_find_stat(stats, "wins"))
            draws = int(_find_stat(stats, "ties"))
            losses = int(_find_stat(stats, "losses"))
            gf = int(_find_stat(stats, "pointsFor"))
            ga = int(_find_stat(stats, "pointsAgainst"))
            pts = int(_find_stat(stats, "points"))
            gp = int(_find_stat(stats, "gamesPlayed"))
            rank = int(_find_stat(stats, "rank"))

            return {
                "team": team_name,
                "record": f"{wins}W-{draws}D-{losses}L",
                "points": pts,
                "goals_for": gf,
                "goals_against": ga,
                "goal_diff": gf - ga,
                "games_played": gp,
                "standing": f"{rank}{'st' if rank == 1 else 'nd' if rank == 2 else 'rd' if rank == 3 else 'th'} in {league}",
            }

    logger.warning("Team not found: %s in %s", team_name, league)
    return {"team": team_name, "record": "", "points": 0,
            "goals_for": 0, "goals_against": 0, "goal_diff": 0,
            "games_played": 0, "standing": ""}


def get_recent_form(team_name: str, league: str = "MLS", n: int = 5) -> dict:
    """Fetch recent form (last N results) for a team.

    Returns dict with: form_string (e.g., "WWDLW"), wins, draws, losses,
    goals_scored, goals_conceded, ppg (points per game over stretch).
    """
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("ESPN teams error: %s", e)
        return _default_form(team_name)

    # Find team ID
    team_id = None
    for group in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = group.get("team", {})
        if t.get("displayName") == team_name:
            team_id = t.get("id")
            break

    if not team_id:
        logger.warning("Team not found for form: %s", team_name)
        return _default_form(team_name)

    # Fetch team results (no season filter — let ESPN return the current season)
    results_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule"
    try:
        resp = requests.get(results_url, timeout=15)
        resp.raise_for_status()
        schedule = resp.json()
    except Exception as e:
        logger.error("ESPN schedule error for %s: %s", team_name, e)
        return _default_form(team_name)

    # Parse completed events
    completed = []
    for event in schedule.get("events", []):
        status = event.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("name", "")
        if status in ("STATUS_FINAL", "STATUS_FULL_TIME"):
            comp = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])

            our_score = opp_score = 0
            is_home = False
            for c in competitors:
                raw_score = c.get("score", 0)
                if isinstance(raw_score, dict):
                    score = int(float(raw_score.get("value", 0)))
                else:
                    score = int(float(raw_score))
                team_info = c.get("team", {})
                if team_info.get("id") == str(team_id) or team_info.get("displayName") == team_name:
                    our_score = score
                    is_home = c.get("homeAway") == "home"
                else:
                    opp_score = score

            if our_score > opp_score:
                result = "W"
            elif our_score < opp_score:
                result = "L"
            else:
                result = "D"

            completed.append({
                "result": result,
                "our_score": our_score,
                "opp_score": opp_score,
                "home": is_home,
            })

    # Take last N
    recent = completed[-n:]
    if not recent:
        return _default_form(team_name)

    form_string = "".join(r["result"] for r in recent)
    wins = sum(1 for r in recent if r["result"] == "W")
    draws = sum(1 for r in recent if r["result"] == "D")
    losses = sum(1 for r in recent if r["result"] == "L")
    gs = sum(r["our_score"] for r in recent)
    gc = sum(r["opp_score"] for r in recent)
    ppg = (wins * 3 + draws) / len(recent)

    # Home/away splits from ALL completed matches
    home_matches = [r for r in completed if r.get("home")]
    away_matches = [r for r in completed if not r.get("home")]

    home_wins = sum(1 for r in home_matches if r["result"] == "W")
    home_draws = sum(1 for r in home_matches if r["result"] == "D")
    home_losses = sum(1 for r in home_matches if r["result"] == "L")
    home_gf = sum(r["our_score"] for r in home_matches) if home_matches else 0
    home_ga = sum(r["opp_score"] for r in home_matches) if home_matches else 0

    away_wins = sum(1 for r in away_matches if r["result"] == "W")
    away_draws = sum(1 for r in away_matches if r["result"] == "D")
    away_losses = sum(1 for r in away_matches if r["result"] == "L")
    away_gf = sum(r["our_score"] for r in away_matches) if away_matches else 0
    away_ga = sum(r["opp_score"] for r in away_matches) if away_matches else 0

    return {
        "team": team_name,
        "form": form_string,
        "last_5_ppg": round(ppg, 2),
        "last_5_wins": wins,
        "last_5_draws": draws,
        "last_5_losses": losses,
        "last_5_gf": gs,
        "last_5_gc": gc,
        "home_record": f"{home_wins}W-{home_draws}D-{home_losses}L",
        "home_gf": home_gf,
        "home_ga": home_ga,
        "away_record": f"{away_wins}W-{away_draws}D-{away_losses}L",
        "away_gf": away_gf,
        "away_ga": away_ga,
    }


def _default_form(team_name: str) -> dict:
    return {
        "team": team_name,
        "form": "",
        "last_5_ppg": 0.0,
        "last_5_wins": 0, "last_5_draws": 0, "last_5_losses": 0,
        "last_5_gf": 0, "last_5_gc": 0,
        "home_record": "", "home_gf": 0, "home_ga": 0,
        "away_record": "", "away_gf": 0, "away_ga": 0,
    }
