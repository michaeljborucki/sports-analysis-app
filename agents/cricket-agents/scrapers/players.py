"""Cricket player profiles scraper using CricketData.org API."""
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE

log = logging.getLogger(__name__)


@dataclass
class PlayerProfile:
    player_id: str
    name: str
    role: str                       # batsman / bowler / all-rounder / keeper
    batting_style: str
    bowling_style: str
    batting_avg: float
    batting_sr: float               # strike rate
    tournament_runs: int
    bowling_econ: float
    bowling_avg: float
    tournament_wickets: int
    recent_form: list = field(default_factory=list)   # e.g. ["50", "32", "2W"]
    venue_record: str = ""


def get_key_players(team: str, league: str, limit: int = 6) -> list[PlayerProfile]:
    """Fetch key player profiles for a team from the CricketData.org API.

    Parameters
    ----------
    team:
        Team abbreviation, e.g. ``"CSK"``.
    league:
        League key, e.g. ``"ipl"``.
    limit:
        Maximum number of player profiles to return (default 6).

    Returns
    -------
    list[PlayerProfile]
        Up to *limit* parsed player profiles; empty list if none found.
    """
    url = f"{CRICKET_API_BASE}/players"
    params = {"apikey": CRICKET_API_KEY, "team": team, "league": league}

    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    profiles: list[PlayerProfile] = []
    for entry in data.get("data", []):
        profile = PlayerProfile(
            player_id=entry.get("id", ""),
            name=entry.get("name", ""),
            role=entry.get("role", ""),
            batting_style=entry.get("batting_style", ""),
            bowling_style=entry.get("bowling_style", ""),
            batting_avg=float(entry.get("batting_avg", 0.0)),
            batting_sr=float(entry.get("batting_sr", 0.0)),
            tournament_runs=int(entry.get("tournament_runs", 0)),
            bowling_econ=float(entry.get("bowling_econ", 0.0)),
            bowling_avg=float(entry.get("bowling_avg", 0.0)),
            tournament_wickets=int(entry.get("tournament_wickets", 0)),
            recent_form=list(entry.get("recent_form", [])),
            venue_record=entry.get("venue_record", ""),
        )
        profiles.append(profile)
        if len(profiles) >= limit:
            break

    log.debug(
        "Fetched %d player(s) for team='%s' league='%s' (limit=%d).",
        len(profiles), team, league, limit,
    )
    return profiles
