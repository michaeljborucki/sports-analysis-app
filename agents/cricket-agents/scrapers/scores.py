"""Cricket match results scraper using CricketData.org API."""
import logging
from dataclasses import dataclass
from datetime import date

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE, TEAM_NAME_TO_ABBREV

logger = logging.getLogger("cricket.scrapers.scores")


@dataclass
class MatchResult:
    match_id: str
    team_a: str           # abbreviation (first team listed)
    team_b: str           # abbreviation (second team listed)
    team_a_full: str      # full name
    team_b_full: str      # full name
    winner: str           # abbreviation of winner
    team_a_score: int
    team_a_wickets: int
    team_a_overs: float
    team_b_score: int
    team_b_wickets: int
    team_b_overs: float
    total_runs: int
    toss_winner: str      # abbreviation
    toss_decision: str    # "bat" or "field"
    dls_applied: bool
    status: str           # raw status string from API


def _team_abbrev(full_name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(full_name, full_name)


def _parse_winner(status: str, team_a_full: str, team_b_full: str) -> str:
    """Extract winner abbreviation from status string like 'Mumbai Indians won by 15 runs'."""
    status_lower = status.lower()

    for full_name in [team_a_full, team_b_full]:
        if full_name.lower() in status_lower:
            return _team_abbrev(full_name)

    # Fallback: scan TEAM_NAME_TO_ABBREV for any team name in status
    for full_name, abbrev in TEAM_NAME_TO_ABBREV.items():
        if full_name.lower() in status_lower:
            return abbrev

    return ""


def get_final_scores(date: str = None) -> list[MatchResult]:
    """Fetch completed T20 match results from CricketData.org.

    Args:
        date: ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        List of MatchResult for completed T20 matches.
    """
    if date is None:
        from datetime import date as date_mod
        date = date_mod.today().isoformat()

    url = f"{CRICKET_API_BASE}/matches"
    params = {
        "apikey": CRICKET_API_KEY,
        "date": date,
        "offset": 0,
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    matches_data = payload.get("data", [])
    logger.info("[scores] %d total matches fetched for %s", len(matches_data), date)

    results = []
    for match in matches_data:
        # Filter: T20 only
        if match.get("matchType", "").lower() != "t20":
            continue

        status = match.get("status", "")
        status_lower = status.lower()

        # Filter: completed matches (won or tied)
        if "won" not in status_lower and "tied" not in status_lower:
            continue

        teams = match.get("teams", [])
        if len(teams) < 2:
            logger.warning("[scores] Match %s has fewer than 2 teams, skipping", match.get("id"))
            continue

        team_a_full = teams[0]
        team_b_full = teams[1]
        team_a = _team_abbrev(team_a_full)
        team_b = _team_abbrev(team_b_full)

        # Parse innings scores
        innings = match.get("score", [])
        team_a_score = team_a_wickets = team_b_score = team_b_wickets = 0
        team_a_overs = team_b_overs = 0.0

        # Match innings to teams by inning label
        for inning in innings:
            inning_label = inning.get("inning", "").lower()
            runs = inning.get("r", 0)
            wickets = inning.get("w", 0)
            overs = float(inning.get("o", 0))

            if team_a_full.lower() in inning_label:
                team_a_score = runs
                team_a_wickets = wickets
                team_a_overs = overs
            elif team_b_full.lower() in inning_label:
                team_b_score = runs
                team_b_wickets = wickets
                team_b_overs = overs

        # Winner
        if "tied" in status_lower:
            winner = "tied"
        else:
            winner = _parse_winner(status, team_a_full, team_b_full)

        # Toss
        toss_winner_full = match.get("tossWinner", "")
        toss_winner = _team_abbrev(toss_winner_full)
        toss_decision = match.get("tossChoice", "bat")

        # DLS detection
        dls_applied = "dls" in status_lower or "d/l" in status_lower

        results.append(MatchResult(
            match_id=match.get("id", ""),
            team_a=team_a,
            team_b=team_b,
            team_a_full=team_a_full,
            team_b_full=team_b_full,
            winner=winner,
            team_a_score=team_a_score,
            team_a_wickets=team_a_wickets,
            team_a_overs=team_a_overs,
            team_b_score=team_b_score,
            team_b_wickets=team_b_wickets,
            team_b_overs=team_b_overs,
            total_runs=team_a_score + team_b_score,
            toss_winner=toss_winner,
            toss_decision=toss_decision,
            dls_applied=dls_applied,
            status=status,
        ))

    logger.info("[scores] %d completed T20 matches parsed", len(results))
    return results
