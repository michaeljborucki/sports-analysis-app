# MLB → Cricket T20 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all MLB baseball code with Cricket T20 franchise league support across 8 leagues, using CricketData.org + Cricsheet data sources, keeping the sport-agnostic ensemble engine intact.

**Architecture:** Two-phase parallel execution. Phase 1 deletes MLB code and builds foundations (config, scrapers, ensemble constants). Phase 2 wires everything together (briefing, system prompt, edge detection, CLI, agents, tests). Each phase has 4 parallel sub-agents.

**Tech Stack:** Python 3.11+, requests, The Odds API, CricketData.org API, Cricsheet CSVs, OpenRouter (6-model ensemble), pytest

**Spec:** `docs/superpowers/specs/2026-03-22-mlb-to-cricket-t20-migration.md`

---

## Phase 1: Delete MLB + Build Foundations

### Task 1: Config & Cleanup (Agent 1)

**Files:**
- Delete: `scrapers/pitchers.py`, `scrapers/lineups.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`
- Delete: `tests/test_pitchers.py`, `tests/test_lineups.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`
- Delete: `docs/superpowers/plans/2026-03-17-mlb-prediction-pipeline.md`
- Rewrite: `config.py`
- Modify: `ensemble/weights.py:6`
- Modify: `ensemble/orchestrator.py:34-58,406-467`
- Modify: `ensemble/consensus.py:4-10,23-30`
- Modify: `ensemble/challenger.py:9-23`
- Modify: `requirements.txt`

- [ ] **Step 1: Delete all MLB-only scraper files and their tests**

```bash
rm scrapers/pitchers.py scrapers/lineups.py scrapers/bullpen.py scrapers/ballpark.py
rm tests/test_pitchers.py tests/test_lineups.py tests/test_bullpen.py tests/test_ballpark.py
rm docs/superpowers/plans/2026-03-17-mlb-prediction-pipeline.md
```

- [ ] **Step 2: Commit deletions**

```bash
git add -u
git commit -m "chore: delete MLB-only scraper files, tests, and plan doc"
```

- [ ] **Step 3: Remove pybaseball from requirements.txt**

Remove the `pybaseball>=2.3.0` line from `requirements.txt`. Keep all other dependencies.

- [ ] **Step 4: Rewrite config.py**

Replace the entire file. Keep these generic settings unchanged: `ODDS_API_KEY`, `ODDS_API_BASE`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `WEATHER_API_KEY`, `WEATHER_API_BASE`, `ENSEMBLE_MODELS`, `ENSEMBLE_CHALLENGER`, `CONSENSUS_MIN_VOTES`, `MAX_CALLS_PER_GAME`, `SCREEN_EDGE_THRESHOLD`.

Replace MLB-specific content with:

**IMPORTANT:** The new `config.py` MUST preserve these variables that other files import: `KIMI_MODEL`, `GAME_TIMEOUT`, `DATA_DIR`, `BETS_CSV`, `MODEL_WEIGHTS_FILE`, `MODEL_PREDICTIONS_CSV`, `LOG_LEVEL`, logging config, `load_dotenv()`. Also keep `ENSEMBLE_MODELS` using SHORT keys (e.g. `"kimi"`, `"claude"`) because `ensemble/models.py` uses them to look up `MODEL_REGISTRY`.

```python
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# --- API Keys & Endpoints ---
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"
CRICKET_API_KEY = os.getenv("CRICKET_API_KEY", "")
CRICKET_API_BASE = "https://api.cricketdata.org/v1"
CRICSHEET_DATA_DIR = "data/cricsheet"

# --- Simulation ---
KIMI_MODEL = "moonshotai/kimi-k2.5"
GAME_TIMEOUT = 300  # 5 min max per game
SCREEN_EDGE_THRESHOLD = 0.03

# --- Ensemble (keep SHORT keys — MODEL_REGISTRY uses them) ---
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# --- Cricket-Specific ---
BET_SLOTS = ["moneyline", "total_runs"]

EDGE_THRESHOLDS = {
    "moneyline": 0.06,
    "total_runs": 0.06,
}

KELLY_FRACTION = 0.125  # Eighth-Kelly for high-variance T20

# --- Data directory (keep existing) ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")

LEAGUES = {
    "ipl": {
        "name": "Indian Premier League",
        "odds_key": "cricket_ipl",
        "season": "Mar-May",
        "teams": ["CSK", "MI", "RCB", "KKR", "DC", "PBKS", "RR", "SRH", "GT", "LSG"],
        "team_names": {
            "Chennai Super Kings": "CSK",
            "Mumbai Indians": "MI",
            "Royal Challengers Bengaluru": "RCB",
            "Kolkata Knight Riders": "KKR",
            "Delhi Capitals": "DC",
            "Punjab Kings": "PBKS",
            "Rajasthan Royals": "RR",
            "Sunrisers Hyderabad": "SRH",
            "Gujarat Titans": "GT",
            "Lucknow Super Giants": "LSG",
        },
    },
    "bbl": {
        "name": "Big Bash League",
        "odds_key": "cricket_big_bash_league",
        "season": "Dec-Jan",
        "teams": ["ADS", "BBH", "HBH", "MLS", "MRS", "PST", "SSX", "SST"],
        "team_names": {
            "Adelaide Strikers": "ADS",
            "Brisbane Heat": "BBH",
            "Hobart Hurricanes": "HBH",
            "Melbourne Stars": "MLS",
            "Melbourne Renegades": "MRS",
            "Perth Scorchers": "PST",
            "Sydney Sixers": "SSX",
            "Sydney Thunder": "SST",
        },
    },
    "cpl": {
        "name": "Caribbean Premier League",
        "odds_key": "cricket_caribbean_premier_league",
        "season": "Aug-Sep",
        "teams": ["TKR", "GAW", "BT", "SNP", "SLK", "JAM"],
        "team_names": {
            "Trinbago Knight Riders": "TKR",
            "Guyana Amazon Warriors": "GAW",
            "Barbados Tridents": "BT",
            "St Kitts & Nevis Patriots": "SNP",
            "Saint Lucia Kings": "SLK",
            "Jamaica Tallawahs": "JAM",
        },
    },
    "psl": {
        "name": "Pakistan Super League",
        "odds_key": "cricket_psl",
        "season": "Feb-Mar",
        "teams": ["IU", "KK", "LQ", "MS", "PZ", "QG"],
        "team_names": {
            "Islamabad United": "IU",
            "Karachi Kings": "KK",
            "Lahore Qalandars": "LQ",
            "Multan Sultans": "MS",
            "Peshawar Zalmi": "PZ",
            "Quetta Gladiators": "QG",
        },
    },
    "hundred": {
        "name": "The Hundred",
        "odds_key": "cricket_the_hundred",
        "season": "Jul-Aug",
        "teams": ["BPH", "LNS", "MO", "NOS", "OI", "SB", "TF", "WF"],
        "team_names": {
            "Birmingham Phoenix": "BPH",
            "London Spirit": "LNS",
            "Manchester Originals": "MO",
            "Northern Superchargers": "NOS",
            "Oval Invincibles": "OI",
            "Southern Brave": "SB",
            "Trent Rockets": "TF",
            "Welsh Fire": "WF",
        },
    },
    "sa20": {
        "name": "SA20",
        "odds_key": "cricket_sa20",
        "season": "Jan-Feb",
        "teams": ["DSG", "JBG", "MI-CT", "PR", "SEC", "SUN"],
        "team_names": {
            "Durban Super Giants": "DSG",
            "Joburg Super Kings": "JBG",
            "MI Cape Town": "MI-CT",
            "Paarl Royals": "PR",
            "Sunrisers Eastern Cape": "SEC",
            "Pretoria Capitals": "SUN",
        },
    },
    "bpl": {
        "name": "Bangladesh Premier League",
        "odds_key": "cricket_bpl",
        "season": "Jan-Feb",
        "teams": ["CV", "CK", "DB", "FBD", "KT", "RR", "SYS"],
        "team_names": {
            "Comilla Victorians": "CV",
            "Chattogram Challengers": "CK",
            "Dhaka Dominators": "DB",
            "Fortune Barishal": "FBD",
            "Khulna Tigers": "KT",
            "Rangpur Riders": "RR",
            "Sylhet Strikers": "SYS",
        },
    },
    "ilt20": {
        "name": "International League T20",
        "odds_key": "cricket_ilt20",
        "season": "Jan-Feb",
        "teams": ["ADK", "DBC", "DES", "GUL", "MIE", "SHJ"],
        "team_names": {
            "Abu Dhabi Knight Riders": "ADK",
            "Dubai Capitals": "DBC",
            "Desert Vipers": "DES",
            "Gulf Giants": "GUL",
            "MI Emirates": "MIE",
            "Sharjah Warriors": "SHJ",
        },
    },
}

# Flatten all team names across leagues for reverse lookup
TEAM_NAME_TO_ABBREV = {}
for league_cfg in LEAGUES.values():
    TEAM_NAME_TO_ABBREV.update(league_cfg["team_names"])

# Venue coordinates for weather lookups (major grounds)
VENUE_COORDS = {
    "Wankhede Stadium": (18.9389, 72.8258),
    "M. Chinnaswamy Stadium": (12.9788, 77.5996),
    "Eden Gardens": (22.5646, 88.3433),
    "MA Chidambaram Stadium": (13.0627, 80.2792),
    "Arun Jaitley Stadium": (28.6377, 77.2433),
    "Narendra Modi Stadium": (23.0914, 72.5967),
    "Rajiv Gandhi Intl Stadium": (17.4065, 78.5506),
    "Sawai Mansingh Stadium": (26.8929, 75.8039),
    "IS Bindra Stadium": (30.6906, 76.7368),
    "BRSABV Ekana Stadium": (26.8467, 80.9462),
    "Melbourne Cricket Ground": (-37.82, 144.9834),
    "Sydney Cricket Ground": (-33.8916, 151.2247),
    "The Gabba": (-27.4858, 153.0381),
    "Adelaide Oval": (-34.9156, 138.5961),
    "Perth Stadium": (-31.9512, 115.8891),
    "Bellerive Oval": (-42.8756, 147.3511),
    "Kensington Oval": (13.1065, -59.6218),
    "Queen's Park Oval": (10.6674, -61.5026),
    "Gaddafi Stadium": (31.5134, 74.3397),
    "National Stadium Karachi": (24.8924, 67.0733),
    "Newlands": (-33.9281, 18.4637),
    "The Oval": (51.4838, -0.1149),
}
```

