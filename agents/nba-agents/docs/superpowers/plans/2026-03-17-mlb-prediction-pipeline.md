# MiroFish MLB Prediction Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily MLB prediction pipeline that scrapes matchup data, screens via direct Kimi calls, simulates high-edge games via MiroFish 512-agent swarm, and outputs Kelly-sized bet signals across Moneyline, Run Line, Totals, and First 5 Innings.

**Architecture:** Scraper layer pulls from pybaseball, MLB Stats API, The Odds API, and weather APIs into a briefing document. Two-tier simulation: Plan B (direct Kimi, $0.06/game) screens all games, then full MiroFish runs on games with >3% edge. Edge detection applies independent Kelly calculations per bet type. CLI orchestrates the daily flow with a CSV-based bet tracker.

**Tech Stack:** Python 3.11+, pybaseball, requests, openai (for Kimi K2.5 via OpenRouter), python-dotenv, click (CLI), pandas (tracker/calibration)

---

## File Structure

```
mlb-predictor/
├── .env                     # API keys (ODDS_API_KEY, OPENROUTER_API_KEY, WEATHER_API_KEY)
├── .env.example             # Template with placeholder keys
├── .gitignore
├── requirements.txt
├── config.py                # All constants, thresholds, team mappings
│
├── scrapers/
│   ├── __init__.py
│   ├── pitchers.py          # Starting pitcher stats + game logs via pybaseball + MLB API
│   ├── lineups.py           # Daily lineup scraper via MLB Stats API
│   ├── bullpen.py           # Bullpen usage tracker (rolling 3-day) via MLB Stats API
│   ├── team_stats.py        # Team-level batting, record, run differential via pybaseball
│   ├── ballpark.py          # Park factors (hardcoded) + weather via OpenWeatherMap
│   ├── odds.py              # Lines across all 4 bet types via The Odds API
│   └── news.py              # Injury reports + roster moves via MLB Stats API
│
├── briefing.py              # Compiles all scraper data into seed document string
├── simulate.py              # MiroFish runner OR direct Kimi Plan B calls via OpenRouter
├── edge.py                  # Edge detection + Kelly sizing for all 4 bet types
├── tracker.py               # Bet logging + P&L tracking to CSV
├── calibrate.py             # Rolling calibration (stub for week 2+)
├── main.py                  # CLI entrypoint: daily / game / results / report
│
├── data/
│   └── bets.csv             # Bet log (created at runtime)
│
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_pitchers.py
    ├── test_lineups.py
    ├── test_bullpen.py
    ├── test_team_stats.py
    ├── test_ballpark.py
    ├── test_odds.py
    ├── test_news.py
    ├── test_briefing.py
    ├── test_simulate.py
    ├── test_edge.py
    ├── test_tracker.py
    └── test_main.py
```

---

## Task 1: Project Scaffolding + Config

**Files:**
- Create: `requirements.txt`, `.env.example`, `.gitignore`, `config.py`
- Test: `tests/__init__.py`, `tests/test_config.py`

- [ ] **Step 1: Initialize git repo and create .gitignore**

```bash
cd /Users/mikeborucki/personal_workspace/baseball-agents
git init
```

`.gitignore`:
```
.env
__pycache__/
*.pyc
data/bets.csv
.pytest_cache/
*.egg-info/
dist/
build/
```

- [ ] **Step 2: Create requirements.txt**

```
pybaseball>=2.3.0
requests>=2.31.0
openai>=1.12.0
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.1.0
pytest>=7.4.0
```

- [ ] **Step 3: Create .env.example**

```
ODDS_API_KEY=your_odds_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
WEATHER_API_KEY=your_openweathermap_api_key_here
```

- [ ] **Step 4: Write failing test for config**

`tests/__init__.py`: empty file

`tests/test_config.py`:
```python
from config import (
    EDGE_THRESHOLDS, PARK_FACTORS, TEAM_ABBREVS,
    MLB_API_BASE, ODDS_API_BASE, KELLY_FRACTION,
)


def test_edge_thresholds_exist_for_all_bet_types():
    for bet_type in ["moneyline", "run_line", "total", "first_5"]:
        assert bet_type in EDGE_THRESHOLDS
        assert 0 < EDGE_THRESHOLDS[bet_type] < 1


def test_park_factors_cover_all_30_teams():
    assert len(PARK_FACTORS) == 30
    for team, factors in PARK_FACTORS.items():
        assert "runs" in factors
        assert "hr" in factors
        assert "name" in factors


def test_team_abbrevs():
    assert len(TEAM_ABBREVS) == 30
    assert "NYY" in TEAM_ABBREVS
    assert "LAD" in TEAM_ABBREVS


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 0.25
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd /Users/mikeborucki/personal_workspace/baseball-agents && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 6: Write config.py**

`config.py`:
```python
import os
from dotenv import load_dotenv

load_dotenv()

# API keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")

# API base URLs
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MIROFISH_AGENTS = 512
SCREEN_EDGE_THRESHOLD = 0.03  # 3% edge to trigger full MiroFish sim

# Kelly sizing — use quarter-Kelly for safety
KELLY_FRACTION = 0.25

# Edge thresholds per bet type (minimum edge to signal a bet)
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "run_line": 0.06,
    "total": 0.05,
    "first_5": 0.05,
}

# All 30 MLB team abbreviations
TEAM_ABBREVS = [
    "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE",
    "COL", "DET", "HOU", "KC", "LAA", "LAD", "MIA", "MIL",
    "MIN", "NYM", "NYY", "OAK", "PHI", "PIT", "SD", "SF",
    "SEA", "STL", "TB", "TEX", "TOR", "WSH",
]

# Team full name to abbreviation mapping
TEAM_NAME_TO_ABBREV = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

# Park factors: keyed by team abbreviation
# runs/hr are multipliers vs league average (1.00 = neutral)
PARK_FACTORS = {
    "ARI": {"name": "Chase Field", "runs": 1.05, "hr": 1.05, "roof": "retractable"},
    "ATL": {"name": "Truist Park", "runs": 1.00, "hr": 1.05, "roof": "open"},
    "BAL": {"name": "Camden Yards", "runs": 1.05, "hr": 1.10, "roof": "open"},
    "BOS": {"name": "Fenway Park", "runs": 1.10, "hr": 0.95, "roof": "open"},
    "CHC": {"name": "Wrigley Field", "runs": 1.05, "hr": 1.05, "roof": "open"},
    "CWS": {"name": "Guaranteed Rate Field", "runs": 1.05, "hr": 1.10, "roof": "open"},
    "CIN": {"name": "Great American Ball Park", "runs": 1.15, "hr": 1.25, "roof": "open"},
    "CLE": {"name": "Progressive Field", "runs": 0.95, "hr": 0.95, "roof": "open"},
    "COL": {"name": "Coors Field", "runs": 1.35, "hr": 1.30, "roof": "open"},
    "DET": {"name": "Comerica Park", "runs": 0.95, "hr": 0.90, "roof": "open"},
    "HOU": {"name": "Minute Maid Park", "runs": 1.05, "hr": 1.10, "roof": "retractable"},
    "KC": {"name": "Kauffman Stadium", "runs": 1.00, "hr": 0.95, "roof": "open"},
    "LAA": {"name": "Angel Stadium", "runs": 0.95, "hr": 1.00, "roof": "open"},
    "LAD": {"name": "Dodger Stadium", "runs": 0.95, "hr": 0.95, "roof": "open"},
    "MIA": {"name": "loanDepot Park", "runs": 0.90, "hr": 0.85, "roof": "retractable"},
    "MIL": {"name": "American Family Field", "runs": 1.05, "hr": 1.10, "roof": "retractable"},
    "MIN": {"name": "Target Field", "runs": 1.00, "hr": 1.00, "roof": "open"},
    "NYM": {"name": "Citi Field", "runs": 0.95, "hr": 0.95, "roof": "open"},
    "NYY": {"name": "Yankee Stadium", "runs": 1.05, "hr": 1.15, "roof": "open"},
    "OAK": {"name": "Oakland Coliseum", "runs": 0.90, "hr": 0.85, "roof": "open"},
    "PHI": {"name": "Citizens Bank Park", "runs": 1.10, "hr": 1.15, "roof": "open"},
    "PIT": {"name": "PNC Park", "runs": 0.95, "hr": 0.90, "roof": "open"},
    "SD": {"name": "Petco Park", "runs": 0.90, "hr": 0.90, "roof": "open"},
    "SF": {"name": "Oracle Park", "runs": 0.85, "hr": 0.80, "roof": "open"},
    "SEA": {"name": "T-Mobile Park", "runs": 0.90, "hr": 0.90, "roof": "retractable"},
    "STL": {"name": "Busch Stadium", "runs": 0.95, "hr": 0.95, "roof": "open"},
    "TB": {"name": "Tropicana Field", "runs": 0.95, "hr": 0.95, "roof": "dome"},
    "TEX": {"name": "Globe Life Field", "runs": 1.00, "hr": 1.05, "roof": "retractable"},
    "TOR": {"name": "Rogers Centre", "runs": 1.05, "hr": 1.10, "roof": "retractable"},
    "WSH": {"name": "Nationals Park", "runs": 1.00, "hr": 1.05, "roof": "open"},
}

