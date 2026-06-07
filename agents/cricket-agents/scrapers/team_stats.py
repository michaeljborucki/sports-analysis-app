"""Cricket team stats scraper using CricketData.org API."""
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE

log = logging.getLogger(__name__)


@dataclass
class TeamProfile:
    team: str                       # abbreviation, e.g. "CSK"
    league: str                     # league key, e.g. "ipl"
    matches: int = 0
    won: int = 0
    lost: int = 0
    no_result: int = 0
    win_rate: float = 0.0           # won / matches (0 when matches == 0)
    bat_first_wins: int = 0
    chase_wins: int = 0
    avg_score_bat_first: float = 0.0
    avg_score_chasing: float = 0.0
    nrr: float = 0.0                # Net Run Rate
    standing: Optional[int] = None  # current table position
    last_5: list = field(default_factory=list)  # e.g. ["W","W","L","W","W"]
    powerplay_run_rate: float = 0.0
    death_overs_economy: float = 0.0


def get_team_profile(team: str, league: str) -> Optional[TeamProfile]:
    """Fetch team stats from the CricketData.org API.

    Parameters
    ----------
    team:
        Team abbreviation, e.g. ``"CSK"``.
    league:
        League key, e.g. ``"ipl"``.

    Returns
    -------
    TeamProfile | None
        Parsed profile, or ``None`` if the team was not found in the response.
    """
    url = f"{CRICKET_API_BASE}/teams"
    params = {"apikey": CRICKET_API_KEY}

    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    for entry in data.get("data", []):
        shortname = entry.get("shortname", "")
        if shortname != team:
            continue

        matches = int(entry.get("matches", 0))
        won = int(entry.get("won", 0))
        lost = int(entry.get("lost", 0))
        win_rate = won / matches if matches > 0 else 0.0

        return TeamProfile(
            team=team,
            league=league,
            matches=matches,
            won=won,
            lost=lost,
            no_result=int(entry.get("no_result", 0)),
            win_rate=win_rate,
            bat_first_wins=int(entry.get("bat_first_wins", 0)),
            chase_wins=int(entry.get("chase_wins", 0)),
            avg_score_bat_first=float(entry.get("avg_score_bat_first", 0.0)),
            avg_score_chasing=float(entry.get("avg_score_chasing", 0.0)),
            nrr=float(entry.get("nrr", 0.0)),
            standing=entry.get("standing"),
            last_5=list(entry.get("last_5", [])),
            powerplay_run_rate=float(entry.get("powerplay_run_rate", 0.0)),
            death_overs_economy=float(entry.get("death_overs_economy", 0.0)),
        )

    log.debug("Team '%s' not found in league '%s' response.", team, league)
    return None