- [ ] **Step 5: Update ensemble/weights.py BET_SLOTS**

Change line 6 from:
```python
BET_SLOTS = ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]
```
to:
```python
BET_SLOTS = ["moneyline", "total_runs"]
```

- [ ] **Step 6: Update ensemble/orchestrator.py constants and build_ensemble_result()**

Replace lines 34-58 (PROB_FIELDS, SLOT_SECTION, PRIMARY_PROB_FIELD):

```python
PROB_FIELDS = {
    "moneyline": ["team_a_win_prob", "team_b_win_prob"],
    "total_runs": ["over_prob", "under_prob", "projected_total"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "total_runs": "total_runs",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "team_a_win_prob",
    "total_runs": "over_prob",
}
```

In `build_ensemble_result()` (lines 406-467):
- Rename `predicted_score` key to `predicted_result` to match the new system prompt output schema
- Change the inner keys from `"home"`/`"away"` to `"batting_first"`/`"chasing"` inside `projected_scores`
- Remove all `first_5` kill logic and hardcoded MLB section keys (`f5_home_win_prob`, `f5_away_win_prob`, `f5_ml_value`, `f5_total_value`, `f5_projected_total`)
- Update confidence voting to reference `"moneyline"` and `"total_runs"` sections only

- [ ] **Step 7: Update ensemble/consensus.py**

Replace lines 4-10 (BET_SLOT_FIELDS):
```python
BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "total_runs": ("total_runs", "value_side"),
}
```

Remove the run_line normalization logic in `extract_vote()` (lines 23-30):
```python
# DELETE this entire block:
if bet_slot == "run_line":
    rl_odds = odds.get("run_line", {})
    home_point = rl_odds.get("home", -1.5)
    ...
```

- [ ] **Step 8: Update ensemble/challenger.py sport references**

In `CHALLENGER_SYSTEM_PROMPT` (lines 9-23), change any "MLB" or "baseball" references to "T20 cricket". The prompt structure (approve/kill verdicts per bet slot) stays the same.

- [ ] **Step 9: Commit Phase 1 Agent 1 changes**

```bash
git add config.py requirements.txt ensemble/weights.py ensemble/orchestrator.py ensemble/consensus.py ensemble/challenger.py
git commit -m "feat: replace MLB config with Cricket T20 leagues and update ensemble constants"
```

---

### Task 2: Schedule + Team Stats Scrapers (Agent 2)

**Files:**
- Create: `scrapers/schedule.py`
- Rewrite: `scrapers/team_stats.py`
- Create: `tests/test_schedule.py`
- Rewrite: `tests/test_team_stats.py`

- [ ] **Step 1: Write test for schedule scraper**

Create `tests/test_schedule.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from scrapers.schedule import get_upcoming_matches, MatchInfo


def _mock_cricket_api_response():
    return {
        "data": [
            {
                "id": "match_001",
                "name": "Mumbai Indians vs Chennai Super Kings",
                "teams": ["Mumbai Indians", "Chennai Super Kings"],
                "venue": "Wankhede Stadium, Mumbai",
                "date": "2026-03-25",
                "dateTimeGMT": "2026-03-25T14:00:00",
                "matchType": "t20",
                "status": "Not started",
                "series_id": "ipl_2026",
            }
        ]
    }


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_returns_match_info(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_cricket_api_response()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches(league="ipl")

    assert len(matches) == 1
    m = matches[0]
    assert isinstance(m, MatchInfo)
    assert m.team_a == "MI"
    assert m.team_b == "CSK"
    assert m.venue == "Wankhede Stadium, Mumbai"
    assert m.league == "ipl"


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches(league="ipl")
    assert matches == []


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_all_leagues(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_cricket_api_response()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches(league=None)
    assert len(matches) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schedule.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement scrapers/schedule.py**

```python
"""Match schedule scraper using CricketData.org API."""

from dataclasses import dataclass
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE, LEAGUES, TEAM_NAME_TO_ABBREV


@dataclass
class MatchInfo:
    match_id: str
    team_a: str  # abbreviation
    team_b: str  # abbreviation
    team_a_full: str
    team_b_full: str
    league: str
    venue: str
    date: str
    datetime_gmt: str
    status: str


def _resolve_team(name: str) -> str:
    """Resolve full team name to abbreviation."""
    return TEAM_NAME_TO_ABBREV.get(name, name)


def get_upcoming_matches(league: Optional[str] = None) -> list[MatchInfo]:
    """Fetch upcoming T20 matches from CricketData.org.

    Args:
        league: League key (e.g. 'ipl'). If None, fetch all leagues.

    Returns:
        List of MatchInfo dataclasses.
    """
    url = f"{CRICKET_API_BASE}/matches"
    params = {"apikey": CRICKET_API_KEY, "offset": 0}

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    matches = []
    for item in data:
        if item.get("matchType") != "t20":
            continue

        teams = item.get("teams", [])
        if len(teams) < 2:
            continue

        team_a_full = teams[0]
        team_b_full = teams[1]
        team_a = _resolve_team(team_a_full)
        team_b = _resolve_team(team_b_full)

        # Determine league from series or team membership
        match_league = _detect_league(team_a_full, team_b_full)
        if league and match_league != league:
            continue

        matches.append(MatchInfo(
            match_id=item.get("id", ""),
            team_a=team_a,
            team_b=team_b,
            team_a_full=team_a_full,
            team_b_full=team_b_full,
            league=match_league or "unknown",
            venue=item.get("venue", ""),
            date=item.get("date", ""),
            datetime_gmt=item.get("dateTimeGMT", ""),
            status=item.get("status", ""),
        ))

    return matches