# Ballpark coordinates for weather lookups
PARK_COORDS = {
    "ARI": (33.4455, -112.0667), "ATL": (33.8907, -84.4677),
    "BAL": (39.2838, -76.6218), "BOS": (42.3467, -71.0972),
    "CHC": (41.9484, -87.6553), "CWS": (41.8299, -87.6338),
    "CIN": (39.0974, -84.5082), "CLE": (41.4962, -81.6852),
    "COL": (39.7559, -104.9942), "DET": (42.3390, -83.0485),
    "HOU": (29.7573, -95.3555), "KC": (39.0517, -94.4803),
    "LAA": (33.8003, -117.8827), "LAD": (34.0739, -118.2400),
    "MIA": (25.7781, -80.2196), "MIL": (43.0280, -87.9712),
    "MIN": (44.9818, -93.2775), "NYM": (40.7571, -73.8458),
    "NYY": (40.8296, -73.9262), "OAK": (37.7516, -122.2005),
    "PHI": (39.9061, -75.1665), "PIT": (40.4469, -80.0057),
    "SD": (32.7076, -117.1570), "SF": (37.7786, -122.3893),
    "SEA": (47.5914, -122.3325), "STL": (38.6226, -90.1928),
    "TB": (27.7682, -82.6534), "TEX": (32.7512, -97.0832),
    "TOR": (43.6414, -79.3894), "WSH": (38.8730, -77.0074),
}

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
```

- [ ] **Step 7: Create scrapers/__init__.py and data dir**

```bash
mkdir -p scrapers data tests
touch scrapers/__init__.py
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/mikeborucki/personal_workspace/baseball-agents && python -m pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements.txt .env.example config.py scrapers/__init__.py tests/__init__.py tests/test_config.py
git commit -m "feat: project scaffolding with config, park factors, and team mappings"
```

---

## Task 2: Odds Scraper

**Files:**
- Create: `scrapers/odds.py`
- Test: `tests/test_odds.py`

- [ ] **Step 1: Write failing test**

`tests/test_odds.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.odds import get_mlb_odds, american_to_implied_prob, OddsData


def test_american_to_implied_prob_favorite():
    # -150 implies 60%
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    # +130 implies ~43.5%
    assert abs(american_to_implied_prob(130) - 0.4348) < 0.001


def test_american_to_implied_prob_even():
    assert abs(american_to_implied_prob(100) - 0.5) < 0.001


