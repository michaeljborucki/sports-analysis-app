"""Fetch player box scores for prop grading via nba_api V3."""
import json
import logging
from difflib import SequenceMatcher

from nba_api.stats.library.http import NBAStatsHTTP

logger = logging.getLogger("mirofish.scrapers.player_stats")


def get_player_box_scores(game_id: str) -> list[dict]:
    """Fetch player stats for a completed game using V3 endpoint (raw request)."""
    try:
        http = NBAStatsHTTP()
        resp = http.send_api_request(
            endpoint="boxscoretraditionalv3",
            parameters={"GameID": game_id, "LeagueID": "00"},
            timeout=30,
        )
        raw = resp.get_response()
        data = json.loads(raw) if isinstance(raw, str) else raw
        bs = data.get("boxScoreTraditional", {})

        players = []
        for team_key in ("homeTeam", "awayTeam"):
            team = bs.get(team_key, {})
            team_abbrev = team.get("teamTricode", "")
            for p in team.get("players", []):
                s = p.get("statistics", {})
                name = f"{p.get('firstName', '')} {p.get('familyName', '')}"
                pts = int(s.get("points", 0))
                reb = int(s.get("reboundsTotal", 0))
                ast = int(s.get("assists", 0))
                threes = int(s.get("threePointersMade", 0))
                players.append({
                    "player": name,
                    "team": team_abbrev,
                    "minutes": s.get("minutes", "0"),
                    "points": pts,
                    "rebounds": reb,
                    "assists": ast,
                    "threes": threes,
                    "pra": pts + reb + ast,
                })
        return players
    except Exception as e:
        logger.error("Failed to fetch box scores for %s: %s", game_id, e)
        return []


def find_player(name: str, box_scores: list[dict], threshold: float = 0.6) -> dict | None:
    """Find a player in box scores using fuzzy matching.

    Matching priority:
    1. Exact match
    2. Last-name exact match (single result)
    3. Best fuzzy match above threshold
    """
    if not name or not box_scores:
        return None

    # Exact match
    for ps in box_scores:
        if ps["player"] == name:
            return ps

    # Last-name exact match
    last_name = name.split()[-1].lower()
    last_matches = [ps for ps in box_scores if ps["player"].split()[-1].lower() == last_name]
    if len(last_matches) == 1:
        return last_matches[0]

    # Fuzzy match using SequenceMatcher
    best_score = 0.0
    best_match = None
    name_lower = name.lower()
    for ps in box_scores:
        score = SequenceMatcher(None, name_lower, ps["player"].lower()).ratio()
        if score > best_score:
            best_score = score
            best_match = ps

    if best_score >= threshold:
        return best_match

    return None