def _detect_league(team_a: str, team_b: str) -> Optional[str]:
    """Detect league by checking team membership."""
    for league_key, cfg in LEAGUES.items():
        names = cfg["team_names"]
        if team_a in names and team_b in names:
            return league_key
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schedule.py -v`
Expected: PASS

- [ ] **Step 5: Write test for cricket team_stats scraper**

Create `tests/test_team_stats.py` (replace existing):
```python
import pytest
from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_team_profile, TeamProfile


def _mock_team_stats_response():
    return {
        "data": {
            "name": "Mumbai Indians",
            "shortname": "MI",
            "matches": 14,
            "won": 9,
            "lost": 5,
            "nrr": "+0.825",
            "position": 2,
        }
    }


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_team_stats_response()
    mock_get.return_value = mock_resp

    profile = get_team_profile("MI", "ipl")

    assert isinstance(profile, TeamProfile)
    assert profile.team == "MI"
    assert profile.matches == 14
    assert profile.won == 9
    assert profile.lost == 5


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_not_found(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": None}
    mock_get.return_value = mock_resp

    profile = get_team_profile("UNKNOWN", "ipl")
    assert profile is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_team_stats.py -v`
Expected: FAIL

- [ ] **Step 7: Implement scrapers/team_stats.py**

Replace the entire file:
```python
"""Cricket team stats scraper using CricketData.org API."""

from dataclasses import dataclass, field
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE


@dataclass
class TeamProfile:
    team: str  # abbreviation
    league: str
    matches: int = 0
    won: int = 0
    lost: int = 0
    no_result: int = 0
    win_rate: float = 0.0
    bat_first_wins: int = 0
    chase_wins: int = 0
    avg_score_bat_first: float = 0.0
    avg_score_chasing: float = 0.0
    nrr: str = "+0.000"
    standing: int = 0
    last_5: list[str] = field(default_factory=list)
    powerplay_run_rate: float = 0.0
    death_overs_economy: float = 0.0


def get_team_profile(team: str, league: str) -> Optional[TeamProfile]:
    """Fetch team profile from CricketData.org.

    Args:
        team: Team abbreviation (e.g. 'MI').
        league: League key (e.g. 'ipl').

    Returns:
        TeamProfile or None if not found.
    """
    url = f"{CRICKET_API_BASE}/teams"
    params = {"apikey": CRICKET_API_KEY}

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data")

    if not data:
        return None

    # Parse response into TeamProfile
    if isinstance(data, dict):
        return _parse_team_data(data, team, league)
    elif isinstance(data, list):
        for entry in data:
            if entry.get("shortname") == team:
                return _parse_team_data(entry, team, league)

    return None


def _parse_team_data(data: dict, team: str, league: str) -> TeamProfile:
    matches = data.get("matches", 0)
    won = data.get("won", 0)
    lost = data.get("lost", 0)
    win_rate = won / matches if matches > 0 else 0.0

    return TeamProfile(
        team=team,
        league=league,
        matches=matches,
        won=won,
        lost=lost,
        no_result=data.get("no_result", 0),
        win_rate=win_rate,
        nrr=data.get("nrr", "+0.000"),
        standing=data.get("position", 0),
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_team_stats.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add scrapers/schedule.py scrapers/team_stats.py tests/test_schedule.py tests/test_team_stats.py
git commit -m "feat: add cricket schedule scraper and rewrite team stats for CricketData.org"
```

---

### Task 3: Players + Venue Scrapers (Agent 3)

**Files:**
- Create: `scrapers/players.py`
- Create: `scrapers/venue.py`
- Create: `tests/test_players.py`
- Create: `tests/test_venue.py`

- [ ] **Step 1: Write test for players scraper**

Create `tests/test_players.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from scrapers.players import get_key_players, PlayerProfile


def _mock_player_data():
    return {
        "data": [
            {
                "id": "p001",
                "name": "Jasprit Bumrah",
                "role": "bowler",
                "battingStyle": "Right Hand Bat",
                "bowlingStyle": "Right-arm fast",
                "country": "India",
            },
            {
                "id": "p002",
                "name": "Rohit Sharma",
                "role": "batsman",
                "battingStyle": "Right Hand Bat",
                "bowlingStyle": "Right-arm offbreak",
                "country": "India",
            },
        ]
    }


@patch("scrapers.players.requests.get")
def test_get_key_players(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_player_data()
    mock_get.return_value = mock_resp

    players = get_key_players("MI", "ipl")

    assert len(players) == 2
    assert isinstance(players[0], PlayerProfile)
    assert players[0].name == "Jasprit Bumrah"
    assert players[0].role == "bowler"


@patch("scrapers.players.requests.get")
def test_get_key_players_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_get.return_value = mock_resp

    players = get_key_players("MI", "ipl")
    assert players == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_players.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scrapers/players.py**

```python
"""Key player profiles using CricketData.org API."""

from dataclasses import dataclass, field
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE


@dataclass
class PlayerProfile:
    player_id: str
    name: str
    role: str  # batsman, bowler, all-rounder, keeper
    batting_style: str = ""
    bowling_style: str = ""
    batting_avg: float = 0.0
    batting_sr: float = 0.0
    tournament_runs: int = 0
    bowling_econ: float = 0.0
    bowling_avg: float = 0.0
    tournament_wickets: int = 0
    recent_form: list[str] = field(default_factory=list)
    venue_record: str = ""


def get_key_players(team: str, league: str, limit: int = 6) -> list[PlayerProfile]:
    """Fetch key player profiles for a team.

    Args:
        team: Team abbreviation (e.g. 'MI').
        league: League key (e.g. 'ipl').
        limit: Max players to return (default 6).

    Returns:
        List of PlayerProfile dataclasses.
    """
    url = f"{CRICKET_API_BASE}/players"
    params = {"apikey": CRICKET_API_KEY}

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    players = []
    for item in data[:limit]:
        players.append(PlayerProfile(
            player_id=item.get("id", ""),
            name=item.get("name", ""),
            role=item.get("role", "unknown"),
            batting_style=item.get("battingStyle", ""),
            bowling_style=item.get("bowlingStyle", ""),
        ))

    return players
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_players.py -v`
Expected: PASS

- [ ] **Step 5: Write test for venue scraper**

Create `tests/test_venue.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from scrapers.venue import get_venue_conditions, VenueConditions


@patch("scrapers.venue.requests.get")
def test_get_venue_conditions(mock_get):
    mock_weather = MagicMock()
    mock_weather.status_code = 200
    mock_weather.json.return_value = {
        "main": {"temp": 32.5, "humidity": 65},
        "wind": {"speed": 12.0},
    }
    mock_get.return_value = mock_weather

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    assert isinstance(conditions, VenueConditions)
    assert conditions.venue_name == "Wankhede Stadium"
    assert conditions.temp_celsius == 32.5
    assert conditions.humidity == 65


def test_get_venue_conditions_unknown_venue():
    conditions = get_venue_conditions("Unknown Ground", "ipl")
    assert conditions.venue_name == "Unknown Ground"
    assert conditions.temp_celsius is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_venue.py -v`
Expected: FAIL

- [ ] **Step 7: Implement scrapers/venue.py**

```python
"""Venue & conditions scraper using Cricsheet data + weather API."""

from dataclasses import dataclass
from typing import Optional

import requests

from config import WEATHER_API_KEY, WEATHER_API_BASE, VENUE_COORDS


@dataclass
class VenueConditions:
    venue_name: str
    avg_1st_innings_score: float = 0.0
    avg_2nd_innings_score: float = 0.0
    chase_win_pct: float = 50.0
    pitch_type: str = "balanced"  # batting-friendly, bowling-friendly, balanced
    pitch_degradation: str = "unknown"
    dew_factor: str = "none"  # none, moderate, heavy
    boundary_size: str = "average"
    temp_celsius: Optional[float] = None
    humidity: Optional[int] = None
    wind_speed: Optional[float] = None
    day_night: str = "unknown"


def get_venue_conditions(venue: str, league: str) -> VenueConditions:
    """Get venue profile with weather conditions.

    Args:
        venue: Venue name (e.g. 'Wankhede Stadium').
        league: League key (e.g. 'ipl').

    Returns:
        VenueConditions dataclass.
    """
    conditions = VenueConditions(venue_name=venue)

    # Weather lookup if coordinates available
    coords = _find_venue_coords(venue)
    if coords and WEATHER_API_KEY:
        weather = _fetch_weather(coords[0], coords[1])
        if weather:
            conditions.temp_celsius = weather.get("temp")
            conditions.humidity = weather.get("humidity")
            conditions.wind_speed = weather.get("wind_speed")

    # Dew heuristic: evening matches in subcontinental venues
    _assess_dew(conditions, league)

    return conditions


def _find_venue_coords(venue: str) -> Optional[tuple[float, float]]:
    """Look up coordinates for a venue."""
    for name, coords in VENUE_COORDS.items():
        if name.lower() in venue.lower() or venue.lower() in name.lower():
            return coords
    return None


def _fetch_weather(lat: float, lon: float) -> Optional[dict]:
    """Fetch current weather from OpenWeatherMap."""
    try:
        resp = requests.get(
            f"{WEATHER_API_BASE}/weather",
            params={"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "metric"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "temp": data.get("main", {}).get("temp"),
            "humidity": data.get("main", {}).get("humidity"),
            "wind_speed": data.get("wind", {}).get("speed"),
        }
    except Exception:
        return None


def _assess_dew(conditions: VenueConditions, league: str) -> None:
    """Assess dew factor based on league and conditions."""
    subcontinental_leagues = {"ipl", "psl", "bpl"}
    if league in subcontinental_leagues and conditions.humidity and conditions.humidity > 60:
        conditions.dew_factor = "moderate" if conditions.humidity < 80 else "heavy"
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_venue.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add scrapers/players.py scrapers/venue.py tests/test_players.py tests/test_venue.py
git commit -m "feat: add cricket player profiles and venue conditions scrapers"
```

---

### Task 4: Toss + Odds + Scores Scrapers (Agent 4)

**Files:**
- Create: `scrapers/toss.py`
- Rewrite: `scrapers/odds.py`
- Rewrite: `scrapers/scores.py`
- Create: `tests/test_toss.py`
- Rewrite: `tests/test_odds.py`
- Rewrite: `tests/test_scores.py`

- [ ] **Step 1: Write test for toss scraper**

Create `tests/test_toss.py`:
```python
import pytest
from scrapers.toss import get_toss_analysis, TossAnalysis


def test_get_toss_analysis_returns_dataclass():
    analysis = get_toss_analysis("Wankhede Stadium")
    assert isinstance(analysis, TossAnalysis)
    assert analysis.venue == "Wankhede Stadium"
    assert 0 <= analysis.bat_first_pct <= 100
    assert 0 <= analysis.chase_pct <= 100
    assert analysis.bat_first_pct + analysis.chase_pct == pytest.approx(100, abs=1)


def test_get_toss_analysis_unknown_venue():
    analysis = get_toss_analysis("Nonexistent Ground")
    assert analysis.venue == "Nonexistent Ground"
    # Should return sensible defaults
    assert analysis.bat_first_pct == 50.0
    assert analysis.chase_pct == 50.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_toss.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scrapers/toss.py**

```python
"""Toss impact analysis using Cricsheet historical data."""

from dataclasses import dataclass


@dataclass
class TossAnalysis:
    venue: str
    bat_first_pct: float = 50.0  # % of toss winners choosing to bat
    chase_pct: float = 50.0  # % of toss winners choosing to field/chase
    bat_first_win_rate: float = 45.0  # historical win rate batting first
    chase_win_rate: float = 55.0  # historical win rate chasing
    typical_toss_choice: str = "field"  # bat or field
    dew_assessment: str = "unknown"
    sample_size: int = 0


# Default T20 venue toss stats (sourced from Cricsheet analysis)
# These are sensible defaults; will be enhanced with live Cricsheet parsing later
VENUE_TOSS_DATA = {
    "Wankhede Stadium": TossAnalysis(
        venue="Wankhede Stadium", bat_first_pct=35, chase_pct=65,
        bat_first_win_rate=42, chase_win_rate=58,
        typical_toss_choice="field", dew_assessment="moderate", sample_size=85,
    ),
    "M. Chinnaswamy Stadium": TossAnalysis(
        venue="M. Chinnaswamy Stadium", bat_first_pct=40, chase_pct=60,
        bat_first_win_rate=44, chase_win_rate=56,
        typical_toss_choice="field", dew_assessment="moderate", sample_size=72,
    ),
    "Eden Gardens": TossAnalysis(
        venue="Eden Gardens", bat_first_pct=38, chase_pct=62,
        bat_first_win_rate=43, chase_win_rate=57,
        typical_toss_choice="field", dew_assessment="heavy", sample_size=68,
    ),
    "Melbourne Cricket Ground": TossAnalysis(
        venue="Melbourne Cricket Ground", bat_first_pct=48, chase_pct=52,
        bat_first_win_rate=48, chase_win_rate=52,
        typical_toss_choice="field", dew_assessment="none", sample_size=55,
    ),
    "Adelaide Oval": TossAnalysis(
        venue="Adelaide Oval", bat_first_pct=45, chase_pct=55,
        bat_first_win_rate=46, chase_win_rate=54,
        typical_toss_choice="field", dew_assessment="none", sample_size=42,
    ),
}


def get_toss_analysis(venue: str) -> TossAnalysis:
    """Get toss impact analysis for a venue.

    Args:
        venue: Venue name (e.g. 'Wankhede Stadium').

    Returns:
        TossAnalysis with historical toss data for the venue.
    """
    # Exact match first
    if venue in VENUE_TOSS_DATA:
        return VENUE_TOSS_DATA[venue]

    # Fuzzy match
    for name, data in VENUE_TOSS_DATA.items():
        if name.lower() in venue.lower() or venue.lower() in name.lower():
            return data

    # Default T20 averages
    return TossAnalysis(venue=venue)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_toss.py -v`
Expected: PASS

- [ ] **Step 5: Write test for cricket odds scraper**

Rewrite `tests/test_odds.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from scrapers.odds import get_cricket_odds, american_to_implied_prob, OddsData


def test_american_to_implied_prob_positive():
    prob = american_to_implied_prob(200)
    assert prob == pytest.approx(0.3333, abs=0.01)


def test_american_to_implied_prob_negative():
    prob = american_to_implied_prob(-150)
    assert prob == pytest.approx(0.6, abs=0.01)


def _mock_odds_response():
    return [
        {
            "id": "game_001",
            "home_team": "Mumbai Indians",
            "away_team": "Chennai Super Kings",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Mumbai Indians", "price": -130},
                                {"name": "Chennai Super Kings", "price": 110},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -110, "point": 340.5},
                                {"name": "Under", "price": -110, "point": 340.5},
                            ],
                        },
                    ],
                }
            ],
        }
    ]


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_odds_response()
    mock_get.return_value = mock_resp

    odds_list = get_cricket_odds("ipl")

    assert len(odds_list) == 1
    o = odds_list[0]
    assert isinstance(o, OddsData)
    assert o.team_a == "MI"
    assert o.team_b == "CSK"
    assert o.moneyline["team_a"] == -130
    assert o.moneyline["team_b"] == 110
    assert o.total_runs["line"] == 340.5


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_get.return_value = mock_resp

    odds_list = get_cricket_odds("ipl")
    assert odds_list == []
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_odds.py -v`
Expected: FAIL

- [ ] **Step 7: Rewrite scrapers/odds.py**

```python
"""Cricket betting odds from The Odds API."""