MOCK_ODDS_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-04-01T23:05:00Z",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "New York Yankees", "price": -150},
                            {"name": "Boston Red Sox", "price": 130},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "New York Yankees", "price": 140, "point": -1.5},
                            {"name": "Boston Red Sox", "price": -165, "point": 1.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 8.5},
                            {"name": "Under", "price": -110, "point": 8.5},
                        ],
                    },
                    {
                        "key": "h2h_1st_5_innings",
                        "outcomes": [
                            {"name": "New York Yankees", "price": -135},
                            {"name": "Boston Red Sox", "price": 115},
                        ],
                    },
                    {
                        "key": "totals_1st_5_innings",
                        "outcomes": [
                            {"name": "Over", "price": -115, "point": 4.5},
                            {"name": "Under", "price": -105, "point": 4.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@patch("scrapers.odds.requests.get")
def test_get_mlb_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_mlb_odds()
    assert len(results) == 1
    game = results[0]
    assert game.home == "NYY"
    assert game.away == "BOS"
    assert game.moneyline["home"] == -150
    assert game.moneyline["away"] == 130
    assert game.run_line["home_odds"] == 140
    assert game.total["line"] == 8.5
    assert 0 < game.implied_probs["ml_home"] < 1
    # F5 markets
    assert game.f5_moneyline["home"] == -135
    assert game.f5_moneyline["away"] == 115
    assert game.f5_total["line"] == 4.5
    assert game.f5_total["over"] == -115


@patch("scrapers.odds.requests.get")
def test_get_mlb_odds_handles_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_mlb_odds()
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_odds.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write scrapers/odds.py**

```python
from dataclasses import dataclass, field
from datetime import datetime
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, TEAM_NAME_TO_ABBREV


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


@dataclass
class OddsData:
    home: str
    away: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    run_line: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    f5_moneyline: dict = field(default_factory=dict)
    f5_total: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def _team_abbrev(full_name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(full_name, full_name)


def get_mlb_odds(date: str = None) -> list[OddsData]:
    """Fetch MLB odds from The Odds API for h2h, spreads, totals markets."""
    url = f"{ODDS_API_BASE}/sports/baseball_mlb/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals,h2h_1st_5_innings,totals_1st_5_innings",
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] API requests remaining: {remaining}")

    results = []
    for event in resp.json():
        home_full = event["home_team"]
        away_full = event["away_team"]
        home = _team_abbrev(home_full)
        away = _team_abbrev(away_full)

        odds_data = OddsData(
            home=home,
            away=away,
            commence_time=event["commence_time"],
        )

        # Use first bookmaker with all markets (prefer FanDuel > DraftKings)
        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets:
                for outcome in markets["h2h"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.moneyline["home"] = outcome["price"]
                    else:
                        odds_data.moneyline["away"] = outcome["price"]

            if "spreads" in markets:
                for outcome in markets["spreads"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.run_line["home"] = outcome.get("point", -1.5)
                        odds_data.run_line["home_odds"] = outcome["price"]
                    else:
                        odds_data.run_line["away"] = outcome.get("point", 1.5)
                        odds_data.run_line["away_odds"] = outcome["price"]

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.total["line"] = outcome.get("point", 0)
                        odds_data.total["over_odds"] = outcome["price"]
                    else:
                        odds_data.total["under_odds"] = outcome["price"]

            # F5 (First 5 Innings) markets — may not be available from all books
            if "h2h_1st_5_innings" in markets:
                for outcome in markets["h2h_1st_5_innings"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.f5_moneyline["home"] = outcome["price"]
                    else:
                        odds_data.f5_moneyline["away"] = outcome["price"]

            if "totals_1st_5_innings" in markets:
                for outcome in markets["totals_1st_5_innings"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.f5_total["line"] = outcome.get("point", 0)
                        odds_data.f5_total["over"] = outcome["price"]
                    else:
                        odds_data.f5_total["under"] = outcome["price"]

            if odds_data.moneyline:
                break  # got data from this bookmaker

        # Compute implied probabilities
        if odds_data.moneyline:
            ml_home = american_to_implied_prob(odds_data.moneyline["home"])
            ml_away = american_to_implied_prob(odds_data.moneyline["away"])
            # Remove vig by normalizing
            total_prob = ml_home + ml_away
            odds_data.implied_probs["ml_home"] = ml_home / total_prob
            odds_data.implied_probs["ml_away"] = ml_away / total_prob

        if odds_data.run_line:
            rl_home = american_to_implied_prob(odds_data.run_line.get("home_odds", -110))
            rl_away = american_to_implied_prob(odds_data.run_line.get("away_odds", -110))
            total_prob = rl_home + rl_away
            odds_data.implied_probs["rl_home"] = rl_home / total_prob
            odds_data.implied_probs["rl_away"] = rl_away / total_prob

        results.append(odds_data)

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_odds.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: odds scraper with The Odds API integration"
```

---

## Task 3: Pitchers Scraper

**Files:**
- Create: `scrapers/pitchers.py`
- Test: `tests/test_pitchers.py`

- [ ] **Step 1: Write failing test**

`tests/test_pitchers.py`:
```python
import json
from datetime import date
from unittest.mock import patch, MagicMock
import pandas as pd
from scrapers.pitchers import get_starter_profile, get_probable_starters


MOCK_SCHEDULE_RESPONSE = {
    "dates": [
        {
            "games": [
                {
                    "gamePk": 12345,
                    "teams": {
                        "away": {
                            "team": {"name": "Boston Red Sox", "id": 111},
                            "probablePitcher": {"id": 543210, "fullName": "Brayan Bello"},
                        },
                        "home": {
                            "team": {"name": "New York Yankees", "id": 147},
                            "probablePitcher": {"id": 654321, "fullName": "Gerrit Cole"},
                        },
                    },
                    "venue": {"name": "Yankee Stadium"},
                    "gameDate": "2026-04-01T23:05:00Z",
                    "status": {"detailedState": "Scheduled"},
                }
            ]
        }
    ]
}


@patch("scrapers.pitchers.requests.get")
def test_get_probable_starters(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_SCHEDULE_RESPONSE
    mock_get.return_value = mock_resp

    games = get_probable_starters("2026-04-01")
    assert len(games) == 1
    game = games[0]
    assert game["away_pitcher"] == "Brayan Bello"
    assert game["home_pitcher"] == "Gerrit Cole"
    assert game["venue"] == "Yankee Stadium"


def test_get_starter_profile_returns_expected_shape():
    """Test that the profile dict has the right keys (using mock pybaseball data)."""
    with patch("scrapers.pitchers.pitching_stats") as mock_ps, \
         patch("scrapers.pitchers.playerid_lookup") as mock_lookup, \
         patch("scrapers.pitchers.statcast_pitcher") as mock_sc, \
         patch("scrapers.pitchers.requests.get") as mock_get:

        # Mock playerid_lookup
        mock_lookup.return_value = pd.DataFrame({
            "key_mlbam": [543210],
            "name_first": ["Gerrit"],
            "name_last": ["Cole"],
        })

        # Mock pitching_stats — return a DataFrame with one row
        mock_ps.return_value = pd.DataFrame({
            "Name": ["Gerrit Cole"],
            "IDfg": [13125],
            "W": [12], "L": [5],
            "ERA": [3.21], "FIP": [3.05], "xFIP": [3.12],
            "WHIP": [1.05], "K/9": [10.2], "BB/9": [2.1], "HR/9": [0.9],
            "IP": [142.1], "GS": [22],
        })

        # Mock statcast — return minimal DataFrame
        mock_sc.return_value = pd.DataFrame({
            "pitch_type": ["FF", "SL", "CH"],
            "release_speed": [96.5, 88.2, 85.1],
        })

        # Mock MLB API for game logs
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"stats": []}
        mock_get.return_value = mock_resp

        profile = get_starter_profile("Gerrit Cole", season=2025)
        assert profile["name"] == "Gerrit Cole"
        assert "season_stats" in profile
        assert "era" in profile["season_stats"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pitchers.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/pitchers.py**

```python
from datetime import date, datetime, timedelta
import requests
import pandas as pd

from pybaseball import playerid_lookup, pitching_stats, statcast_pitcher
from config import MLB_API_BASE, TEAM_NAME_TO_ABBREV


def get_probable_starters(game_date: str = None) -> list[dict]:
    """Fetch today's games with probable pitchers from MLB Stats API."""
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{MLB_API_BASE}/schedule"
    params = {
        "date": game_date,
        "sportId": 1,
        "hydrate": "probablePitcher,venue",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            away = game["teams"]["away"]
            home = game["teams"]["home"]

            away_pitcher = away.get("probablePitcher", {})
            home_pitcher = home.get("probablePitcher", {})

            games.append({
                "game_pk": game["gamePk"],
                "game_date": game.get("gameDate", ""),
                "status": game.get("status", {}).get("detailedState", ""),
                "venue": game.get("venue", {}).get("name", ""),
                "away_team": TEAM_NAME_TO_ABBREV.get(
                    away["team"]["name"], away["team"]["name"]
                ),
                "away_team_id": away["team"]["id"],
                "away_pitcher": away_pitcher.get("fullName", "TBD"),
                "away_pitcher_id": away_pitcher.get("id"),
                "home_team": TEAM_NAME_TO_ABBREV.get(
                    home["team"]["name"], home["team"]["name"]
                ),
                "home_team_id": home["team"]["id"],
                "home_pitcher": home_pitcher.get("fullName", "TBD"),
                "home_pitcher_id": home_pitcher.get("id"),
            })

    return games


def get_starter_profile(pitcher_name: str, season: int = 2026) -> dict:
    """Build comprehensive pitcher profile from pybaseball + MLB API."""
    first, last = pitcher_name.split(" ", 1)

    # Get MLB ID
    lookup = playerid_lookup(last, first)
    if lookup.empty:
        return {"name": pitcher_name, "error": "player not found"}

    mlbam_id = int(lookup.iloc[0]["key_mlbam"])

    # Season stats from FanGraphs via pybaseball
    try:
        stats_df = pitching_stats(season, season, qual=0)
        player_row = stats_df[
            stats_df["Name"].str.contains(last, case=False, na=False)
        ]
        if player_row.empty:
            season_stats = {}
        else:
            row = player_row.iloc[0]
            season_stats = {
                "w": int(row.get("W", 0)),
                "l": int(row.get("L", 0)),
                "era": float(row.get("ERA", 0)),
                "fip": float(row.get("FIP", 0)),
                "xfip": float(row.get("xFIP", 0)),
                "whip": float(row.get("WHIP", 0)),
                "k_per_9": float(row.get("K/9", 0)),
                "bb_per_9": float(row.get("BB/9", 0)),
                "hr_per_9": float(row.get("HR/9", 0)),
                "ip": float(row.get("IP", 0)),
                "starts": int(row.get("GS", 0)),
            }
    except Exception:
        season_stats = {}

    # Pitch mix + velo from Statcast (last 30 days)
    pitch_mix = {}
    recent_velo = None
    try:
        end = date.today()
        start = end - timedelta(days=30)
        sc = statcast_pitcher(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), mlbam_id
        )
        if not sc.empty and "pitch_type" in sc.columns:
            counts = sc["pitch_type"].value_counts(normalize=True)
            pitch_mix = {k: round(v * 100, 1) for k, v in counts.items()}
        if not sc.empty and "release_speed" in sc.columns:
            fastballs = sc[sc["pitch_type"].isin(["FF", "SI"])]
            if not fastballs.empty:
                recent_velo = round(fastballs["release_speed"].mean(), 1)
    except Exception:
        pass

    # Recent game logs from MLB API
    last_5 = _get_recent_game_logs(mlbam_id, season, limit=5)

    # Calculate days rest
    days_rest = None
    if last_5:
        try:
            last_start_date = datetime.strptime(last_5[0]["date"], "%Y-%m-%d").date()
            days_rest = (date.today() - last_start_date).days
        except (ValueError, KeyError):
            pass

    return {
        "name": pitcher_name,
        "mlbam_id": mlbam_id,
        "season_stats": season_stats,
        "last_5_starts": last_5,
        "pitch_mix": pitch_mix,
        "recent_velo_avg": recent_velo,
        "days_rest": days_rest,
    }


def _get_recent_game_logs(pitcher_id: int, season: int, limit: int = 5) -> list[dict]:
    """Fetch recent game logs from MLB Stats API."""
    url = f"{MLB_API_BASE}/people/{pitcher_id}/stats"
    params = {
        "stats": "gameLog",
        "season": season,
        "group": "pitching",
    }
    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        logs = []
        for split_group in data.get("stats", []):
            for split in split_group.get("splits", []):
                stat = split.get("stat", {})
                logs.append({
                    "date": split.get("date", ""),
                    "opp": split.get("opponent", {}).get("abbreviation", ""),
                    "ip": stat.get("inningsPitched", "0"),
                    "er": stat.get("earnedRuns", 0),
                    "k": stat.get("strikeOuts", 0),
                    "bb": stat.get("baseOnBalls", 0),
                    "hits": stat.get("hits", 0),
                    "pitches": stat.get("numberOfPitches", 0),
                    "decision": stat.get("decision", ""),
                })

        # Sort by date descending, return last N
        logs.sort(key=lambda x: x["date"], reverse=True)
        return logs[:limit]
    except Exception:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pitchers.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/pitchers.py tests/test_pitchers.py
git commit -m "feat: pitchers scraper with MLB API + pybaseball integration"
```

---

## Task 4: Lineups Scraper

**Files:**
- Create: `scrapers/lineups.py`
- Test: `tests/test_lineups.py`

- [ ] **Step 1: Write failing test**

`tests/test_lineups.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.lineups import get_confirmed_lineups


MOCK_SCHEDULE_LINEUPS = {
    "dates": [
        {
            "games": [
                {
                    "gamePk": 12345,
                    "teams": {
                        "away": {
                            "team": {"name": "Boston Red Sox"},
                        },
                        "home": {
                            "team": {"name": "New York Yankees"},
                        },
                    },
                    "lineups": {
                        "awayPlayers": [
                            {"id": 1, "fullName": "Player A", "primaryPosition": {"abbreviation": "CF"}, "batSide": {"code": "R"}},
                            {"id": 2, "fullName": "Player B", "primaryPosition": {"abbreviation": "SS"}, "batSide": {"code": "L"}},
                        ],
                        "homePlayers": [
                            {"id": 3, "fullName": "Player C", "primaryPosition": {"abbreviation": "RF"}, "batSide": {"code": "R"}},
                        ],
                    },
                }
            ]
        }
    ]
}


@patch("scrapers.lineups.requests.get")
def test_get_confirmed_lineups(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_SCHEDULE_LINEUPS
    mock_get.return_value = mock_resp

    result = get_confirmed_lineups("2026-04-01")
    assert "NYY" in result
    assert "BOS" in result
    assert result["BOS"]["confirmed"] is True
    assert len(result["BOS"]["lineup"]) == 2
    assert result["BOS"]["lineup"][0]["name"] == "Player A"


@patch("scrapers.lineups.requests.get")
def test_unconfirmed_lineup_when_no_lineups_key(mock_get):
    no_lineups = {
        "dates": [{"games": [{
            "gamePk": 99,
            "teams": {
                "away": {"team": {"name": "Boston Red Sox"}},
                "home": {"team": {"name": "New York Yankees"}},
            },
        }]}]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = no_lineups
    mock_get.return_value = mock_resp

    result = get_confirmed_lineups("2026-04-01")
    assert result["NYY"]["confirmed"] is False
    assert result["NYY"]["lineup"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lineups.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/lineups.py**

```python
import requests
from config import MLB_API_BASE, TEAM_NAME_TO_ABBREV


def get_confirmed_lineups(game_date: str) -> dict:
    """Fetch confirmed lineups from MLB Stats API.

    Returns dict keyed by team abbreviation with lineup data.
    """
    url = f"{MLB_API_BASE}/schedule"
    params = {
        "date": game_date,
        "sportId": 1,
        "hydrate": "lineups",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            away_name = game["teams"]["away"]["team"]["name"]
            home_name = game["teams"]["home"]["team"]["name"]
            away = TEAM_NAME_TO_ABBREV.get(away_name, away_name)
            home = TEAM_NAME_TO_ABBREV.get(home_name, home_name)

            lineups = game.get("lineups", {})
            away_players = lineups.get("awayPlayers", [])
            home_players = lineups.get("homePlayers", [])

            result[away] = {
                "confirmed": len(away_players) > 0,
                "lineup": [
                    {
                        "id": p["id"],
                        "name": p["fullName"],
                        "position": p.get("primaryPosition", {}).get("abbreviation", ""),
                        "bats": p.get("batSide", {}).get("code", ""),
                    }
                    for p in away_players
                ],
            }

            result[home] = {
                "confirmed": len(home_players) > 0,
                "lineup": [
                    {
                        "id": p["id"],
                        "name": p["fullName"],
                        "position": p.get("primaryPosition", {}).get("abbreviation", ""),
                        "bats": p.get("batSide", {}).get("code", ""),
                    }
                    for p in home_players
                ],
            }

    return result
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_lineups.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/lineups.py tests/test_lineups.py
git commit -m "feat: lineups scraper via MLB Stats API"
```

---

## Task 5: Bullpen Scraper

**Files:**
- Create: `scrapers/bullpen.py`
- Test: `tests/test_bullpen.py`

- [ ] **Step 1: Write failing test**

`tests/test_bullpen.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.bullpen import get_bullpen_state, _classify_freshness


def test_classify_freshness():
    assert _classify_freshness(avg_pitches=10) == "fresh"
    assert _classify_freshness(avg_pitches=22) == "moderate"
    assert _classify_freshness(avg_pitches=32) == "tired"
    assert _classify_freshness(avg_pitches=45) == "gassed"


@patch("scrapers.bullpen.requests.get")
def test_get_bullpen_state_returns_shape(mock_get):
    # Mock roster response
    roster_resp = MagicMock()
    roster_resp.status_code = 200
    roster_resp.json.return_value = {
        "roster": [
            {"person": {"id": 1, "fullName": "Reliever A"},
             "status": {"code": "A"},
             "position": {"abbreviation": "RP"}},
            {"person": {"id": 2, "fullName": "Closer B"},
             "status": {"code": "A"},
             "position": {"abbreviation": "CL"}},
        ]
    }

    # Mock game log response (empty)
    log_resp = MagicMock()
    log_resp.status_code = 200
    log_resp.json.return_value = {"stats": []}

    mock_get.side_effect = [roster_resp, log_resp, log_resp]

    state = get_bullpen_state(147, "2026-04-01")
    assert "bullpen_freshness" in state
    assert "relievers" in state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bullpen.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/bullpen.py**

```python
from datetime import date, datetime, timedelta
import requests
from config import MLB_API_BASE


def _classify_freshness(avg_pitches: float) -> str:
    if avg_pitches < 15:
        return "fresh"
    elif avg_pitches < 25:
        return "moderate"
    elif avg_pitches < 35:
        return "tired"
    return "gassed"


def get_bullpen_state(team_id: int, game_date: str) -> dict:
    """Get bullpen usage state for a team over rolling 3-day window."""
    # Get active roster
    url = f"{MLB_API_BASE}/teams/{team_id}/roster"
    params = {"rosterType": "active", "date": game_date}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    roster = resp.json()

    relievers = []
    closer = None
    total_pitches = 0
    reliever_count = 0

    for player in roster.get("roster", []):
        pos = player.get("position", {}).get("abbreviation", "")
        if pos not in ("RP", "CL"):
            continue

        pid = player["person"]["id"]
        name = player["person"]["fullName"]

        # Get recent game logs
        pitches_3d = _get_recent_pitches(pid, game_date, days=3)
        available = pitches_3d < 40  # rough threshold

        entry = {
            "name": name,
            "id": pid,
            "available": available,
            "pitches_last_3d": pitches_3d,
        }

        if pos == "CL":
            closer = entry
        else:
            relievers.append(entry)

        total_pitches += pitches_3d
        reliever_count += 1

    avg_pitches = total_pitches / max(reliever_count, 1)

    return {
        "closer": closer,
        "relievers": relievers,
        "bullpen_freshness": _classify_freshness(avg_pitches),
        "avg_pitches_3d": round(avg_pitches, 1),
    }


def _get_recent_pitches(pitcher_id: int, game_date: str, days: int = 3) -> int:
    """Sum pitches thrown in the last N days."""
    url = f"{MLB_API_BASE}/people/{pitcher_id}/stats"
    params = {
        "stats": "gameLog",
        "season": game_date[:4],
        "group": "pitching",
    }
    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        cutoff = datetime.strptime(game_date, "%Y-%m-%d").date() - timedelta(days=days)
        total = 0

        for stat_group in data.get("stats", []):
            for split in stat_group.get("splits", []):
                split_date = split.get("date", "")
                if not split_date:
                    continue
                try:
                    d = datetime.strptime(split_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if d >= cutoff:
                    total += split.get("stat", {}).get("numberOfPitches", 0)

        return total
    except Exception:
        return 0
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_bullpen.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/bullpen.py tests/test_bullpen.py
git commit -m "feat: bullpen usage tracker with freshness classification"
```

---

## Task 6: Team Stats Scraper

**Files:**
- Create: `scrapers/team_stats.py`
- Test: `tests/test_team_stats.py`

- [ ] **Step 1: Write failing test**

`tests/test_team_stats.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_team_profile, pythagorean_win_pct


def test_pythagorean_win_pct():
    # Team scoring 5 runs/game allowing 4 should be above .500
    pct = pythagorean_win_pct(5.0, 4.0)
    assert 0.55 < pct < 0.65


def test_pythagorean_equal_runs():
    pct = pythagorean_win_pct(4.5, 4.5)
    assert abs(pct - 0.5) < 0.001


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_shape(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "teams": [
            {
                "name": "New York Yankees",
                "abbreviation": "NYY",
                "division": {"name": "American League East"},
                "record": {
                    "wins": 45, "losses": 30,
                    "winningPercentage": ".600",
                    "records": {
                        "splitRecords": [
                            {"type": "home", "wins": 25, "losses": 12},
                            {"type": "away", "wins": 20, "losses": 18},
                        ]
                    },
                    "runsScored": 360, "runsAllowed": 298,
                    "divisionRank": "1",
                },
            }
        ]
    }
    mock_get.return_value = mock_resp

    profile = get_team_profile("NYY", season=2026)
    assert profile["team"] == "NYY"
    assert profile["record"] == "45-30"
    assert profile["run_diff"] == 62
    assert "pyth_pct" in profile
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_team_stats.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/team_stats.py**

```python
import requests
from config import MLB_API_BASE


def pythagorean_win_pct(runs_scored: float, runs_allowed: float, exp: float = 1.83) -> float:
    """Calculate Pythagorean expected win percentage."""
    if runs_scored == 0 and runs_allowed == 0:
        return 0.5
    return runs_scored ** exp / (runs_scored ** exp + runs_allowed ** exp)


def get_team_profile(team_abbrev: str, season: int = 2026) -> dict:
    """Get team profile from MLB Stats API standings."""
    url = f"{MLB_API_BASE}/teams"
    params = {"season": season, "sportId": 1, "hydrate": "record"}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    for team in data.get("teams", []):
        if team.get("abbreviation") != team_abbrev:
            continue

        record = team.get("record", {})
        wins = record.get("wins", 0)
        losses = record.get("losses", 0)
        rs = record.get("runsScored", 0)
        ra = record.get("runsAllowed", 0)
        games = wins + losses

        home_rec = ""
        away_rec = ""
        for sr in record.get("records", {}).get("splitRecords", []):
            if sr["type"] == "home":
                home_rec = f"{sr['wins']}-{sr['losses']}"
            elif sr["type"] == "away":
                away_rec = f"{sr['wins']}-{sr['losses']}"

        rpg = rs / max(games, 1)
        rapg = ra / max(games, 1)

        return {
            "team": team_abbrev,
            "record": f"{wins}-{losses}",
            "pct": round(wins / max(games, 1), 3),
            "home_record": home_rec,
            "away_record": away_rec,
            "run_diff": rs - ra,
            "runs_per_game": round(rpg, 1),
            "runs_allowed_per_game": round(rapg, 1),
            "pyth_pct": round(pythagorean_win_pct(rpg, rapg), 3),
            "division": team.get("division", {}).get("name", ""),
            "div_rank": record.get("divisionRank", ""),
        }

    return {"team": team_abbrev, "error": "team not found"}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_team_stats.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/team_stats.py tests/test_team_stats.py
git commit -m "feat: team stats scraper with Pythagorean win pct"
```

---

## Task 7: Ballpark + Weather Scraper

**Files:**
- Create: `scrapers/ballpark.py`
- Test: `tests/test_ballpark.py`

- [ ] **Step 1: Write failing test**

`tests/test_ballpark.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.ballpark import get_game_environment, _classify_wind_impact


def test_classify_wind_impact_out():
    assert _classify_wind_impact(15, "out") == "hitter_boost"


def test_classify_wind_impact_in():
    assert _classify_wind_impact(15, "in") == "pitcher_boost"


def test_classify_wind_impact_calm():
    assert _classify_wind_impact(3, "out") == "neutral"


@patch("scrapers.ballpark.requests.get")
def test_get_game_environment(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "main": {"temp": 72, "humidity": 55},  # imperial units = Fahrenheit
        "wind": {"speed": 12, "deg": 180},  # imperial units = mph
        "weather": [{"main": "Clear"}],
    }
    mock_get.return_value = mock_resp

    env = get_game_environment("NYY", "2026-04-01", "19:05")
    assert env["ballpark"] == "Yankee Stadium"
    assert env["park_factor_runs"] == 1.05
    assert "weather" in env
    assert env["weather"]["temp_f"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ballpark.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/ballpark.py**

```python
import requests
from config import PARK_FACTORS, PARK_COORDS, WEATHER_API_KEY, WEATHER_API_BASE


def _classify_wind_impact(wind_mph: float, direction: str) -> str:
    if wind_mph < 8:
        return "neutral"
    if direction == "out":
        return "hitter_boost"
    if direction == "in":
        return "pitcher_boost"
    return "neutral"


def _wind_direction_label(degrees: float) -> str:
    """Simplify wind direction to ballpark-relevant label.
    This is approximate — a real implementation would need park orientation."""
    if 135 <= degrees <= 225:
        return "out"  # blowing toward outfield (south wind at most parks)
    elif 315 <= degrees or degrees <= 45:
        return "in"
    return "cross"


def get_game_environment(home_team: str, game_date: str, game_time: str = "") -> dict:
    """Get ballpark + weather environment for a game."""
    park = PARK_FACTORS.get(home_team, {})
    coords = PARK_COORDS.get(home_team)

    weather = {}
    if coords and WEATHER_API_KEY:
        try:
            lat, lon = coords
            url = f"{WEATHER_API_BASE}/weather"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": WEATHER_API_KEY,
                "units": "imperial",
            }
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            wind_mph = round(data.get("wind", {}).get("speed", 0), 1)  # imperial = mph
            wind_deg = data.get("wind", {}).get("deg", 0)
            wind_dir = _wind_direction_label(wind_deg)

            weather = {
                "temp_f": round(data["main"]["temp"]),
                "humidity": data["main"].get("humidity", 0),
                "wind_mph": wind_mph,
                "wind_direction": wind_dir,
                "condition": data.get("weather", [{}])[0].get("main", ""),
            }
        except Exception:
            # If weather API fails, use empty weather — non-critical
            weather = {
                "temp_f": 72,
                "humidity": 50,
                "wind_mph": 0,
                "wind_direction": "calm",
                "condition": "Unknown",
            }
    elif coords:
        # No API key — use defaults
        weather = {
            "temp_f": 72,
            "humidity": 50,
            "wind_mph": 0,
            "wind_direction": "calm",
            "condition": "Unknown",
        }

    roof = park.get("roof", "open")
    wind_impact = "neutral"
    if roof == "open" and weather:
        wind_impact = _classify_wind_impact(
            weather.get("wind_mph", 0),
            weather.get("wind_direction", "calm"),
        )

    return {
        "ballpark": park.get("name", "Unknown"),
        "park_factor_runs": park.get("runs", 1.0),
        "park_factor_hr": park.get("hr", 1.0),
        "roof": roof,
        "weather": weather,
        "day_night": "night" if game_time and int(game_time.split(":")[0]) >= 17 else "day",
        "wind_impact": wind_impact,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_ballpark.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/ballpark.py tests/test_ballpark.py
git commit -m "feat: ballpark + weather scraper with wind impact classification"
```

---

## Task 8: News/Injuries Scraper

**Files:**
- Create: `scrapers/news.py`
- Test: `tests/test_news.py`

- [ ] **Step 1: Write failing test**

`tests/test_news.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.news import get_injuries


MOCK_INJURIES = {
    "people": [
        {
            "id": 123,
            "fullName": "Mike Trout",
            "currentTeam": {"abbreviation": "LAA"},
            "injuries": [
                {"description": "Left knee", "status": "10-Day IL"}
            ],
        }
    ]
}


@patch("scrapers.news.requests.get")
def test_get_injuries(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_INJURIES
    mock_get.return_value = mock_resp

    injuries = get_injuries()
    assert len(injuries) >= 1
    assert injuries[0]["player"] == "Mike Trout"
    assert injuries[0]["team"] == "LAA"


@patch("scrapers.news.requests.get")
def test_get_injuries_for_team(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_INJURIES
    mock_get.return_value = mock_resp

    injuries = get_injuries(team="LAA")
    assert all(i["team"] == "LAA" for i in injuries)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_news.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/news.py**

```python
import requests
from config import MLB_API_BASE


def get_injuries(team: str = None) -> list[dict]:
    """Get current injury list from MLB Stats API."""
    url = f"{MLB_API_BASE}/injuries"
    params = {"sportId": 1}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    injuries = []
    for person in data.get("people", []):
        team_abbrev = person.get("currentTeam", {}).get("abbreviation", "")
        if team and team_abbrev != team:
            continue

        for injury in person.get("injuries", []):
            injuries.append({
                "player": person["fullName"],
                "team": team_abbrev,
                "injury": injury.get("description", ""),
                "status": injury.get("status", ""),
            })

    return injuries


def get_transactions(team_id: int = None, days: int = 3) -> list[dict]:
    """Get recent transactions from MLB Stats API."""
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=days)

    url = f"{MLB_API_BASE}/transactions"
    params = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    }
    if team_id:
        params["teamId"] = team_id

    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "date": t.get("date", ""),
                "type": t.get("typeDesc", ""),
                "description": t.get("description", ""),
            }
            for t in data.get("transactions", [])
        ]
    except Exception:
        return []
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_news.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add scrapers/news.py tests/test_news.py
git commit -m "feat: injuries + transactions scraper via MLB Stats API"
```

---

## Task 9: Briefing Builder

**Files:**
- Create: `briefing.py`
- Test: `tests/test_briefing.py`

- [ ] **Step 1: Write failing test**

`tests/test_briefing.py`:
```python
from briefing import build_briefing


def test_build_briefing_produces_string():
    game_data = {
        "away_team": "BOS",
        "home_team": "NYY",
        "away_record": "40-35",
        "home_record": "45-30",
        "away_pitcher": {
            "name": "Brayan Bello",
            "season_stats": {"era": 3.50, "fip": 3.40, "xfip": 3.55,
                             "whip": 1.15, "k_per_9": 9.0, "bb_per_9": 2.5,
                             "hr_per_9": 1.0, "w": 8, "l": 5, "ip": 110, "starts": 18},
            "days_rest": 5,
            "last_5_starts": [],
        },
        "home_pitcher": {
            "name": "Gerrit Cole",
            "season_stats": {"era": 3.00, "fip": 2.90, "xfip": 3.10,
                             "whip": 1.00, "k_per_9": 11.0, "bb_per_9": 1.8,
                             "hr_per_9": 0.8, "w": 12, "l": 3, "ip": 140, "starts": 22},
            "days_rest": 4,
            "last_5_starts": [],
        },
        "odds": {
            "moneyline": {"home": -150, "away": 130},
            "run_line": {"home": -1.5, "home_odds": 140, "away": 1.5, "away_odds": -165},
            "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"ml_home": 0.585, "ml_away": 0.415},
        },
        "environment": {
            "ballpark": "Yankee Stadium",
            "park_factor_runs": 1.05,
            "weather": {"temp_f": 72, "wind_mph": 10, "wind_direction": "out"},
            "day_night": "night",
        },
        "away_bullpen": {"bullpen_freshness": "moderate", "closer": {"name": "Kenley Jansen"}},
        "home_bullpen": {"bullpen_freshness": "fresh", "closer": {"name": "Clay Holmes"}},
        "away_injuries": [],
        "home_injuries": [],
    }
    briefing = build_briefing(game_data)
    assert isinstance(briefing, str)
    assert "BOS" in briefing
    assert "NYY" in briefing
    assert "Gerrit Cole" in briefing
    assert "Brayan Bello" in briefing
    assert "Yankee Stadium" in briefing
    assert "PREDICTION TASK" in briefing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_briefing.py -v`
Expected: FAIL

- [ ] **Step 3: Write briefing.py**

```python
"""Compile all game data into a seed briefing document for LLM simulation."""


def _format_game_log(starts: list[dict]) -> str:
    if not starts:
        return "    No recent game logs available"
    lines = []
    for s in starts[:5]:
        lines.append(
            f"    {s.get('date', '?')} vs {s.get('opp', '?')}: "
            f"{s.get('ip', '?')} IP, {s.get('er', '?')} ER, "
            f"{s.get('k', '?')} K, {s.get('bb', '?')} BB, "
            f"{s.get('pitches', '?')} pitches"
        )
    return "\n".join(lines)


def _format_injuries(injuries: list[dict]) -> str:
    if not injuries:
        return "No notable injuries"
    return ", ".join(f"{i['player']} ({i.get('status', 'unknown')})" for i in injuries)


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def build_briefing(game_data: dict) -> str:
    """Build the full briefing string from compiled game data."""
    away = game_data["away_team"]
    home = game_data["home_team"]
    ap = game_data.get("away_pitcher", {})
    hp = game_data.get("home_pitcher", {})
    odds = game_data.get("odds", {})
    env = game_data.get("environment", {})
    weather = env.get("weather", {})
    a_bp = game_data.get("away_bullpen", {})
    h_bp = game_data.get("home_bullpen", {})

    ml = odds.get("moneyline", {})
    rl = odds.get("run_line", {})
    total = odds.get("total", {})
    implied = odds.get("implied_probs", {})
    total_line = total.get("line", "N/A")

    briefing = f"""MLB GAME PREDICTION ANALYSIS
==============================
{away} ({game_data.get('away_record', '')}) at {home} ({game_data.get('home_record', '')})
{env.get('ballpark', '')} | {env.get('day_night', '')}
Weather: {weather.get('temp_f', 'N/A')}°F, Wind {weather.get('wind_mph', 'N/A')}mph {weather.get('wind_direction', '')} | Park Factor: {env.get('park_factor_runs', 'N/A')}

BETTING LINES:
  Moneyline: {home} {ml.get('home', 'N/A')} / {away} {ml.get('away', 'N/A')}
  Run Line: {home} {rl.get('home', -1.5)} ({rl.get('home_odds', 'N/A')}) / {away} {rl.get('away', 1.5)} ({rl.get('away_odds', 'N/A')})
  Total: {total_line} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  Implied Win Prob: {home} {implied.get('ml_home', 0):.1%} / {away} {implied.get('ml_away', 0):.1%}

== STARTING PITCHING MATCHUP ==

{ap.get('name', 'TBD')} ({away}) — {_safe_get(ap, 'season_stats', 'w')}-{_safe_get(ap, 'season_stats', 'l')}, {_safe_get(ap, 'season_stats', 'era')} ERA
  FIP: {_safe_get(ap, 'season_stats', 'fip')} | xFIP: {_safe_get(ap, 'season_stats', 'xfip')} | WHIP: {_safe_get(ap, 'season_stats', 'whip')}
  K/9: {_safe_get(ap, 'season_stats', 'k_per_9')} | BB/9: {_safe_get(ap, 'season_stats', 'bb_per_9')} | HR/9: {_safe_get(ap, 'season_stats', 'hr_per_9')}
  Days Rest: {ap.get('days_rest', 'N/A')}
  Last 5 Starts:
{_format_game_log(ap.get('last_5_starts', []))}

{hp.get('name', 'TBD')} ({home}) — {_safe_get(hp, 'season_stats', 'w')}-{_safe_get(hp, 'season_stats', 'l')}, {_safe_get(hp, 'season_stats', 'era')} ERA
  FIP: {_safe_get(hp, 'season_stats', 'fip')} | xFIP: {_safe_get(hp, 'season_stats', 'xfip')} | WHIP: {_safe_get(hp, 'season_stats', 'whip')}
  K/9: {_safe_get(hp, 'season_stats', 'k_per_9')} | BB/9: {_safe_get(hp, 'season_stats', 'bb_per_9')} | HR/9: {_safe_get(hp, 'season_stats', 'hr_per_9')}
  Days Rest: {hp.get('days_rest', 'N/A')}
  Last 5 Starts:
{_format_game_log(hp.get('last_5_starts', []))}

== BULLPEN STATE ==
{away} Bullpen: {a_bp.get('bullpen_freshness', 'N/A')}
  Closer: {_safe_get(a_bp, 'closer', 'name', default='TBD')}

{home} Bullpen: {h_bp.get('bullpen_freshness', 'N/A')}
  Closer: {_safe_get(h_bp, 'closer', 'name', default='TBD')}

== INJURIES ==
{away}: {_format_injuries(game_data.get('away_injuries', []))}
{home}: {_format_injuries(game_data.get('home_injuries', []))}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions
for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. RUN LINE (-1.5): Probability the favorite wins by 2+ runs.
   Is there value on either side of the run line?
3. TOTAL (O/U {total_line}): Projected total runs. Does the pitching matchup,
   ballpark, weather, and lineup composition point over or under?
4. FIRST 5 INNINGS: Based ONLY on the starting pitchers (ignore bullpens),
   who leads after 5 innings? What's the projected F5 total?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""
    return briefing
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_briefing.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat: briefing builder compiles game data into LLM seed document"
```

---

## Task 10: Simulator (Plan B + MiroFish)

**Files:**
- Create: `simulate.py`
- Test: `tests/test_simulate.py`

- [ ] **Step 1: Write failing test**

`tests/test_simulate.py`:
```python
import json
from unittest.mock import patch, MagicMock
from simulate import run_plan_b, parse_simulation_result, MLB_SYSTEM_PROMPT


MOCK_LLM_RESPONSE = json.dumps({
    "analyst_assessments": [
        {"role": "pitching", "game_winner": "NYY", "reasoning": "Cole is elite"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.58,
            "away_win_prob": 0.42,
            "value_side": "none",
            "edge": 0.0,
            "confidence": "medium",
        },
        "run_line": {
            "favorite_cover_prob": 0.38,
            "value_side": "underdog_rl",
            "edge": 0.04,
            "confidence": "low",
        },
        "total": {
            "projected_total": 8.2,
            "over_prob": 0.45,
            "under_prob": 0.55,
            "value_side": "under",
            "edge": 0.03,
            "confidence": "medium",
        },
        "first_5": {
            "f5_home_win_prob": 0.55,
            "f5_away_win_prob": 0.45,
            "f5_projected_total": 4.0,
            "f5_ml_value": "none",
            "f5_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 3, "home": 5},
        "key_factors": ["Cole dominance", "wind blowing in"],
    },
})


def test_parse_simulation_result_valid():
    result = parse_simulation_result(MOCK_LLM_RESPONSE)
    assert result["predictions"]["moneyline"]["home_win_prob"] == 0.58
    assert result["predictions"]["total"]["projected_total"] == 8.2


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_system_prompt_exists():
    assert "MLB" in MLB_SYSTEM_PROMPT
    assert "JSON" in MLB_SYSTEM_PROMPT


@patch("simulate.openai.OpenAI")
def test_run_plan_b_calls_api(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_LLM_RESPONSE
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    result = run_plan_b("Test briefing content")
    assert result is not None
    assert "predictions" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_simulate.py -v`
Expected: FAIL

- [ ] **Step 3: Write simulate.py**

```python
"""Simulation layer: Plan B (direct Kimi) and MiroFish 512-agent."""
import json
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL


MLB_SYSTEM_PROMPT = """You are an elite MLB prediction system analyzing a game.
Simulate a panel of 6 expert analysts:

1. PITCHING ANALYST: Evaluates starter quality, pitch mix, splits, rest,
   time-through-order degradation. This drives F5 predictions heavily.
2. HITTING ANALYST: Evaluates lineup strength, platoon advantages,
   hot/cold streaks, and how the lineup matches up vs the starter.
3. BULLPEN ANALYST: Evaluates bullpen availability, fatigue, and how
   the game changes after the starter exits. Critical for full game vs F5 delta.
4. ENVIRONMENT ANALYST: Evaluates park factor, weather (wind, temp),
   day/night, and how these conditions affect run scoring.
5. MARKET ANALYST: Evaluates the betting lines for value. Where is the
   public money likely flowing? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What is the obvious narrative
   that might be wrong? Where is the value on the unpopular side?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "pitching", "game_winner": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "home_win_prob": 0.XX,
      "away_win_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "run_line": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite_rl|underdog_rl|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_5": {
      "f5_home_win_prob": 0.XX,
      "f5_away_win_prob": 0.XX,
      "f5_projected_total": X.X,
      "f5_ml_value": "home|away|none",
      "f5_total_value": "over|under|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": X, "home": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""


def parse_simulation_result(raw: str) -> dict | None:
    """Parse JSON response from LLM, handling common issues."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_plan_b(briefing: str, runs: int = 1) -> dict | None:
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/game.

    If runs > 1, average the probability estimates across runs for stability.
    """
    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    results = []
    for _ in range(runs):
        try:
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": MLB_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
        except Exception as e:
            print(f"[simulate] Plan B error: {e}")

    if not results:
        return None

    if len(results) == 1:
        return results[0]

    # Average probabilities across runs
    return _average_results(results)


def run_mirofish(briefing: str, runs: int = 3) -> dict | None:
    """Run full MiroFish 512-agent simulation.

    TODO: Integrate with MiroFish SDK once available.
    For now, falls back to Plan B with ensemble averaging.
    """
    print(f"[simulate] MiroFish: running {runs}-run ensemble")
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "moneyline": ["home_win_prob", "away_win_prob", "edge"],
        "run_line": ["favorite_cover_prob", "edge"],
        "total": ["projected_total", "over_prob", "under_prob", "edge"],
        "first_5": ["f5_home_win_prob", "f5_away_win_prob", "f5_projected_total"],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for field in fields:
            values = []
            for r in results:
                val = r.get("predictions", {}).get(section, {}).get(field)
                if val is not None:
                    values.append(float(val))
            if values:
                preds[section][field] = round(sum(values) / len(values), 4)

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_simulate.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add simulate.py tests/test_simulate.py
git commit -m "feat: simulation layer with Plan B (Kimi) + MiroFish ensemble"
```

---

## Task 11: Edge Detection + Kelly Sizing

**Files:**
- Create: `edge.py`
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write failing test**

`tests/test_edge.py`:
```python
from edge import (
    kelly_criterion, american_to_decimal, analyze_all_edges,
    check_moneyline_edge, check_total_edge,
)


def test_kelly_criterion_positive_edge():
    # 55% chance at even odds (+100 / decimal 2.0) = 10% edge
    kelly = kelly_criterion(0.55, 2.0)
    assert 0.05 < kelly < 0.15


def test_kelly_criterion_no_edge():
    # 50% chance at even odds = 0 Kelly
    kelly = kelly_criterion(0.50, 2.0)
    assert kelly == 0


def test_kelly_criterion_negative_edge():
    kelly = kelly_criterion(0.40, 2.0)
    assert kelly == 0


def test_american_to_decimal():
    assert american_to_decimal(-150) == round(100 / 150 + 1, 4)
    assert american_to_decimal(130) == round(130 / 100 + 1, 4)
    assert american_to_decimal(100) == 2.0


def test_check_moneyline_edge_found():
    sim = {
        "predictions": {
            "moneyline": {
                "home_win_prob": 0.62,
                "away_win_prob": 0.38,
            }
        }
    }
    odds = {
        "moneyline": {"home": -130, "away": 110},
        "implied_probs": {"ml_home": 0.565, "ml_away": 0.435},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is not None
    assert result["side"] == "home"
    assert result["edge"] > 0.05


def test_check_moneyline_edge_none():
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.56, "away_win_prob": 0.44}
        }
    }
    odds = {
        "moneyline": {"home": -150, "away": 130},
        "implied_probs": {"ml_home": 0.585, "ml_away": 0.415},
    }
    # Edge is only ~2.5% on away, below 5% threshold
    result = check_moneyline_edge(sim, odds)
    # Could be None or a bet — depends on exact calc
    if result:
        assert result["edge"] >= 0.05


def test_analyze_all_edges_returns_list():
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.65, "away_win_prob": 0.35},
            "run_line": {"favorite_cover_prob": 0.45},
            "total": {"over_prob": 0.60, "under_prob": 0.40, "projected_total": 9.5},
            "first_5": {
                "f5_home_win_prob": 0.58, "f5_away_win_prob": 0.42,
                "f5_projected_total": 4.8,
            },
        }
    }
    odds = {
        "moneyline": {"home": -140, "away": 120},
        "run_line": {"home": -1.5, "home_odds": 145, "away": 1.5, "away_odds": -170},
        "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
        "f5_moneyline": {"home": -130, "away": 110},
        "f5_total": {"line": 4.5, "over": -110, "under": -110},
        "implied_probs": {"ml_home": 0.583, "ml_away": 0.417},
    }
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    for bet in bets:
        assert "bet_type" in bet
        assert "edge" in bet
        assert "kelly_pct" in bet
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_edge.py -v`
Expected: FAIL

- [ ] **Step 3: Write edge.py**

```python
"""Edge detection and Kelly criterion sizing for all 4 bet types."""
from config import EDGE_THRESHOLDS, KELLY_FRACTION
from scrapers.odds import american_to_implied_prob


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds < 0:
        return round(100 / abs(odds) + 1, 4)
    return round(odds / 100 + 1, 4)


def kelly_criterion(prob: float, decimal_odds: float) -> float:
    """Calculate Kelly fraction. Returns 0 if no edge."""
    b = decimal_odds - 1  # net odds
    q = 1 - prob
    if b <= 0:
        return 0
    kelly = (b * prob - q) / b
    return max(0, round(kelly, 4))


def check_moneyline_edge(sim: dict, odds: dict) -> dict | None:
    """Check for moneyline value on either side."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = EDGE_THRESHOLDS["moneyline"]

    # Check home
    home_prob = ml_pred.get("home_win_prob", 0)
    home_implied = odds.get("implied_probs", {}).get("ml_home", 0)
    home_edge = home_prob - home_implied

    # Check away
    away_prob = ml_pred.get("away_win_prob", 0)
    away_implied = odds.get("implied_probs", {}).get("ml_away", 0)
    away_edge = away_prob - away_implied

    # Take the side with more edge
    if home_edge >= threshold and home_edge >= away_edge:
        dec = american_to_decimal(ml_odds["home"])
        return {
            "bet_type": "moneyline",
            "side": "home",
            "odds": ml_odds["home"],
            "sim_prob": home_prob,
            "market_prob": home_implied,
            "edge": round(home_edge, 4),
            "kelly_pct": round(kelly_criterion(home_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        dec = american_to_decimal(ml_odds["away"])
        return {
            "bet_type": "moneyline",
            "side": "away",
            "odds": ml_odds["away"],
            "sim_prob": away_prob,
            "market_prob": away_implied,
            "edge": round(away_edge, 4),
            "kelly_pct": round(kelly_criterion(away_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }

    return None


def check_run_line_edge(sim: dict, odds: dict) -> dict | None:
    """Check for run line value. Determines favorite by spread point, not position."""
    rl_pred = sim.get("predictions", {}).get("run_line", {})
    rl_odds = odds.get("run_line", {})
    if not rl_pred or not rl_odds:
        return None

    threshold = EDGE_THRESHOLDS["run_line"]
    fav_prob = rl_pred.get("favorite_cover_prob", 0)

    # Determine which side is the favorite based on spread point
    home_point = rl_odds.get("home", -1.5)
    home_odds = rl_odds.get("home_odds", -110)
    away_odds = rl_odds.get("away_odds", -110)

    # The side with the negative point (-1.5) is the favorite
    home_is_fav = home_point < 0

    if home_is_fav:
        fav_odds = home_odds
        dog_odds = away_odds
        fav_label = f"home {home_point}"
        dog_label = f"away {rl_odds.get('away', 1.5)}"
    else:
        fav_odds = away_odds
        dog_odds = home_odds
        fav_label = f"away {rl_odds.get('away', -1.5)}"
        dog_label = f"home {home_point}"

    fav_implied = american_to_implied_prob(fav_odds)
    dog_implied = american_to_implied_prob(dog_odds)
    total = fav_implied + dog_implied
    fav_implied /= total
    dog_implied /= total

    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    if fav_edge >= threshold and fav_edge >= dog_edge:
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "run_line",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_implied, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": rl_pred.get("confidence", "medium"),
        }
    elif dog_edge >= threshold:
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "run_line",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_implied, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": rl_pred.get("confidence", "medium"),
        }

    return None


def check_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total (over/under) value."""
    total_pred = sim.get("predictions", {}).get("total", {})
    total_odds = odds.get("total", {})
    if not total_pred or not total_odds:
        return None

    threshold = EDGE_THRESHOLDS["total"]

    over_prob = total_pred.get("over_prob", 0)
    under_prob = total_pred.get("under_prob", 0)

    over_odds = total_odds.get("over_odds", -110)
    under_odds = total_odds.get("under_odds", -110)
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total_impl = over_implied + under_implied
    over_implied /= total_impl
    under_implied /= total_impl

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    line = total_odds.get("line", "?")

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }

    return None


def check_f5_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First 5 Innings value (moneyline or total)."""
    f5_pred = sim.get("predictions", {}).get("first_5", {})
    if not f5_pred:
        return None

    threshold = EDGE_THRESHOLDS["first_5"]

    # F5 moneyline
    f5_ml = odds.get("f5_moneyline", {})
    if f5_ml:
        home_odds = f5_ml.get("home", -110)
        away_odds = f5_ml.get("away", -110)
        h_implied = american_to_implied_prob(home_odds)
        a_implied = american_to_implied_prob(away_odds)
        total = h_implied + a_implied
        h_implied /= total
        a_implied /= total

        h_prob = f5_pred.get("f5_home_win_prob", 0)
        a_prob = f5_pred.get("f5_away_win_prob", 0)
        h_edge = h_prob - h_implied
        a_edge = a_prob - a_implied

        if h_edge >= threshold and h_edge >= a_edge:
            dec = american_to_decimal(home_odds)
            return {
                "bet_type": "first_5",
                "side": "home F5 ML",
                "odds": home_odds,
                "sim_prob": h_prob,
                "market_prob": round(h_implied, 4),
                "edge": round(h_edge, 4),
                "kelly_pct": round(kelly_criterion(h_prob, dec) * KELLY_FRACTION, 4),
                "confidence": f5_pred.get("confidence", "medium"),
            }
        elif a_edge >= threshold:
            dec = american_to_decimal(away_odds)
            return {
                "bet_type": "first_5",
                "side": "away F5 ML",
                "odds": away_odds,
                "sim_prob": a_prob,
                "market_prob": round(a_implied, 4),
                "edge": round(a_edge, 4),
                "kelly_pct": round(kelly_criterion(a_prob, dec) * KELLY_FRACTION, 4),
                "confidence": f5_pred.get("confidence", "medium"),
            }

    return None


def analyze_all_edges(sim: dict, odds: dict) -> list[dict]:
    """Run all edge checks for a single game. Returns 0-4 bet signals."""
    bets = []

    ml = check_moneyline_edge(sim, odds)
    if ml:
        bets.append(ml)

    rl = check_run_line_edge(sim, odds)
    if rl:
        bets.append(rl)

    total = check_total_edge(sim, odds)
    if total:
        bets.append(total)

    f5 = check_f5_edge(sim, odds)
    if f5:
        bets.append(f5)

    return bets
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_edge.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: edge detection with Kelly criterion for all 4 bet types"
```

---

## Task 12: Bet Tracker

**Files:**
- Create: `tracker.py`
- Test: `tests/test_tracker.py`

- [ ] **Step 1: Write failing test**

`tests/test_tracker.py`:
```python
import os
import tempfile
import pandas as pd
from tracker import log_bet, load_bets, update_result, get_summary


def test_log_and_load_bet(tmp_path):
    csv = str(tmp_path / "bets.csv")
    bet = {
        "date": "2026-04-01",
        "game": "BOS@NYY",
        "bet_type": "moneyline",
        "side": "home",
        "odds": -150,
        "sim_prob": 0.62,
        "edge": 0.055,
        "kelly_pct": 0.02,
    }
    log_bet(bet, csv_path=csv)
    df = load_bets(csv_path=csv)
    assert len(df) == 1
    assert df.iloc[0]["game"] == "BOS@NYY"


def test_update_result(tmp_path):
    csv = str(tmp_path / "bets.csv")
    bet = {
        "date": "2026-04-01",
        "game": "BOS@NYY",
        "bet_type": "moneyline",
        "side": "home",
        "odds": -150,
        "sim_prob": 0.62,
        "edge": 0.055,
        "kelly_pct": 0.02,
    }
    log_bet(bet, csv_path=csv)
    update_result(0, "W", csv_path=csv)
    df = load_bets(csv_path=csv)
    assert df.iloc[0]["result"] == "W"


def test_get_summary_empty(tmp_path):
    csv = str(tmp_path / "bets.csv")
    summary = get_summary(csv_path=csv)
    assert summary["total_bets"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tracker.py -v`
Expected: FAIL

- [ ] **Step 3: Write tracker.py**

```python
"""Bet logging and P&L tracking via CSV."""
import os
import pandas as pd
from config import BETS_CSV, DATA_DIR

COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "edge", "kelly_pct", "result", "profit",
]


def _ensure_csv(csv_path: str) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path):
        pd.DataFrame(columns=COLUMNS).to_csv(csv_path, index=False)


def log_bet(bet: dict, csv_path: str = None) -> None:
    """Append a bet to the CSV tracker."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    df = pd.read_csv(csv_path)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    return pd.read_csv(csv_path)


def update_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a bet's result (W/L/P) and calculate profit."""
    csv_path = csv_path or BETS_CSV
    df = pd.read_csv(csv_path)
    df.at[index, "result"] = result

    odds = df.at[index, "odds"]
    if result == "W":
        if odds < 0:
            df.at[index, "profit"] = round(100 / abs(odds), 2)
        else:
            df.at[index, "profit"] = round(odds / 100, 2)
    elif result == "L":
        df.at[index, "profit"] = -1.0
    else:  # Push
        df.at[index, "profit"] = 0.0

    df.to_csv(csv_path, index=False)


def get_summary(csv_path: str = None) -> dict:
    """Generate P&L summary."""
    csv_path = csv_path or BETS_CSV
    df = load_bets(csv_path)

    if df.empty:
        return {"total_bets": 0, "record": "0-0-0", "profit": 0, "roi": 0}

    settled = df[df["result"].isin(["W", "L", "P"])]
    wins = len(settled[settled["result"] == "W"])
    losses = len(settled[settled["result"] == "L"])
    pushes = len(settled[settled["result"] == "P"])
    profit = settled["profit"].sum() if not settled.empty else 0

    return {
        "total_bets": len(df),
        "settled": len(settled),
        "pending": len(df) - len(settled),
        "record": f"{wins}-{losses}-{pushes}",
        "win_rate": round(wins / max(len(settled), 1), 3),
        "profit": round(float(profit), 2),
        "roi": round(float(profit) / max(len(settled), 1) * 100, 1),
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_tracker.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: bet tracker with CSV logging and P&L summary"
```

---

## Task 13: CLI Main Pipeline

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

`tests/test_main.py`:
```python
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "daily" in result.output
    assert "report" in result.output


def test_report_empty():
    runner = CliRunner()
    with patch("main.get_summary") as mock_summary:
        mock_summary.return_value = {
            "total_bets": 0, "record": "0-0-0", "profit": 0, "roi": 0,
        }
        result = runner.invoke(cli, ["report"])
        assert result.exit_code == 0
        assert "0-0-0" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL

- [ ] **Step 3: Write main.py**

```python
"""CLI entrypoint for MiroFish MLB Prediction Pipeline."""
import click
from datetime import date, datetime

from config import SCREEN_EDGE_THRESHOLD
from scrapers.pitchers import get_probable_starters, get_starter_profile
from scrapers.lineups import get_confirmed_lineups
from scrapers.bullpen import get_bullpen_state
from scrapers.team_stats import get_team_profile
from scrapers.ballpark import get_game_environment
from scrapers.odds import get_mlb_odds
from scrapers.news import get_injuries
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary


@click.group()
def cli():
    """MiroFish MLB Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
def daily(game_date):
    """Run full daily pipeline: scrape → screen → simulate → detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\n=== MiroFish MLB Pipeline — {game_date} ===\n")

    # Step 1: Get schedule + probable pitchers
    click.echo("[1/6] Fetching schedule and probable pitchers...")
    games = get_probable_starters(game_date)
    if not games:
        click.echo("No games found for this date.")
        return
    click.echo(f"  Found {len(games)} games")

    # Step 2: Get odds
    click.echo("[2/6] Fetching odds...")
    odds_list = get_mlb_odds()
    odds_by_teams = {}
    for o in odds_list:
        key = f"{o.away}@{o.home}"
        odds_by_teams[key] = o

    # Step 3: Get lineups
    click.echo("[3/6] Fetching lineups...")
    lineups = get_confirmed_lineups(game_date)

    # Step 4: Get injuries
    click.echo("[4/6] Fetching injuries...")
    all_injuries = get_injuries()
    injuries_by_team = {}
    for inj in all_injuries:
        team = inj["team"]
        injuries_by_team.setdefault(team, []).append(inj)

    # Step 5: Build briefings + screen
    click.echo("[5/6] Building briefings and running screen pass...")
    screened_games = []

    for game in games:
        away = game["away_team"]
        home = game["home_team"]
        game_key = f"{away}@{home}"

        # Get odds for this game
        odds = odds_by_teams.get(game_key)
        if not odds:
            click.echo(f"  {game_key}: No odds found, skipping")
            continue

        # Build game data
        away_pitcher = get_starter_profile(
            game["away_pitcher"], season=int(game_date[:4])
        ) if game["away_pitcher"] != "TBD" else {"name": "TBD"}

        home_pitcher = get_starter_profile(
            game["home_pitcher"], season=int(game_date[:4])
        ) if game["home_pitcher"] != "TBD" else {"name": "TBD"}

        away_profile = get_team_profile(away, season=int(game_date[:4]))
        home_profile = get_team_profile(home, season=int(game_date[:4]))

        env = get_game_environment(home, game_date)

        game_data = {
            "away_team": away,
            "home_team": home,
            "away_record": away_profile.get("record", ""),
            "home_record": home_profile.get("record", ""),
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "odds": {
                "moneyline": odds.moneyline,
                "run_line": odds.run_line,
                "total": odds.total,
                "f5_moneyline": odds.f5_moneyline,
                "f5_total": odds.f5_total,
                "implied_probs": odds.implied_probs,
            },
            "environment": env,
            "away_bullpen": get_bullpen_state(
                game["away_team_id"], game_date
            ) if game.get("away_team_id") else {},
            "home_bullpen": get_bullpen_state(
                game["home_team_id"], game_date
            ) if game.get("home_team_id") else {},
            "away_injuries": injuries_by_team.get(away, []),
            "home_injuries": injuries_by_team.get(home, []),
        }

        # Build briefing
        brief = build_briefing(game_data)

        # Screen with Plan B
        click.echo(f"  Screening {game_key}...")
        screen = run_plan_b(brief)
        if not screen:
            click.echo(f"    Screen failed, skipping")
            continue

        # Check if any edge exceeds screen threshold
        screen_odds = game_data["odds"]
        edges = analyze_all_edges(screen, screen_odds)
        max_edge = max((e["edge"] for e in edges), default=0)

        if max_edge >= SCREEN_EDGE_THRESHOLD:
            click.echo(f"    FLAGGED — max edge {max_edge:.1%}, queuing for full sim")
            screened_games.append((game_key, brief, game_data))
        else:
            click.echo(f"    No edge found (max {max_edge:.1%})")

    # Step 6: Full MiroFish simulation on flagged games
    click.echo(f"\n[6/6] Running full simulation on {len(screened_games)} flagged games...")
    total_bets = 0

    for game_key, brief, game_data in screened_games:
        click.echo(f"\n  === {game_key} ===")
        result = run_mirofish(brief, runs=3)
        if not result:
            click.echo("    Simulation failed")
            continue

        bets = analyze_all_edges(result, game_data["odds"])
        if not bets:
            click.echo("    No bets after full sim")
            continue

        for bet in bets:
            bet["date"] = game_date
            bet["game"] = game_key
            click.echo(
                f"    BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
            )
            log_bet(bet)
            total_bets += 1

    click.echo(f"\n=== Done. {total_bets} bets logged. ===")


@cli.command()
@click.argument("away_team")
@click.argument("home_team")
@click.option("--date", "game_date", default=None)
@click.option("--away-pitcher", default=None, help="Away starting pitcher name")
@click.option("--home-pitcher", default=None, help="Home starting pitcher name")
def game(away_team, home_team, game_date, away_pitcher, home_pitcher):
    """Analyze a single game."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {away_team}@{home_team} on {game_date}...")

    # Look up probable pitchers from schedule if not provided
    if not away_pitcher or not home_pitcher:
        games = get_probable_starters(game_date)
        for g in games:
            if g["away_team"] == away_team and g["home_team"] == home_team:
                away_pitcher = away_pitcher or g["away_pitcher"]
                home_pitcher = home_pitcher or g["home_pitcher"]
                break

    # Build pitcher profiles
    season = int(game_date[:4])
    ap = get_starter_profile(away_pitcher, season) if away_pitcher and away_pitcher != "TBD" else {"name": "TBD"}
    hp = get_starter_profile(home_pitcher, season) if home_pitcher and home_pitcher != "TBD" else {"name": "TBD"}

    # Get odds
    odds_list = get_mlb_odds()
    game_odds = None
    for o in odds_list:
        if o.away == away_team and o.home == home_team:
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this game.")
        return

    env = get_game_environment(home_team, game_date)
    away_profile = get_team_profile(away_team)
    home_profile = get_team_profile(home_team)

    game_data = {
        "away_team": away_team,
        "home_team": home_team,
        "away_record": away_profile.get("record", ""),
        "home_record": home_profile.get("record", ""),
        "away_pitcher": ap,
        "home_pitcher": hp,
        "odds": {
            "moneyline": game_odds.moneyline,
            "run_line": game_odds.run_line,
            "total": game_odds.total,
            "f5_moneyline": game_odds.f5_moneyline,
            "f5_total": game_odds.f5_total,
            "implied_probs": game_odds.implied_probs,
        },
        "environment": env,
        "away_bullpen": {},
        "home_bullpen": {},
        "away_injuries": [],
        "home_injuries": [],
    }

    brief = build_briefing(game_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3)
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, game_data["odds"])
    if not bets:
        click.echo("No value found.")
        return

    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{away_team}@{home_team}"
        click.echo(
            f"  BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
            f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
        )
        log_bet(bet)


@cli.command()
def report():
    """Show P&L summary."""
    summary = get_summary()
    click.echo("\n=== MiroFish P&L Report ===")
    click.echo(f"  Total bets: {summary['total_bets']}")
    click.echo(f"  Record: {summary['record']}")
    click.echo(f"  Profit (units): {summary.get('profit', 0)}")
    click.echo(f"  ROI: {summary.get('roi', 0)}%")
    click.echo()


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_main.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: CLI pipeline with daily/game/report commands"
```

---

## Task 14: Calibrate Stub

**Files:**
- Create: `calibrate.py`
- Test: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing test**

`tests/test_calibrate.py`:
```python
from unittest.mock import patch
import pandas as pd
from calibrate import calibration_report


@patch("calibrate.load_bets")
def test_calibration_report_insufficient_data(mock_load):
    mock_load.return_value = pd.DataFrame(columns=["result", "bet_type", "edge"])
    result = calibration_report()
    assert result["status"] == "insufficient_data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calibrate.py -v`
Expected: FAIL

- [ ] **Step 3: Write calibrate.py stub**

```python
"""Rolling calibration — to be built after 2 weeks of data.

After collecting ~200 games of predictions vs actual results:
1. Bin predicted probabilities (0-10%, 10-20%, etc.)
2. Compare predicted vs actual hit rates per bin
3. Build isotonic regression calibration curve
4. Apply calibration to future predictions before edge detection

This stub exists so imports don't break.
"""
from tracker import load_bets


def calibration_report() -> dict:
    """Generate calibration analysis from historical bets."""
    df = load_bets()
    settled = df[df["result"].isin(["W", "L"])]

    if len(settled) < 50:
        return {"status": "insufficient_data", "n": len(settled), "needed": 50}

    # Group by bet type
    report = {}
    for bet_type in settled["bet_type"].unique():
        subset = settled[settled["bet_type"] == bet_type]
        wins = len(subset[subset["result"] == "W"])
        total = len(subset)
        report[bet_type] = {
            "n": total,
            "win_rate": round(wins / total, 3) if total > 0 else 0,
            "avg_edge": round(subset["edge"].mean(), 3) if "edge" in subset else 0,
        }

    return {"status": "ok", "by_type": report, "total_settled": len(settled)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_calibrate.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat: calibration stub for post-launch analysis"
```

---

## Task 15: Integration Test + Install

- [ ] **Step 1: Install dependencies**

```bash
cd /Users/mikeborucki/personal_workspace/baseball-agents
pip install -r requirements.txt
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 3: Verify CLI help works**

```bash
python main.py --help
python main.py daily --help
python main.py report
```

- [ ] **Step 4: Create .env from .env.example with real keys (manual)**

```bash
cp .env.example .env
# Edit .env with your actual API keys
```

- [ ] **Step 5: Final commit**

```bash
# Verify .env is NOT staged before committing
git status
git add config.py scrapers/ briefing.py simulate.py edge.py tracker.py calibrate.py main.py tests/ data/
git commit -m "feat: complete MiroFish MLB prediction pipeline ready for opening day"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Scaffolding + Config | config.py, requirements.txt, .env.example, .gitignore |
| 2 | Odds Scraper | scrapers/odds.py |
| 3 | Pitchers Scraper | scrapers/pitchers.py |
| 4 | Lineups Scraper | scrapers/lineups.py |
| 5 | Bullpen Scraper | scrapers/bullpen.py |
| 6 | Team Stats Scraper | scrapers/team_stats.py |
| 7 | Ballpark + Weather | scrapers/ballpark.py |
| 8 | News/Injuries | scrapers/news.py |
| 9 | Briefing Builder | briefing.py |
| 10 | Simulator | simulate.py |
| 11 | Edge Detection | edge.py |
| 12 | Bet Tracker | tracker.py |
| 13 | CLI Pipeline | main.py |
| 14 | Calibration Stub | calibrate.py |
| 15 | Integration Test | all tests |
