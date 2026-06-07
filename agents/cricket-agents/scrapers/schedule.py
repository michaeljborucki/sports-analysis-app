"""Match schedule scraper using CricketData.org API."""
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE, LEAGUES, TEAM_NAME_TO_ABBREV

log = logging.getLogger(__name__)


@dataclass
class MatchInfo:
    match_id: str
    team_a: str          # abbreviation
    team_b: str          # abbreviation
    team_a_full: str     # full team name
    team_b_full: str     # full team name
    league: Optional[str]
    venue: str
    date: str            # YYYY-MM-DD
    datetime_gmt: str    # ISO datetime string
    status: str


def _resolve_team(name: str) -> str:
    """Return the abbreviation for *name*, or *name* itself if unknown."""
    return TEAM_NAME_TO_ABBREV.get(name, name)


def _detect_league(team_a_full: str, team_b_full: str) -> Optional[str]:
    """Return the league key if both teams belong to the same league, else None."""
    for league_key, cfg in LEAGUES.items():
        team_names = set(cfg["team_names"].keys())
        if team_a_full in team_names and team_b_full in team_names:
            return league_key
    return None


def get_upcoming_matches(league: Optional[str] = None) -> list[MatchInfo]:
    """Fetch upcoming T20 matches from the CricketData.org API.

    Parameters
    ----------
    league:
        Optional league key (e.g. ``"ipl"``). When provided only matches for
        that league are returned.

    Returns
    -------
    list[MatchInfo]
        A list of upcoming T20 matches, filtered by *league* if given.
    """
    url = f"{CRICKET_API_BASE}/matches"
    params = {"apikey": CRICKET_API_KEY}

    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    matches: list[MatchInfo] = []
    for raw in data.get("data", []):
        # Only process T20 format matches
        if raw.get("matchType", "").lower() != "t20":
            continue

        teams = raw.get("teams", [])
        team_a_full = teams[0] if len(teams) > 0 else ""
        team_b_full = teams[1] if len(teams) > 1 else ""

        # Prefer shortname from teamInfo when available; fall back to TEAM_NAME_TO_ABBREV
        team_info = raw.get("teamInfo", [])
        if len(team_info) >= 2:
            team_a = team_info[0].get("shortname") or _resolve_team(team_a_full)
            team_b = team_info[1].get("shortname") or _resolve_team(team_b_full)
            # Override with our canonical abbreviation if we know the team
            team_a = TEAM_NAME_TO_ABBREV.get(team_a_full, team_a)
            team_b = TEAM_NAME_TO_ABBREV.get(team_b_full, team_b)
        else:
            team_a = _resolve_team(team_a_full)
            team_b = _resolve_team(team_b_full)

        detected_league = _detect_league(team_a_full, team_b_full)

        # Filter by requested league
        if league is not None and detected_league != league:
            continue

        match = MatchInfo(
            match_id=raw.get("id", ""),
            team_a=team_a,
            team_b=team_b,
            team_a_full=team_a_full,
            team_b_full=team_b_full,
            league=detected_league,
            venue=raw.get("venue", ""),
            date=raw.get("date", ""),
            datetime_gmt=raw.get("dateTimeGMT", ""),
            status=raw.get("status", ""),
        )
        matches.append(match)

    return matches