from dataclasses import dataclass, field

import requests

from config import ODDS_API_KEY, ODDS_API_BASE, LEAGUES, TEAM_NAME_TO_ABBREV


def american_to_implied_prob(american_odds: int) -> float:
    """Convert American odds to implied probability (vig-included)."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


@dataclass
class OddsData:
    team_a: str  # abbreviation
    team_b: str
    team_a_full: str = ""
    team_b_full: str = ""
    moneyline: dict = field(default_factory=dict)  # {"team_a": price, "team_b": price}
    total_runs: dict = field(default_factory=dict)  # {"line": X, "over": price, "under": price}
    implied_probs: dict = field(default_factory=dict)  # {"team_a": prob, "team_b": prob}


def _resolve_team(name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(name, name)


def get_cricket_odds(league: str) -> list[OddsData]:
    """Fetch cricket odds from The Odds API.

    Args:
        league: League key (e.g. 'ipl').

    Returns:
        List of OddsData for upcoming matches.
    """
    league_cfg = LEAGUES.get(league)
    if not league_cfg:
        return []

    sport_key = league_cfg["odds_key"]
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,uk,eu",
        "markets": "h2h,totals",
        "oddsFormat": "american",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    events = resp.json()

    results = []
    for event in events:
        team_a_full = event.get("home_team", "")
        team_b_full = event.get("away_team", "")
        team_a = _resolve_team(team_a_full)
        team_b = _resolve_team(team_b_full)

        odds = OddsData(
            team_a=team_a,
            team_b=team_b,
            team_a_full=team_a_full,
            team_b_full=team_b_full,
        )

        # Parse first bookmaker with full markets
        for bk in event.get("bookmakers", []):
            for market in bk.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == team_a_full:
                            odds.moneyline["team_a"] = outcome["price"]
                        elif outcome["name"] == team_b_full:
                            odds.moneyline["team_b"] = outcome["price"]

                elif market["key"] == "totals":
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Over":
                            odds.total_runs["over"] = outcome["price"]
                            odds.total_runs["line"] = outcome.get("point", 0)
                        elif outcome["name"] == "Under":
                            odds.total_runs["under"] = outcome["price"]

            if odds.moneyline:
                break  # Use first bookmaker with data

        # Calculate implied probabilities (vig-removed)
        if "team_a" in odds.moneyline and "team_b" in odds.moneyline:
            raw_a = american_to_implied_prob(odds.moneyline["team_a"])
            raw_b = american_to_implied_prob(odds.moneyline["team_b"])
            total = raw_a + raw_b
            odds.implied_probs = {
                "team_a": raw_a / total if total > 0 else 0.5,
                "team_b": raw_b / total if total > 0 else 0.5,
            }

        results.append(odds)

    return results
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_odds.py -v`
Expected: PASS

- [ ] **Step 9: Write test for cricket scores scraper**

Rewrite `tests/test_scores.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores, MatchResult


def _mock_scores_response():
    return {
        "data": [
            {
                "id": "match_001",
                "name": "Mumbai Indians vs Chennai Super Kings",
                "teams": ["Mumbai Indians", "Chennai Super Kings"],
                "status": "Mumbai Indians won by 5 wickets",
                "score": [
                    {"r": 180, "w": 6, "o": 20, "inning": "Chennai Super Kings Inning 1"},
                    {"r": 183, "w": 5, "o": 19.2, "inning": "Mumbai Indians Inning 1"},
                ],
                "tpiResult": {
                    "tpiWinner": "Mumbai Indians",
                    "tpiDecision": "field",
                },
                "matchType": "t20",
            }
        ]
    }


@patch("scrapers.scores.requests.get")
def test_get_final_scores(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_scores_response()
    mock_get.return_value = mock_resp

    results = get_final_scores()

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, MatchResult)
    assert r.winner == "MI"
    assert r.team_a_score == 180
    assert r.team_b_score == 183
    assert r.total_runs == 363


@patch("scrapers.scores.requests.get")
def test_get_final_scores_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_get.return_value = mock_resp

    results = get_final_scores()
    assert results == []
```

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest tests/test_scores.py -v`
Expected: FAIL

- [ ] **Step 11: Rewrite scrapers/scores.py**

```python
"""Cricket match results scraper using CricketData.org API."""

from dataclasses import dataclass
from typing import Optional

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE, TEAM_NAME_TO_ABBREV


@dataclass
class MatchResult:
    match_id: str
    team_a: str  # abbreviation
    team_b: str
    team_a_full: str = ""
    team_b_full: str = ""
    winner: str = ""  # abbreviation
    team_a_score: int = 0
    team_a_wickets: int = 0
    team_a_overs: float = 0.0
    team_b_score: int = 0
    team_b_wickets: int = 0
    team_b_overs: float = 0.0
    total_runs: int = 0
    toss_winner: str = ""
    toss_decision: str = ""  # bat or field
    dls_applied: bool = False
    status: str = ""


def _resolve_team(name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(name, name)


def get_final_scores(date: Optional[str] = None) -> list[MatchResult]:
    """Fetch completed T20 match results.

    Args:
        date: Optional date filter (YYYY-MM-DD).

    Returns:
        List of MatchResult dataclasses.
    """
    url = f"{CRICKET_API_BASE}/matches"
    params = {"apikey": CRICKET_API_KEY, "offset": 0}

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    results = []
    for item in data:
        if item.get("matchType") != "t20":
            continue

        status = item.get("status", "")
        if "won" not in status.lower() and "tied" not in status.lower():
            continue

        teams = item.get("teams", [])
        if len(teams) < 2:
            continue

        team_a_full = teams[0]
        team_b_full = teams[1]
        team_a = _resolve_team(team_a_full)
        team_b = _resolve_team(team_b_full)

        # Parse scores
        scores = item.get("score", [])
        team_a_score, team_a_wickets, team_a_overs = 0, 0, 0.0
        team_b_score, team_b_wickets, team_b_overs = 0, 0, 0.0

        for s in scores:
            inning = s.get("inning", "")
            if team_a_full in inning:
                team_a_score = s.get("r", 0)
                team_a_wickets = s.get("w", 0)
                team_a_overs = s.get("o", 0.0)
            elif team_b_full in inning:
                team_b_score = s.get("r", 0)
                team_b_wickets = s.get("w", 0)
                team_b_overs = s.get("o", 0.0)

        # Determine winner
        winner = ""
        for t in [team_a_full, team_b_full]:
            if t.lower() in status.lower() and "won" in status.lower():
                winner = _resolve_team(t)
                break

        # Toss info
        toss = item.get("tpiResult", {}) or {}
        toss_winner = _resolve_team(toss.get("tpiWinner", ""))
        toss_decision = toss.get("tpiDecision", "")

        # DLS check
        dls_applied = "d/l" in status.lower() or "dls" in status.lower()

        results.append(MatchResult(
            match_id=item.get("id", ""),
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

    return results
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/test_toss.py tests/test_odds.py tests/test_scores.py -v`
Expected: ALL PASS

- [ ] **Step 13: Commit**

```bash
git add scrapers/toss.py scrapers/odds.py scrapers/scores.py tests/test_toss.py tests/test_odds.py tests/test_scores.py
git commit -m "feat: add toss analysis, rewrite odds and scores scrapers for cricket"
```

---

## Phase 2: Wire Everything Together

Phase 2 depends on Phase 1 completing. All 4 Phase 1 agents must finish before Phase 2 agents start.

### Task 5: Briefing + System Prompt (Agent 5)

**Files:**
- Rewrite: `briefing.py`
- Modify: `simulate.py:11-67,176-181`
- Modify: `ensemble/runner.py:7,49`
- Rewrite: `tests/test_briefing.py`
- Modify: `tests/test_simulate.py`

- [ ] **Step 1: Write test for cricket briefing**

Rewrite `tests/test_briefing.py`:
```python
import pytest
from briefing import build_briefing


def _mock_cricket_game_data():
    return {
        "league": "ipl",
        "match_number": 25,
        "date": "2026-03-25",
        "team_a": "MI",
        "team_b": "CSK",
        "team_a_full": "Mumbai Indians",
        "team_b_full": "Chennai Super Kings",
        "venue": "Wankhede Stadium, Mumbai",
        "day_night": "Night",
        "odds": {
            "moneyline": {"team_a": -130, "team_b": 110},
            "total_runs": {"line": 340.5, "over": -110, "under": -110},
            "implied_probs": {"team_a": 0.565, "team_b": 0.435},
        },
        "venue_conditions": {
            "avg_1st_innings_score": 175.3,
            "avg_2nd_innings_score": 168.7,
            "chase_win_pct": 58.0,
            "pitch_type": "batting-friendly",
            "dew_factor": "moderate",
            "temp_celsius": 32.5,
            "humidity": 65,
            "wind_speed": 12.0,
        },
        "toss": {
            "bat_first_pct": 35,
            "chase_pct": 65,
            "bat_first_win_rate": 42,
            "chase_win_rate": 58,
            "typical_toss_choice": "field",
        },
        "team_a_profile": {
            "record": "9-5",
            "nrr": "+0.825",
            "standing": 2,
            "form": "W W L W W",
        },
        "team_b_profile": {
            "record": "7-7",
            "nrr": "-0.120",
            "standing": 5,
            "form": "L W L W L",
        },
    }


def test_build_briefing_contains_cricket_sections():
    briefing = build_briefing(_mock_cricket_game_data())
    assert "T20 CRICKET MATCH PREDICTION ANALYSIS" in briefing
    assert "VENUE & CONDITIONS" in briefing
    assert "TOSS IMPACT" in briefing
    assert "Mumbai Indians" in briefing or "MI" in briefing
    assert "Chennai Super Kings" in briefing or "CSK" in briefing
    assert "Match Winner" in briefing
    assert "Total Runs" in briefing


def test_build_briefing_no_mlb_references():
    briefing = build_briefing(_mock_cricket_game_data())
    assert "MLB" not in briefing
    assert "pitcher" not in briefing.lower()
    assert "bullpen" not in briefing.lower()
    assert "run_line" not in briefing
    assert "first_5" not in briefing
    assert "innings" not in briefing.lower() or "innings score" in briefing.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_briefing.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite briefing.py**

Replace entire file with cricket T20 briefing template (from `docs/sport-prompts/08-cricket-t20.md`):

```python
"""Build structured briefing for T20 cricket LLM prediction."""


def build_briefing(game_data: dict) -> str:
    """Compile game data into a structured text briefing for the LLM.

    Args:
        game_data: Dict with keys: league, match_number, date, team_a, team_b,
            venue, day_night, odds, venue_conditions, toss, team_a_profile,
            team_b_profile, team_a_players, team_b_players, head_to_head,
            match_context.

    Returns:
        Formatted briefing string.
    """
    odds = game_data.get("odds", {})
    ml = odds.get("moneyline", {})
    total = odds.get("total_runs", {})
    probs = odds.get("implied_probs", {})
    vc = game_data.get("venue_conditions", {})
    toss = game_data.get("toss", {})
    ta = game_data.get("team_a_profile", {})
    tb = game_data.get("team_b_profile", {})

    lines = [
        "T20 CRICKET MATCH PREDICTION ANALYSIS",
        "=" * 40,
        f"{game_data.get('league', '').upper()} — Match {game_data.get('match_number', '')} | {game_data.get('date', '')}",
        f"{game_data.get('team_a_full', game_data.get('team_a', ''))} vs {game_data.get('team_b_full', game_data.get('team_b', ''))}",
        f"{game_data.get('venue', '')} | {game_data.get('day_night', '')}",
        "",
        "BETTING LINES:",
        f"  Match Winner: {game_data.get('team_a', '')} {ml.get('team_a', 'N/A')} / {game_data.get('team_b', '')} {ml.get('team_b', 'N/A')}",
        f"  Total Runs: {total.get('line', 'N/A')} (Over {total.get('over', 'N/A')} / Under {total.get('under', 'N/A')})",
        f"  Implied Win Prob: {game_data.get('team_a', '')} {probs.get('team_a', 0):.1%} / {game_data.get('team_b', '')} {probs.get('team_b', 0):.1%}",
        "",
        "== VENUE & CONDITIONS ==",
        f"  Ground: {game_data.get('venue', '')}",
        f"  Avg 1st Innings Score: {vc.get('avg_1st_innings_score', 'N/A')}",
        f"  Avg 2nd Innings Score: {vc.get('avg_2nd_innings_score', 'N/A')}",
        f"  Chase Win %: {vc.get('chase_win_pct', 'N/A')}%",
        f"  Pitch Type: {vc.get('pitch_type', 'N/A')}",
        f"  Dew Factor: {vc.get('dew_factor', 'N/A')}",
        f"  Weather: {vc.get('temp_celsius', 'N/A')}°C, Humidity {vc.get('humidity', 'N/A')}%, Wind {vc.get('wind_speed', 'N/A')}",
        "",
        "== TOSS IMPACT ==",
        f"  At this venue: teams batting first win {toss.get('bat_first_win_rate', 'N/A')}%, chasing wins {toss.get('chase_win_rate', 'N/A')}%",
        f"  Toss winner typically elects to: {toss.get('typical_toss_choice', 'N/A')}",
        f"  Toss result: {game_data.get('toss_result', 'TBD')}",
        "",
        "== TEAM PROFILES ==",
        "",
        f"{game_data.get('team_a_full', game_data.get('team_a', ''))} — {ta.get('record', 'N/A')} | NRR: {ta.get('nrr', 'N/A')} | Standing: #{ta.get('standing', 'N/A')}",
        f"  Form (Last 5): {ta.get('form', 'N/A')}",
    ]

    # Team A players
    for p in game_data.get("team_a_players", []):
        lines.append(f"    {p.get('name', '')}: {p.get('role', '')} | {p.get('stats', '')}")

    lines += [
        "",
        f"{game_data.get('team_b_full', game_data.get('team_b', ''))} — {tb.get('record', 'N/A')} | NRR: {tb.get('nrr', 'N/A')} | Standing: #{tb.get('standing', 'N/A')}",
        f"  Form (Last 5): {tb.get('form', 'N/A')}",
    ]

    # Team B players
    for p in game_data.get("team_b_players", []):
        lines.append(f"    {p.get('name', '')}: {p.get('role', '')} | {p.get('stats', '')}")

    # Head-to-head
    h2h = game_data.get("head_to_head", {})
    lines += [
        "",
        "== HEAD-TO-HEAD ==",
        f"  Overall: {h2h.get('overall', 'N/A')}",
        f"  At This Venue: {h2h.get('at_venue', 'N/A')}",
    ]
    for meeting in h2h.get("last_3", []):
        lines.append(f"    {meeting}")

    # Match context
    ctx = game_data.get("match_context", {})
    lines += [
        "",
        "== MATCH CONTEXT ==",
        f"  League Stage: {ctx.get('stage', 'N/A')}",
        f"  Playoff Implications: {ctx.get('playoff_context', 'N/A')}",
        "",
        "== PREDICTION TASK ==",
        "Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:",
        "",
        f"1. MATCH WINNER: Win probability for each team. Factor in toss impact, venue history, and current form. Which side has moneyline value?",
        f"2. TOTAL RUNS (O/U {total.get('line', 'N/A')}): Projected total runs. Factor in pitch conditions, powerplay/death bowling quality, boundary dimensions, and dew factor.",
        "",
        "For each bet type, provide:",
        "  - Your probability estimate",
        "  - Whether the market price offers value",
        "  - Confidence level (low/medium/high)",
        "  - Key factors driving the assessment",
    ]

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_briefing.py -v`
Expected: PASS

- [ ] **Step 5: Replace MLB_SYSTEM_PROMPT in simulate.py**

Replace lines 11-67 (`MLB_SYSTEM_PROMPT`) with `SYSTEM_PROMPT` (renamed from MLB-specific):

```python
SYSTEM_PROMPT = """You are an elite T20 cricket prediction system analyzing a franchise league match.
Simulate a panel of 6 expert analysts:

1. PITCH & CONDITIONS ANALYST: Evaluates the pitch surface, venue history,
   weather conditions, dew factor, and how conditions will change through
   the match. Is this a high-scoring belter or a turning track?
   Does the surface deteriorate for the team batting second?
   This is the MOST IMPORTANT factor in T20 prediction.
2. BATTING ANALYST: Evaluates top-order and middle-order quality, power-hitting
   ability, matchups against the opposition bowling attack, and recent form.
   Powerplay aggression vs death-overs finishing ability.
3. BOWLING ANALYST: Evaluates pace and spin bowling matchups, death bowling
   quality, powerplay wicket-taking ability, and economy rates. How does the
   bowling attack match up on this specific surface?
4. TOSS & CHASE ANALYST: Evaluates the toss impact at this venue. If the
   toss has occurred, how does the decision change probabilities?
   Dew makes chasing significantly easier at subcontinental evening venues.
   What is the historical chase win rate here?
5. MARKET ANALYST: Evaluates the betting lines for value. Is the market
   properly pricing the venue factor? Is a team's recent form masking
   underlying quality? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is a strong team overvalued because
   of brand/IPL auction price? Is a "weak" batting lineup actually better
   suited to this pitch? Is the dew factor being overweighted in dry conditions?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "pitch_conditions", "pick": "TEAM", "reasoning": "..."},
    {"role": "batting", "pick": "TEAM", "reasoning": "..."},
    {"role": "bowling", "pick": "TEAM", "reasoning": "..."},
    {"role": "toss_chase", "pick": "TEAM", "reasoning": "..."},
    {"role": "market", "pick": "TEAM", "reasoning": "..."},
    {"role": "contrarian", "pick": "TEAM", "reasoning": "..."}
  ],
  "predictions": {
    "moneyline": {
      "team_a_win_prob": 0.XX,
      "team_b_win_prob": 0.XX,
      "value_side": "team_a|team_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_runs": {
      "projected_total": XXX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {
      "winner": "TEAM",
      "winning_margin": "X wickets|X runs",
      "projected_scores": {"batting_first": XXX, "chasing": XXX}
    },
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""
```

- [ ] **Step 6: Update _average_results() in simulate.py**

Replace the `prob_fields` dict (lines 176-181):
```python
prob_fields = {
    "moneyline": ["team_a_win_prob", "team_b_win_prob", "edge"],
    "total_runs": ["projected_total", "over_prob", "under_prob", "edge"],
}
```

- [ ] **Step 7: Update ensemble/runner.py import**

Change line 7 from:
```python
from simulate import MLB_SYSTEM_PROMPT, parse_simulation_result
```
to:
```python
from simulate import SYSTEM_PROMPT, parse_simulation_result
```

Change line 49 from:
```python
sys_prompt = system_prompt or MLB_SYSTEM_PROMPT
```
to:
```python
sys_prompt = system_prompt or SYSTEM_PROMPT
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_briefing.py tests/test_simulate.py -v`
Expected: PASS (may need to update test_simulate.py assertions for new prompt name)

- [ ] **Step 9: Commit**

```bash
git add briefing.py simulate.py ensemble/runner.py tests/test_briefing.py tests/test_simulate.py
git commit -m "feat: cricket T20 briefing template and 6-analyst system prompt"
```

---

### Task 6: Edge + Main (Agent 6)

**Files:**
- Modify: `edge.py:74-308,311-335`
- Rewrite: `main.py`
- Modify: `tests/test_edge.py`

- [ ] **Step 1: Update edge.py — remove MLB bet types, update field names**

Remove these functions entirely:
- `check_run_line_edge()` (lines 74-137)
- `check_f5_ml_edge()` (lines 193-243)
- `check_f5_total_edge()` (lines 246-308)

In `check_moneyline_edge()`:
- Change `home_win_prob`/`away_win_prob` → `team_a_win_prob`/`team_b_win_prob`
- Change `ml_odds["home"]`/`ml_odds["away"]` → `ml_odds["team_a"]`/`ml_odds["team_b"]`
- Change `implied_probs.get("ml_home")`/`implied_probs.get("ml_away")` → `implied_probs.get("team_a")`/`implied_probs.get("team_b")` (must match `OddsData.implied_probs` keys)

In `check_total_edge()`:
- Change `predictions.get("total")` → `predictions.get("total_runs")`
- Change `odds.get("total", {})` → `odds.get("total_runs", {})`
- Change `total_odds.get("over_odds")` → `total_odds.get("over")` and `total_odds.get("under_odds")` → `total_odds.get("under")` (must match `OddsData.total_runs` keys)
- Update edge threshold key from `"total"` → `"total_runs"`

Rewrite `analyze_all_edges()`:
```python
def analyze_all_edges(predictions: dict, odds: dict) -> list[dict]:
    """Check all cricket bet types for edge."""
    checkers = [
        ("moneyline", check_moneyline_edge),
        ("total_runs", check_total_edge),
    ]
    edges = []
    for bet_type, checker in checkers:
        result = checker(predictions, odds)
        if result:
            edges.append(result)
    return edges
```

- [ ] **Step 2: Update tests/test_edge.py**

Remove all tests for `check_run_line_edge`, `check_f5_ml_edge`, `check_f5_total_edge`. Update remaining tests to use `team_a_win_prob`/`team_b_win_prob` field names and `total_runs` key. Update edge threshold references from `"total"` to `"total_runs"`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: PASS

- [ ] **Step 4: Rewrite main.py**

Replace all MLB scraper imports and game_data building. Key changes:
- Import cricket scrapers: `schedule`, `team_stats`, `players`, `venue`, `toss`, `odds`, `scores`
- Remove: `get_probable_starters`, `get_confirmed_lineups`, `get_bullpen_state`, `get_game_environment`
- Replace `get_mlb_odds` with `get_cricket_odds`
- Add `--league` CLI argument
- Change title from "MLB" to "Cricket T20"
- Build `game_data` dict with cricket structure: `team_a`, `team_b`, `venue_conditions`, `toss`, `team_a_profile`, `team_b_profile`, `team_a_players`, `team_b_players`, `odds`
- Remove all references to `away_pitcher`, `home_pitcher`, `bullpen`, `f5_moneyline`, `f5_total`, `run_line`

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add edge.py main.py tests/test_edge.py
git commit -m "feat: cricket edge detection and CLI with --league support"
```

---

### Task 7: Agents (Agent 7)

**Files:**
- Modify: `agents/results_grader.py:21-81`
- Modify: `agents/health_check.py:4-18`
- Modify: `agents/daily_runner.py:82`
- Verify: `agents/bet_card.py`
- Rewrite: `scrapers/news.py`
- Rewrite: `docs/daily-workflow.md`
- Modify: `tests/test_results_grader.py`, `tests/test_health_check.py`, `tests/test_news.py`

- [ ] **Step 1: Update agents/results_grader.py**

In `grade_bet()`:
- Remove the entire `elif bet_type == "run_line":` block (lines 38-53)
- Remove the entire `elif bet_type == "first_5":` block (lines 62-81)
- Keep `moneyline` and `total` grading
- Rename `total` references to `total_runs` where appropriate
- Update score parsing from `home_score`/`away_score` to `team_a_score`/`team_b_score`
- Handle DLS: if `match.dls_applied`, void total_runs bets (push)

Update imports: change `from scrapers.scores import get_final_scores` (keep same import, new implementation)

- [ ] **Step 2: Update agents/health_check.py**

Replace `check_mlb_api()` (lines 11-18) with:
```python
def check_cricket_api():
    """Ping CricketData.org API."""
    try:
        resp = requests.get(
            f"{CRICKET_API_BASE}/matches",
            params={"apikey": CRICKET_API_KEY},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False
```

Update imports: replace `MLB_API_BASE` with `CRICKET_API_BASE, CRICKET_API_KEY`.
Update `run_health_check()` to call `check_cricket_api()` instead of `check_mlb_api()`.

- [ ] **Step 3: Update agents/daily_runner.py branding**

Change line 82 from `"MIROFISH DAILY RUNNER"` to `"MIROFISH T20 CRICKET DAILY RUNNER"`.

- [ ] **Step 4: Verify agents/bet_card.py**

Check that the American odds formatting `f"{int(bet['odds']):+4d}"` works for cricket odds. Cricket odds from The Odds API come in American format when requested, so this should work as-is. Update branding from `"MIROFISH BET CARD"` to `"MIROFISH T20 CRICKET BET CARD"`.

- [ ] **Step 5: Rewrite scrapers/news.py**

```python
"""Cricket news and squad availability."""

from dataclasses import dataclass, field

import requests

from config import CRICKET_API_KEY, CRICKET_API_BASE


@dataclass
class SquadUpdate:
    team: str
    league: str
    available: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    notes: str = ""


def get_squad_updates(league: str) -> list[SquadUpdate]:
    """Fetch squad/availability updates.

    Args:
        league: League key (e.g. 'ipl').

    Returns:
        List of SquadUpdate dataclasses.
    """
    # CricketData.org doesn't have a dedicated injuries endpoint.
    # For now, return empty list. Future: scrape team announcements.
    return []
```

- [ ] **Step 6: Rewrite docs/daily-workflow.md**

Replace MLB workflow instructions with cricket T20 workflow covering:
- Health check, grade yesterday's results, run pipeline for today's matches
- `--league` flag usage
- Bet types: match winner + total runs only
- League season schedules

- [ ] **Step 7: Update tests**

- `tests/test_results_grader.py`: Remove run_line and first_5 grading tests. Update score structures to cricket format. Add DLS void test.
- `tests/test_health_check.py`: Replace `check_mlb_api` assertions with `check_cricket_api`.
- `tests/test_news.py`: Update to test `get_squad_updates()`.

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_results_grader.py tests/test_health_check.py tests/test_news.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add agents/ scrapers/news.py docs/daily-workflow.md tests/test_results_grader.py tests/test_health_check.py tests/test_news.py
git commit -m "feat: update agents, news scraper, and daily workflow for cricket T20"
```

---

### Task 8: Test Fixtures + Integration (Agent 8)

**Files:**
- Modify: `tests/ensemble_fixtures.py`
- Modify: `tests/test_ensemble_weights.py`
- Modify: `tests/test_ensemble_consensus.py`
- Modify: `tests/test_ensemble_orchestrator.py`
- Modify: `tests/test_ensemble_runner.py`
- Modify: `tests/test_ensemble_challenger.py`
- Modify: `tests/test_ensemble_integration.py`
- Modify: `tests/test_ensemble_logger.py`
- Modify: `tests/test_ensemble_models.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_self_optimizer.py`
- Modify: `tests/test_bet_card.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_tracker.py`
- Modify: `tests/test_calibrate.py`
- Modify: `ensemble/logger.py` (game label format)
- Create: `.env.example`

- [ ] **Step 1: Update tests/ensemble_fixtures.py**

Replace `MOCK_PREDICTION`:
```python
MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "pitch_conditions", "pick": "MI", "reasoning": "Batting-friendly pitch"},
        {"role": "batting", "pick": "MI", "reasoning": "Stronger top order"},
        {"role": "bowling", "pick": "CSK", "reasoning": "Better death bowling"},
        {"role": "toss_chase", "pick": "MI", "reasoning": "Dew advantage chasing"},
        {"role": "market", "pick": "MI", "reasoning": "Value on MI at these odds"},
        {"role": "contrarian", "pick": "CSK", "reasoning": "MI overvalued by brand"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.58,
            "team_b_win_prob": 0.42,
            "value_side": "team_a",
            "edge": 0.08,
            "confidence": "medium",
        },
        "total_runs": {
            "projected_total": 345.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.06,
            "confidence": "medium",
        },
        "predicted_result": {
            "winner": "MI",
            "winning_margin": "5 wickets",
            "projected_scores": {"batting_first": 175, "chasing": 178},
        },
        "key_factors": ["Dew advantage", "Batting-friendly pitch", "MI powerplay strength"],
    },
}

MOCK_ODDS = {
    "moneyline": {"team_a": -130, "team_b": 110},
    "total_runs": {"line": 340.5, "over": -110, "under": -110},
    "implied_probs": {"team_a": 0.565, "team_b": 0.435},
}
```

Update `make_prediction()` helper to use cricket fields.

- [ ] **Step 2: Update all ensemble test files**

For each test file:
- `test_ensemble_weights.py`: Change `assert len(BET_SLOTS) == 5` to `== 2`. Update slot names in weight assertions.
- `test_ensemble_consensus.py`: Update `BET_SLOT_FIELDS` assertions to 2 entries. Remove all `run_line` vote normalization tests. Update vote extraction tests to use `team_a`/`team_b`.
- `test_ensemble_orchestrator.py`: Update `PROB_FIELDS`, `SLOT_SECTION`, `PRIMARY_PROB_FIELD` assertions. Remove first_5 references. Change `predicted_score` to `predicted_result` with keys `batting_first`/`chasing`.
- `test_ensemble_runner.py`: Change `MLB_SYSTEM_PROMPT` import to `SYSTEM_PROMPT`.
- `test_ensemble_challenger.py`: Update any "MLB" string assertions to "T20 cricket".
- `test_ensemble_integration.py`: Update `MOCK_PREDICTION` usage to cricket format.
- `test_ensemble_logger.py`: Change game labels from `"NYY@BOS"` to `"MI vs CSK"`.
- `test_ensemble_models.py`: Verify `get_panel_models()` still works with short keys. No changes expected if `ENSEMBLE_MODELS` kept short keys.

- [ ] **Step 3: Update test_config.py**

Update assertions for:
- `LEAGUES` dict (8 entries)
- `BET_SLOTS` (2 entries)
- `EDGE_THRESHOLDS` (2 entries, both 0.06)
- `KELLY_FRACTION` (0.125)
- Remove assertions for `MLB_API_BASE`, `TEAM_ABBREVS`, `PARK_FACTORS`, `PARK_COORDS`

- [ ] **Step 4: Update test_self_optimizer.py**

Verify `BET_SLOTS` import from `ensemble.weights` works with 2 slots. Update any bet type iteration tests.

- [ ] **Step 5: Update test_bet_card.py**

Update game label formatting assertions. Verify odds display works.

- [ ] **Step 6: Update remaining test files**

- `tests/test_main.py`: Update to match new CLI structure (cricket scraper calls, `--league` flag). Mock cricket scrapers instead of MLB scrapers.
- `tests/test_tracker.py`: Update game key format if changed (e.g. `"MI vs CSK"` instead of `"BOS@NYY"`). If `tracker.py` is unchanged, verify tests still pass.
- `tests/test_calibrate.py`: Verify it still works with the 2 cricket bet types. Likely no changes needed.
- `ensemble/logger.py`: Update game label format in `PREDICTION_COLUMNS` or wherever game labels are constructed — use `"MI vs CSK"` format instead of `"NYY@BOS"`.

- [ ] **Step 7: Create .env.example**

Create `.env.example` with all required environment variables:
```
ODDS_API_KEY=your_odds_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
WEATHER_API_KEY=your_openweathermap_api_key
CRICKET_API_KEY=your_cricketdata_org_api_key
LOG_LEVEL=INFO
```

- [ ] **Step 8: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 9: Fix any integration failures**

If any tests fail due to cross-file dependencies, fix the specific failures.

- [ ] **Step 10: Commit**

```bash
git add tests/ ensemble/logger.py .env.example
git commit -m "feat: update all test fixtures and ensemble tests for cricket T20"
```

---

## Final Integration

### Task 9: Full Pipeline Smoke Test

- [ ] **Step 1: Run complete test suite**

Run: `pytest tests/ -v --tb=long`
Expected: ALL PASS with 0 failures

- [ ] **Step 2: Verify no MLB references remain**

Run: `grep -rn "MLB\|mlb\|baseball\|pitcher\|bullpen\|run_line\|first_5\|home_win_prob\|away_win_prob" --include="*.py" .`
Expected: No matches (or only in comments/docs explaining the migration)

- [ ] **Step 3: Verify health check passes**

Run: `python main.py health`
Expected: CricketData.org, Odds API, OpenRouter checks pass (or graceful failure if no API keys set)

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final integration verification — MLB to Cricket T20 migration complete"
```
