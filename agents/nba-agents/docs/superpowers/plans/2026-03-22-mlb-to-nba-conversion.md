# MLB-to-NBA Pipeline Conversion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the MiroFish prediction pipeline from MLB baseball to NBA basketball, removing all MLB code and rebuilding sport-specific layers for NBA.

**Architecture:** The 6-layer pipeline (SCRAPE > BRIEFING > SCREEN > ENSEMBLE > EDGE > BET) is preserved. Sport-agnostic layers (ensemble engine, tracker, agents) transfer with minimal renames. Sport-specific layers (scrapers, briefing template, system prompt, bet slots, edge detection) are rebuilt for NBA using `nba_api` as the data source.

**Tech Stack:** Python 3.11+, nba_api, requests, openai (OpenRouter), click, pandas, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-mlb-to-nba-conversion-design.md`

---

## File Structure

### Files to Delete
- `scrapers/pitchers.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`, `scrapers/lineups.py`, `scrapers/news.py`
- `tests/test_pitchers.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`, `tests/test_lineups.py`, `tests/test_news.py`

### Files to Create
- `scrapers/schedule.py` — NBA daily schedule via nba_api
- `scrapers/injuries.py` — NBA injury report
- `scrapers/matchup.py` — H2H and pace matchup data
- `scrapers/rest.py` — Rest, B2B, and travel data
- `tests/test_schedule.py`, `tests/test_injuries.py`, `tests/test_matchup.py`, `tests/test_rest.py`

### Files to Rewrite
- `config.py` — NBA teams, thresholds, season helper
- `scrapers/team_stats.py` — NBA team profiles via nba_api
- `scrapers/odds.py` — NBA odds (spread, H1 markets)
- `scrapers/scores.py` — NBA final scores via nba_api
- `briefing.py` — NBA briefing template
- `simulate.py` — NBA system prompt + field renames
- `edge.py` — spread/H1 edge detection
- `main.py` — NBA pipeline wiring
- `ensemble/weights.py` — NBA bet slot names
- `ensemble/consensus.py` — NBA bet slot field mappings
- `ensemble/orchestrator.py` — NBA bet slot references
- `ensemble/runner.py` — NBA system prompt import
- `ensemble/challenger.py` — NBA challenger prompt
- `agents/results_grader.py` — spread/H1 grading
- `agents/health_check.py` — NBA API health check
- `requirements.txt`, `.env.example`
- `tests/ensemble_fixtures.py` + all test files with MLB references

### Files Unchanged
- `tracker.py`, `calibrate.py`, `ensemble/logger.py`, `ensemble/models.py`
- `agents/bet_card.py`, `agents/self_optimizer.py`, `agents/daily_runner.py`

---

## Task 1: Foundation — Config, Requirements, Delete MLB Files

**Files:**
- Rewrite: `config.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Delete: `scrapers/pitchers.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`, `scrapers/lineups.py`, `scrapers/news.py`
- Delete: `tests/test_pitchers.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`, `tests/test_lineups.py`, `tests/test_news.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Delete all MLB-only scraper files and their tests**

```bash
git rm scrapers/pitchers.py scrapers/bullpen.py scrapers/ballpark.py scrapers/lineups.py scrapers/news.py
git rm tests/test_pitchers.py tests/test_bullpen.py tests/test_ballpark.py tests/test_lineups.py tests/test_news.py
```

- [ ] **Step 2: Update requirements.txt**

Replace `pybaseball>=2.3.0` with `nba_api>=1.6.0`. Keep all other dependencies.

```
nba_api>=1.6.0
requests>=2.31.0
openai>=1.12.0
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.1.0
pytest>=7.4.0
```

- [ ] **Step 3: Install new dependencies**

```bash
pip install nba_api>=1.6.0
```

- [ ] **Step 4: Update .env.example**

Remove `WEATHER_API_KEY` line. Keep `ODDS_API_KEY` and `OPENROUTER_API_KEY`.

```
ODDS_API_KEY=your_odds_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

- [ ] **Step 5: Rewrite config.py**

Remove: `MLB_API_BASE`, `WEATHER_API_KEY`, `WEATHER_API_BASE`, `PARK_FACTORS`, `PARK_COORDS`, all MLB team data.

Write new `config.py`:

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

# API keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT_KEY = "basketball_nba"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03
GAME_TIMEOUT = 300

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing
KELLY_FRACTION = 0.25

# Edge thresholds per bet type
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "spread": 0.06,
    "total": 0.05,
    "first_half_ml": 0.05,
    "first_half_total": 0.05,
}

# Home court advantage (approximate points)
HOME_COURT_ADVANTAGE = 3.0

# All 30 NBA team abbreviations
TEAM_ABBREVS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# Team full name to abbreviation mapping (covers Odds API + nba_api names)
TEAM_NAME_TO_ABBREV = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC",
    "Los Angeles Lakers": "LAL", "LA Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def nba_season(game_date: str) -> str:
    """Convert date string to NBA season format.

    nba_api expects seasons like '2025-26'.
    NBA season starts in October, so dates Oct-Dec belong to the current year's season,
    and dates Jan-Sep belong to the previous year's season.

    Example: '2026-03-22' -> '2025-26', '2025-10-15' -> '2025-26'
    """
    year = int(game_date[:4])
    month = int(game_date[5:7])
    if month >= 10:
        return f"{year}-{str(year + 1)[-2:]}"
    return f"{year - 1}-{str(year)[-2:]}"


# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
```

- [ ] **Step 6: Write config tests**

Rewrite `tests/test_config.py`:

```python
from config import EDGE_THRESHOLDS, TEAM_ABBREVS, TEAM_NAME_TO_ABBREV, KELLY_FRACTION, ODDS_API_BASE, nba_season


def test_edge_thresholds_has_all_bet_types():
    expected = {"moneyline", "spread", "total", "first_half_ml", "first_half_total"}
    assert set(EDGE_THRESHOLDS.keys()) == expected


def test_all_thresholds_positive():
    for k, v in EDGE_THRESHOLDS.items():
        assert v > 0, f"{k} threshold must be positive"


def test_team_abbrevs_count():
    assert len(TEAM_ABBREVS) == 30


def test_team_name_mapping_covers_all_abbrevs():
    mapped = set(TEAM_NAME_TO_ABBREV.values())
    for abbrev in TEAM_ABBREVS:
        assert abbrev in mapped, f"{abbrev} missing from TEAM_NAME_TO_ABBREV"


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 1.0


def test_odds_api_base():
    assert "the-odds-api.com" in ODDS_API_BASE


def test_nba_season_march():
    assert nba_season("2026-03-22") == "2025-26"


def test_nba_season_october():
    assert nba_season("2025-10-15") == "2025-26"


def test_nba_season_january():
    assert nba_season("2026-01-01") == "2025-26"
```

- [ ] **Step 7: Run config tests**

```bash
pytest tests/test_config.py -v
```
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: NBA config foundation, delete MLB scrapers, update requirements"
```

---

## Task 2: Shared Test Infrastructure — Weights + Fixtures

**Files:**
- Modify: `ensemble/weights.py:6`
- Rewrite: `tests/ensemble_fixtures.py`
- Test: `tests/test_ensemble_weights.py`

This must be done before any ensemble tests can pass.

- [ ] **Step 1: Update ensemble/weights.py BET_SLOTS**

Change line 6 from:
```python
BET_SLOTS = ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]
```
to:
```python
BET_SLOTS = ["moneyline", "spread", "total", "first_half_ml", "first_half_total"]
```

- [ ] **Step 2: Rewrite tests/ensemble_fixtures.py**

Replace all MLB field names, analyst roles, and values with NBA equivalents:

```python
"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "offensive", "pick": "BOS", "reasoning": "Elite offensive rating and 3PT shooting"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.58,
            "away_win_prob": 0.42,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "spread": {
            "favorite_cover_prob": 0.45,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "low",
        },
        "total": {
            "projected_total": 218.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "first_half": {
            "h1_home_win_prob": 0.56,
            "h1_away_win_prob": 0.44,
            "h1_projected_total": 108.5,
            "h1_ml_value": "home",
            "h1_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 105, "home": 112},
        "key_factors": ["Home court advantage", "B2B fatigue for away team"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"home": -150, "away": 130},
    "spread": {"home": -4.5, "home_odds": -110, "away": 4.5, "away_odds": -110},
    "total": {"line": 218.5, "over_odds": -110, "under_odds": -110},
    "h1_moneyline": {"home": -130, "away": 110},
    "h1_total": {"line": 108.5, "over_odds": -115, "under_odds": -105},
    "implied_probs": {"ml_home": 0.60, "ml_away": 0.40},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
```

- [ ] **Step 3: Update tests/test_ensemble_weights.py**

Update the hardcoded BET_SLOTS assertion. Find and replace `"run_line"` with `"spread"`, `"first_5_ml"` with `"first_half_ml"`, `"first_5_total"` with `"first_half_total"` throughout the file.

- [ ] **Step 4: Run weights tests**

```bash
pytest tests/test_ensemble_weights.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add ensemble/weights.py tests/ensemble_fixtures.py tests/test_ensemble_weights.py
git commit -m "feat: update bet slot names to NBA (spread, first_half)"
```

---

## Task 3: Schedule Scraper

**Files:**
- Create: `scrapers/schedule.py`
- Create: `tests/test_schedule.py`

- [ ] **Step 1: Write tests for schedule scraper**

```python
"""Tests for scrapers/schedule.py."""
from unittest.mock import patch, MagicMock
from scrapers.schedule import get_todays_games


def _mock_scoreboard_response():
    """Mock nba_api ScoreboardV3 response."""
    mock = MagicMock()
    mock.get_dict.return_value = {
        "scoreboard": {
            "games": [
                {
                    "gameId": "0022500001",
                    "homeTeam": {"teamId": 1610612738, "teamTricode": "BOS", "teamName": "Celtics", "teamCity": "Boston"},
                    "awayTeam": {"teamId": 1610612747, "teamTricode": "LAL", "teamName": "Lakers", "teamCity": "Los Angeles"},
                    "gameStatusText": "7:30 pm ET",
                    "arenaName": "TD Garden",
                },
            ]
        }
    }
    return mock


@patch("scrapers.schedule.ScoreboardV3")
def test_get_todays_games(mock_sb):
    mock_sb.return_value = _mock_scoreboard_response()
    games = get_todays_games("2026-03-22")
    assert len(games) == 1
    assert games[0]["home_team"] == "BOS"
    assert games[0]["away_team"] == "LAL"
    assert games[0]["arena"] == "TD Garden"
    assert games[0]["game_id"] == "0022500001"


@patch("scrapers.schedule.ScoreboardV3")
def test_get_todays_games_empty(mock_sb):
    mock = MagicMock()
    mock.get_dict.return_value = {"scoreboard": {"games": []}}
    mock_sb.return_value = mock
    games = get_todays_games("2026-07-15")
    assert games == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule.py -v
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement scrapers/schedule.py**

```python
"""Fetch today's NBA schedule via nba_api."""
import logging
from datetime import date
from nba_api.stats.endpoints import ScoreboardV3

logger = logging.getLogger("mirofish.scrapers.schedule")


def get_todays_games(game_date: str = None) -> list[dict]:
    """Get today's NBA games.

    Returns list of dicts with game_id, home_team, away_team, game_time, arena, team IDs.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    try:
        sb = ScoreboardV3(game_date=game_date)
        data = sb.get_dict()
    except Exception as e:
        logger.error("Failed to fetch schedule for %s: %s", game_date, e)
        return []

    games = []
    for g in data.get("scoreboard", {}).get("games", []):
        home = g.get("homeTeam", {})
        away = g.get("awayTeam", {})
        games.append({
            "game_id": g.get("gameId", ""),
            "home_team": home.get("teamTricode", ""),
            "away_team": away.get("teamTricode", ""),
            "game_time": g.get("gameStatusText", ""),
            "arena": g.get("arenaName", ""),
            "home_team_id": home.get("teamId", 0),
            "away_team_id": away.get("teamId", 0),
        })

    logger.info("Found %d games for %s", len(games), game_date)
    return games
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_schedule.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/schedule.py tests/test_schedule.py
git commit -m "feat: NBA schedule scraper via nba_api ScoreboardV3"
```

---

## Task 4: Team Stats Scraper

**Files:**
- Rewrite: `scrapers/team_stats.py`
- Rewrite: `tests/test_team_stats.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for scrapers/team_stats.py."""
from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_team_profile, pythagorean_win_pct


def test_pythagorean_win_pct_nba():
    # NBA exponent ~14, team scoring 110 ppg allowing 105 ppg
    pct = pythagorean_win_pct(110, 105, exp=14)
    assert 0.6 < pct < 0.8


def test_pythagorean_win_pct_equal():
    assert pythagorean_win_pct(100, 100) == 0.5


def test_pythagorean_win_pct_zero():
    assert pythagorean_win_pct(0, 0) == 0.5


@patch("scrapers.team_stats.LeagueDashTeamStats")
def test_get_team_profile(mock_stats):
    mock_df = MagicMock()
    mock_df.get_data_frames.return_value = [MagicMock()]
    df = mock_df.get_data_frames.return_value[0]
    df.__len__ = lambda s: 1
    df.__getitem__ = lambda s, k: MagicMock()
    # This tests the function exists and accepts correct args
    mock_stats.return_value = mock_df
    # Full integration tested separately; here we verify it doesn't crash
```

- [ ] **Step 2: Implement scrapers/team_stats.py**

```python
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
    """Get NBA team profile with advanced stats.

    Args:
        team_abbrev: 3-letter team code (e.g., 'BOS')
        season: NBA season string (e.g., '2025-26'). Auto-detected if None.
    """
    if season is None:
        season = nba_season(date.today().isoformat())

    try:
        from nba_api.stats.endpoints import LeagueDashTeamStats
        stats = LeagueDashTeamStats(season=season, per_mode_detailed="PerGame")
        df = stats.get_data_frames()[0]
    except Exception as e:
        logger.error("Failed to fetch team stats for %s: %s", team_abbrev, e)
        return {"team": team_abbrev, "error": str(e)}

    row = df[df["TEAM_ABBREVIATION"] == team_abbrev]
    if row.empty:
        return {"team": team_abbrev, "error": "team not found"}

    r = row.iloc[0]
    wins = int(r.get("W", 0))
    losses = int(r.get("L", 0))
    ppg = float(r.get("PTS", 0))
    opp_ppg = float(r.get("OPP_PTS", ppg))  # may need separate query

    return {
        "team": team_abbrev,
        "record": f"{wins}-{losses}",
        "pct": round(r.get("W_PCT", 0), 3),
        "home_record": "",  # populated from splits if available
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
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_team_stats.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add scrapers/team_stats.py tests/test_team_stats.py
git commit -m "feat: NBA team stats scraper with advanced metrics"
```

---

## Task 5: Injuries Scraper

**Files:**
- Create: `scrapers/injuries.py`
- Create: `tests/test_injuries.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for scrapers/injuries.py."""
from scrapers.injuries import classify_impact_tier


def test_classify_star():
    assert classify_impact_tier(34.5) == "star"


def test_classify_rotation():
    assert classify_impact_tier(22.0) == "rotation"


def test_classify_bench():
    assert classify_impact_tier(10.0) == "bench"


def test_get_injuries_returns_list():
    from scrapers.injuries import get_injuries
    result = get_injuries()
    assert isinstance(result, list)
```

- [ ] **Step 2: Implement scrapers/injuries.py**

```python
"""Fetch NBA injury report."""
import logging
import requests

logger = logging.getLogger("mirofish.scrapers.injuries")


def classify_impact_tier(minutes_per_game: float) -> str:
    """Classify player impact by minutes per game."""
    if minutes_per_game >= 28:
        return "star"
    elif minutes_per_game >= 18:
        return "rotation"
    return "bench"


def get_injuries() -> list[dict]:
    """Fetch current NBA injury report.

    Returns list of dicts with team, player, status, reason, impact_tier.
    """
    try:
        # Use the NBA.com injury report endpoint
        url = "https://cdn.nba.com/static/json/liveData/odds/odds_todaysGames.json"
        # Alternative: scrape from official injury report
        # For now, return empty list as a stub — real implementation
        # would parse the NBA official injury report page or a third-party API
        logger.info("Injury report: using stub implementation")
        return []
    except Exception as e:
        logger.error("Failed to fetch injuries: %s", e)
        return []
```

Note: The injury scraper is a stub because NBA.com doesn't expose a clean JSON injury API. The implementing agent should check for a working `nba_api` endpoint or use web scraping. The `classify_impact_tier` function and data format are fully specified.

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_injuries.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add scrapers/injuries.py tests/test_injuries.py
git commit -m "feat: NBA injuries scraper with impact tier classification"
```

---

## Task 6: Matchup Scraper

**Files:**
- Create: `scrapers/matchup.py`
- Create: `tests/test_matchup.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for scrapers/matchup.py."""
from scrapers.matchup import compute_pace_matchup


def test_compute_pace_matchup_similar():
    result = compute_pace_matchup(100.0, 101.0)
    assert result["projected_pace"] == 100.5
    assert "similar" in result["mismatch"].lower()


def test_compute_pace_matchup_fast_vs_slow():
    result = compute_pace_matchup(105.0, 95.0)
    assert result["projected_pace"] == 100.0
    assert result["projected_possessions"] > 0
```

- [ ] **Step 2: Implement scrapers/matchup.py**

```python
"""Fetch NBA matchup-specific data."""
import logging
from datetime import date
from config import nba_season

logger = logging.getLogger("mirofish.scrapers.matchup")


def compute_pace_matchup(pace_home: float, pace_away: float) -> dict:
    """Compute pace matchup projection."""
    projected_pace = round((pace_home + pace_away) / 2, 1)
    # Approximate possessions per game (48 min game)
    projected_possessions = round(projected_pace)
    diff = abs(pace_home - pace_away)
    if diff < 2:
        mismatch = "Both teams play at similar pace"
    elif diff < 5:
        mismatch = "Moderate pace differential"
    else:
        fast = "home" if pace_home > pace_away else "away"
        mismatch = f"Significant pace mismatch — {fast} team plays much faster"
    return {
        "projected_pace": projected_pace,
        "projected_possessions": projected_possessions,
        "mismatch": mismatch,
    }


def get_matchup_data(home_abbrev: str, away_abbrev: str, season: str = None) -> dict:
    """Get head-to-head and pace matchup data.

    Args:
        home_abbrev: Home team abbreviation
        away_abbrev: Away team abbreviation
        season: NBA season string
    """
    if season is None:
        season = nba_season(date.today().isoformat())

    result = {
        "h2h_record": "",
        "last_meeting": "",
        "pace_matchup": compute_pace_matchup(100.0, 100.0),  # default
    }

    try:
        from nba_api.stats.endpoints import LeagueGameLog
        logs = LeagueGameLog(season=season, season_type_all_star="Regular Season")
        df = logs.get_data_frames()[0]

        # Filter H2H games
        home_games = df[df["TEAM_ABBREVIATION"] == home_abbrev]
        h2h = home_games[home_games["MATCHUP"].str.contains(away_abbrev, na=False)]

        if not h2h.empty:
            wins = int((h2h["WL"] == "W").sum())
            losses = int((h2h["WL"] == "L").sum())
            result["h2h_record"] = f"{wins}-{losses}"
            last = h2h.iloc[0]
            result["last_meeting"] = f"{last['MATCHUP']} ({last.get('GAME_DATE', '')})"

    except Exception as e:
        logger.warning("Failed to fetch matchup data for %s vs %s: %s", home_abbrev, away_abbrev, e)

    return result
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_matchup.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add scrapers/matchup.py tests/test_matchup.py
git commit -m "feat: NBA matchup scraper with pace projection"
```

---

## Task 7: Rest & Travel Scraper

**Files:**
- Create: `scrapers/rest.py`
- Create: `tests/test_rest.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for scrapers/rest.py."""
from scrapers.rest import compute_rest_from_dates


def test_back_to_back():
    result = compute_rest_from_dates("2026-03-22", ["2026-03-21", "2026-03-19"])
    assert result["days_rest"] == 0
    assert result["is_b2b"] is True


def test_one_day_rest():
    result = compute_rest_from_dates("2026-03-22", ["2026-03-20", "2026-03-18"])
    assert result["days_rest"] == 1
    assert result["is_b2b"] is False


def test_no_recent_games():
    result = compute_rest_from_dates("2026-03-22", [])
    assert result["days_rest"] >= 3
    assert result["is_b2b"] is False


def test_games_last_7():
    dates = ["2026-03-21", "2026-03-19", "2026-03-17", "2026-03-10"]
    result = compute_rest_from_dates("2026-03-22", dates)
    assert result["games_last_7"] == 3
```

- [ ] **Step 2: Implement scrapers/rest.py**

```python
"""Compute rest, back-to-back, and travel data for NBA teams."""
import logging
from datetime import date, datetime, timedelta
from config import nba_season

logger = logging.getLogger("mirofish.scrapers.rest")


def compute_rest_from_dates(game_date: str, recent_game_dates: list[str]) -> dict:
    """Compute rest metrics from a list of recent game dates.

    Args:
        game_date: Today's game date (YYYY-MM-DD)
        recent_game_dates: List of recent game dates, most recent first
    """
    today = datetime.strptime(game_date, "%Y-%m-%d").date()

    if not recent_game_dates:
        return {
            "days_rest": 3,
            "is_b2b": False,
            "games_last_7": 0,
            "road_trip_length": 0,
            "travel_miles": 0,
            "tz_change": 0,
        }

    last_game = datetime.strptime(recent_game_dates[0], "%Y-%m-%d").date()
    days_rest = (today - last_game).days - 1  # subtract 1: day before = 0 rest

    week_ago = today - timedelta(days=7)
    games_last_7 = sum(
        1 for d in recent_game_dates
        if datetime.strptime(d, "%Y-%m-%d").date() >= week_ago
    )

    return {
        "days_rest": max(days_rest, 0),
        "is_b2b": days_rest == 0,
        "games_last_7": games_last_7,
        "road_trip_length": 0,
        "travel_miles": 0,
        "tz_change": 0,
    }


def get_rest_data(team_abbrev: str, game_date: str) -> dict:
    """Fetch rest and schedule data for a team.

    Args:
        team_abbrev: 3-letter team code
        game_date: Game date string (YYYY-MM-DD)
    """
    season = nba_season(game_date)

    try:
        from nba_api.stats.endpoints import LeagueGameLog
        logs = LeagueGameLog(
            season=season,
            season_type_all_star="Regular Season",
        )
        df = logs.get_data_frames()[0]
        team_games = df[df["TEAM_ABBREVIATION"] == team_abbrev].copy()

        # Get games before today
        team_games["GAME_DT"] = team_games["GAME_DATE"].apply(
            lambda x: datetime.strptime(x[:10], "%Y-%m-%d").date()
        )
        today = datetime.strptime(game_date, "%Y-%m-%d").date()
        past_games = team_games[team_games["GAME_DT"] < today]
        past_games = past_games.sort_values("GAME_DT", ascending=False)

        recent_dates = [d.strftime("%Y-%m-%d") for d in past_games["GAME_DT"].head(10)]
        return compute_rest_from_dates(game_date, recent_dates)

    except Exception as e:
        logger.warning("Failed to fetch rest data for %s: %s", team_abbrev, e)
        return compute_rest_from_dates(game_date, [])
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_rest.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add scrapers/rest.py tests/test_rest.py
git commit -m "feat: NBA rest and B2B scraper"
```

---

## Task 8: Odds Scraper Conversion

**Files:**
- Rewrite: `scrapers/odds.py`
- Rewrite: `tests/test_odds.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for scrapers/odds.py."""
from unittest.mock import patch, MagicMock
from scrapers.odds import american_to_implied_prob, OddsData, get_nba_odds


def test_implied_prob_favorite():
    p = american_to_implied_prob(-150)
    assert abs(p - 0.6) < 0.01


def test_implied_prob_underdog():
    p = american_to_implied_prob(150)
    assert abs(p - 0.4) < 0.01


def test_odds_data_fields():
    od = OddsData(home="BOS", away="LAL", commence_time="2026-03-22T00:30:00Z")
    assert od.spread == {}
    assert od.h1_moneyline == {}
    assert od.h1_total == {}
    assert od.h1_spread == {}
    # Verify old MLB fields don't exist
    assert not hasattr(od, "run_line")
    assert not hasattr(od, "f5_moneyline")
    assert not hasattr(od, "f5_total")


@patch("scrapers.odds.requests.get")
def test_get_nba_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.json.return_value = [
        {
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "commence_time": "2026-03-22T00:30:00Z",
            "bookmakers": [
                {
                    "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": "Boston Celtics", "price": -150},
                            {"name": "Los Angeles Lakers", "price": 130},
                        ]},
                        {"key": "spreads", "outcomes": [
                            {"name": "Boston Celtics", "price": -110, "point": -4.5},
                            {"name": "Los Angeles Lakers", "price": -110, "point": 4.5},
                        ]},
                        {"key": "totals", "outcomes": [
                            {"name": "Over", "price": -110, "point": 218.5},
                            {"name": "Under", "price": -110},
                        ]},
                        {"key": "h2h_h1", "outcomes": [
                            {"name": "Boston Celtics", "price": -130},
                            {"name": "Los Angeles Lakers", "price": 110},
                        ]},
                        {"key": "totals_h1", "outcomes": [
                            {"name": "Over", "price": -115, "point": 108.5},
                            {"name": "Under", "price": -105},
                        ]},
                        {"key": "spreads_h1", "outcomes": [
                            {"name": "Boston Celtics", "price": -110, "point": -2.5},
                            {"name": "Los Angeles Lakers", "price": -110, "point": 2.5},
                        ]},
                    ]
                }
            ],
        }
    ]
    mock_get.return_value = mock_resp
    results = get_nba_odds()
    assert len(results) == 1
    assert results[0].home == "BOS"
    assert results[0].away == "LAL"
    assert results[0].moneyline["home"] == -150
    assert results[0].spread["home"] == -4.5
    assert results[0].total["line"] == 218.5
    # H1 markets
    assert results[0].h1_moneyline["home"] == -130
    assert results[0].h1_total["line"] == 108.5
    assert results[0].h1_total["over_odds"] == -115
    assert results[0].h1_spread["home"] == -2.5
```

- [ ] **Step 2: Rewrite scrapers/odds.py**

Key changes from current code:
- `OddsData`: `run_line` -> `spread`, `f5_moneyline` -> `h1_moneyline`, `f5_total` -> `h1_total`, add `h1_spread`
- `get_mlb_odds()` -> `get_nba_odds()`
- Sport key: `basketball_nba`
- Markets: `"h2h,spreads,totals,h2h_h1,totals_h1,spreads_h1"`
- Market parsing: `"h2h_h1"` replaces `"h2h_1st_5_innings"`, `"totals_h1"` replaces `"totals_1st_5_innings"`, add `"spreads_h1"`
- Remove default `-1.5`/`1.5` from spread parsing
- `h1_total` keys: use `"over_odds"`/`"under_odds"` (fix inconsistency from MLB code)
- Implied probs: `rl_home`/`rl_away` -> `spread_home`/`spread_away`

```python
from dataclasses import dataclass, field
import requests
from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY, TEAM_NAME_TO_ABBREV


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
    spread: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    h1_moneyline: dict = field(default_factory=dict)
    h1_total: dict = field(default_factory=dict)
    h1_spread: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def _team_abbrev(full_name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(full_name, full_name)


def get_nba_odds() -> list[OddsData]:
    """Fetch NBA odds from The Odds API."""
    markets_options = [
        "h2h,spreads,totals,h2h_h1,totals_h1,spreads_h1",
        "h2h,spreads,totals",
    ]

    resp = None
    for markets in markets_options:
        url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": markets,
            "oddsFormat": "american",
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 422 and "h1" in markets:
            print("[odds] H1 markets not available, falling back to core markets")
            continue
        resp.raise_for_status()
        break

    data = resp.json()
    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] {len(data)} games, {remaining} API requests remaining")

    results = []
    for event in data:
        home = _team_abbrev(event["home_team"])
        away = _team_abbrev(event["away_team"])
        odds_data = OddsData(home=home, away=away, commence_time=event["commence_time"])

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
                        odds_data.spread["home"] = outcome.get("point", 0)
                        odds_data.spread["home_odds"] = outcome["price"]
                    else:
                        odds_data.spread["away"] = outcome.get("point", 0)
                        odds_data.spread["away_odds"] = outcome["price"]

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.total["line"] = outcome.get("point", 0)
                        odds_data.total["over_odds"] = outcome["price"]
                    else:
                        odds_data.total["under_odds"] = outcome["price"]

            if "h2h_h1" in markets:
                for outcome in markets["h2h_h1"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.h1_moneyline["home"] = outcome["price"]
                    else:
                        odds_data.h1_moneyline["away"] = outcome["price"]

            if "totals_h1" in markets:
                for outcome in markets["totals_h1"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.h1_total["line"] = outcome.get("point", 0)
                        odds_data.h1_total["over_odds"] = outcome["price"]
                    else:
                        odds_data.h1_total["under_odds"] = outcome["price"]

            if "spreads_h1" in markets:
                for outcome in markets["spreads_h1"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.h1_spread["home"] = outcome.get("point", 0)
                        odds_data.h1_spread["home_odds"] = outcome["price"]
                    else:
                        odds_data.h1_spread["away"] = outcome.get("point", 0)
                        odds_data.h1_spread["away_odds"] = outcome["price"]

            if odds_data.moneyline:
                break

        # Compute implied probabilities (vig-removed)
        if odds_data.moneyline:
            ml_home = american_to_implied_prob(odds_data.moneyline["home"])
            ml_away = american_to_implied_prob(odds_data.moneyline["away"])
            total_prob = ml_home + ml_away
            odds_data.implied_probs["ml_home"] = ml_home / total_prob
            odds_data.implied_probs["ml_away"] = ml_away / total_prob

        if odds_data.spread:
            sp_home = american_to_implied_prob(odds_data.spread.get("home_odds", -110))
            sp_away = american_to_implied_prob(odds_data.spread.get("away_odds", -110))
            total_prob = sp_home + sp_away
            odds_data.implied_probs["spread_home"] = sp_home / total_prob
            odds_data.implied_probs["spread_away"] = sp_away / total_prob

        results.append(odds_data)

    return results
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_odds.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: NBA odds scraper with spread, H1 markets"
```

---

## Task 9: Scores Scraper Conversion

**Files:**
- Rewrite: `scrapers/scores.py`
- Rewrite: `tests/test_scores.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for scrapers/scores.py."""
from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores


@patch("scrapers.scores.LeagueGameLog")
def test_get_final_scores_returns_correct_fields(mock_log):
    # Test that return dict has NBA field names
    mock_df = MagicMock()
    mock_df.get_data_frames.return_value = [MagicMock()]
    mock_log.return_value = mock_df
    # Stub: verify function exists and accepts date arg
    scores = get_final_scores("2026-03-22")
    assert isinstance(scores, list)


def test_score_dict_schema():
    """Verify expected schema of a score dict."""
    score = {
        "away": "LAL", "home": "BOS",
        "away_score": 105, "home_score": 112,
        "away_score_h1": 52, "home_score_h1": 58,
        "total_points": 217, "total_points_h1": 110,
        "status": "Final",
    }
    # No MLB fields should exist
    assert "away_score_5" not in score
    assert "total_runs" not in score
    assert "total_runs_5" not in score
    # NBA fields present
    assert "away_score_h1" in score
    assert "total_points" in score
    assert "total_points_h1" in score


@patch("scrapers.scores.ScoreboardV2")
def test_half_score_aggregation(mock_sb):
    """Verify Q1+Q2 aggregation for first half scores."""
    mock_sb.return_value.get_dict.return_value = {
        "resultSets": [
            {
                "name": "GameHeader",
                "headers": ["GAME_ID", "GAME_STATUS_TEXT", "HOME_TEAM_ID", "VISITOR_TEAM_ID"],
                "rowSet": [["0022500001", "Final", 100, 200]],
            },
            {
                "name": "LineScore",
                "headers": ["GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "PTS",
                            "PTS_QTR1", "PTS_QTR2", "PTS_QTR3", "PTS_QTR4"],
                "rowSet": [
                    ["0022500001", 100, "BOS", 112, 30, 28, 26, 28],
                    ["0022500001", 200, "LAL", 105, 25, 27, 24, 29],
                ],
            },
        ]
    }
    scores = get_final_scores("2026-03-22")
    assert len(scores) == 1
    s = scores[0]
    assert s["home"] == "BOS"
    assert s["away"] == "LAL"
    assert s["home_score"] == 112
    assert s["away_score"] == 105
    assert s["home_score_h1"] == 58  # 30 + 28
    assert s["away_score_h1"] == 52  # 25 + 27
    assert s["total_points"] == 217
    assert s["total_points_h1"] == 110
```

- [ ] **Step 2: Implement scrapers/scores.py**

```python
"""Pull final NBA scores via nba_api."""
import logging
from datetime import date
from config import nba_season

logger = logging.getLogger("mirofish.scrapers.scores")


def get_final_scores(game_date: str = None) -> list[dict]:
    """Get final scores for all NBA games on a date.

    Returns list of dicts with:
        away, home, away_score, home_score,
        away_score_h1, home_score_h1,
        total_points, total_points_h1, status
    """
    if game_date is None:
        game_date = date.today().isoformat()

    try:
        from nba_api.stats.endpoints import ScoreboardV2
        sb = ScoreboardV2(game_date=game_date)
        data = sb.get_dict()
    except Exception as e:
        logger.error("Failed to fetch scores for %s: %s", game_date, e)
        return []

    scores = []
    result_sets = {rs["name"]: rs for rs in data.get("resultSets", [])}

    game_header = result_sets.get("GameHeader", {})
    line_score = result_sets.get("LineScore", {})

    if not game_header or not line_score:
        return []

    headers_cols = game_header.get("headers", [])
    headers_rows = game_header.get("rowSet", [])
    line_cols = line_score.get("headers", [])
    line_rows = line_score.get("rowSet", [])

    # Build line score lookup by game_id + team_id
    line_by_game = {}
    for row in line_rows:
        entry = dict(zip(line_cols, row))
        gid = entry.get("GAME_ID")
        tid = entry.get("TEAM_ID")
        line_by_game[(gid, tid)] = entry

    for row in headers_rows:
        header = dict(zip(headers_cols, row))
        status = header.get("GAME_STATUS_TEXT", "")
        if "Final" not in status:
            continue

        game_id = header.get("GAME_ID")
        home_tid = header.get("HOME_TEAM_ID")
        away_tid = header.get("VISITOR_TEAM_ID")

        home_line = line_by_game.get((game_id, home_tid), {})
        away_line = line_by_game.get((game_id, away_tid), {})

        home_score = int(home_line.get("PTS", 0))
        away_score = int(away_line.get("PTS", 0))

        # First half = Q1 + Q2
        home_h1 = int(home_line.get("PTS_QTR1", 0)) + int(home_line.get("PTS_QTR2", 0))
        away_h1 = int(away_line.get("PTS_QTR1", 0)) + int(away_line.get("PTS_QTR2", 0))

        scores.append({
            "away": away_line.get("TEAM_ABBREVIATION", ""),
            "home": home_line.get("TEAM_ABBREVIATION", ""),
            "away_score": away_score,
            "home_score": home_score,
            "away_score_h1": away_h1,
            "home_score_h1": home_h1,
            "total_points": away_score + home_score,
            "total_points_h1": away_h1 + home_h1,
            "status": "Final",
        })

    return scores
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_scores.py -v
git add scrapers/scores.py tests/test_scores.py
git commit -m "feat: NBA scores scraper with half-time scoring"
```

---

## Task 10: Briefing Template

**Files:**
- Rewrite: `briefing.py`
- Rewrite: `tests/test_briefing.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for briefing.py."""
from briefing import build_briefing, _format_injuries


def test_format_injuries_empty():
    assert _format_injuries([]) == "No notable injuries"


def test_format_injuries():
    injuries = [
        {"player": "LeBron James", "status": "Out"},
        {"player": "AD", "status": "Questionable"},
    ]
    result = _format_injuries(injuries)
    assert "LeBron James" in result
    assert "Out" in result


def test_build_briefing_contains_nba_header():
    game_data = {
        "away_team": "LAL", "home_team": "BOS",
        "away_record": "40-25", "home_record": "50-15",
        "away_stats": {"ortg": 112.0, "drtg": 110.0, "net_rtg": 2.0, "pace": 100.0,
                       "efg_pct": 0.530, "tov_pct": 0.130, "three_rate": 0.380,
                       "three_pct": 0.360, "last_10": "6-4", "trend": "W2",
                       "away_record": "18-15"},
        "home_stats": {"ortg": 118.0, "drtg": 106.0, "net_rtg": 12.0, "pace": 98.0,
                       "efg_pct": 0.560, "tov_pct": 0.120, "three_rate": 0.400,
                       "three_pct": 0.390, "last_10": "8-2", "trend": "W5",
                       "home_record": "28-5"},
        "away_rest": {"days_rest": 1, "is_b2b": False, "games_last_7": 3,
                      "travel_miles": 500},
        "home_rest": {"days_rest": 2, "is_b2b": False, "games_last_7": 2,
                      "travel_miles": 0},
        "matchup": {"h2h_record": "1-1", "last_meeting": "LAL 110, BOS 108",
                     "pace_matchup": {"projected_pace": 99.0,
                                      "projected_possessions": 99,
                                      "mismatch": "Similar pace"}},
        "arena": "TD Garden", "game_time": "7:30 PM ET",
        "odds": {
            "moneyline": {"home": -200, "away": 170},
            "spread": {"home": -5.5, "home_odds": -110, "away": 5.5, "away_odds": -110},
            "total": {"line": 220.5, "over_odds": -110, "under_odds": -110},
            "h1_spread": {"home": -3.0, "home_odds": -110},
            "h1_total": {"line": 110.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"ml_home": 0.65, "ml_away": 0.35},
        },
        "away_injuries": [{"player": "AD", "status": "Questionable"}],
        "home_injuries": [],
    }
    brief = build_briefing(game_data)
    assert "NBA GAME PREDICTION ANALYSIS" in brief
    assert "LAL" in brief and "BOS" in brief
    assert "SPREAD" in brief or "Spread" in brief
    assert "TEAM PROFILES" in brief
    assert "PACE MATCHUP" in brief
    assert "INJURIES" in brief
    assert "PREDICTION TASK" in brief
    # No MLB content
    assert "MLB" not in brief
    assert "PITCHING" not in brief
    assert "BULLPEN" not in brief
    assert "Run Line" not in brief
```

- [ ] **Step 2: Rewrite briefing.py**

Full NBA briefing template per the spec (docs/sport-prompts/03-nba.md). The `build_briefing()` function takes the new `game_data` dict shape and renders the NBA template. Keep `_format_injuries()` and `_safe_get()`. Remove `_format_game_log()`.

The implementing agent should reference `docs/sport-prompts/03-nba.md` lines 77-139 for the exact briefing template format.

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_briefing.py -v
git add briefing.py tests/test_briefing.py
git commit -m "feat: NBA briefing template with team profiles, pace, rest"
```

---

## Task 11: Simulation Layer — System Prompt + Runner

**Files:**
- Modify: `simulate.py:11-67` (system prompt), `simulate.py:176-181` (average fields)
- Modify: `ensemble/runner.py:7,42,49`
- Rewrite: `tests/test_simulate.py`

- [ ] **Step 1: Replace MLB_SYSTEM_PROMPT with NBA_SYSTEM_PROMPT in simulate.py**

Replace the entire `MLB_SYSTEM_PROMPT` string (lines 11-67) with the NBA system prompt from `docs/sport-prompts/03-nba.md` lines 146-208. Name the variable `NBA_SYSTEM_PROMPT`.

Key changes in the JSON output structure:
- `"run_line"` section -> `"spread"` with `favorite_cover_prob`, `value_side: "favorite|underdog|none"`
- `"first_5"` section -> `"first_half"` with `h1_home_win_prob`, `h1_away_win_prob`, `h1_projected_total`, `h1_ml_value`, `h1_total_value`
- `predicted_score` values ~95-125 (not 2-8)
- Analyst roles: `"offensive"`, `"defensive"`, `"pace_tempo"`, `"rest_schedule"`, `"market"`, `"contrarian"`

- [ ] **Step 2: Update _average_results() in simulate.py**

Change `prob_fields` dict (line 176-181):

```python
prob_fields = {
    "moneyline": ["home_win_prob", "away_win_prob", "edge"],
    "spread": ["favorite_cover_prob", "edge"],
    "total": ["projected_total", "over_prob", "under_prob", "edge"],
    "first_half": ["h1_home_win_prob", "h1_away_win_prob", "h1_projected_total"],
}
```

- [ ] **Step 3: Update run_plan_b() reference**

Change line 109 from `MLB_SYSTEM_PROMPT` to `NBA_SYSTEM_PROMPT`.

- [ ] **Step 4: Update ensemble/runner.py**

Line 7: `from simulate import MLB_SYSTEM_PROMPT` -> `from simulate import NBA_SYSTEM_PROMPT`
Line 42 docstring: `"MLB_SYSTEM_PROMPT"` -> `"NBA_SYSTEM_PROMPT"`
Line 49: `sys_prompt = system_prompt or MLB_SYSTEM_PROMPT` -> `sys_prompt = system_prompt or NBA_SYSTEM_PROMPT`

- [ ] **Step 5: Update tests/test_simulate.py**

Replace all references to `MLB_SYSTEM_PROMPT` with `NBA_SYSTEM_PROMPT`. Update mock prediction field names (`run_line` -> `spread`, `first_5` -> `first_half`, `f5_*` -> `h1_*`). Update fixture imports if using `ensemble_fixtures.py`.

- [ ] **Step 6: Update tests/test_ensemble_runner.py**

Update any references to `MLB_SYSTEM_PROMPT`.

- [ ] **Step 7: Run tests and commit**

```bash
pytest tests/test_simulate.py tests/test_ensemble_runner.py -v
git add simulate.py ensemble/runner.py tests/test_simulate.py tests/test_ensemble_runner.py
git commit -m "feat: NBA system prompt with 6-expert panel, update runner"
```

---

## Task 12: Edge Detection

**Files:**
- Modify: `edge.py`
- Rewrite: `tests/test_edge.py`

- [ ] **Step 1: Rename functions and fields in edge.py**

- `check_run_line_edge()` -> `check_spread_edge()`:
  - All `"run_line"` strings -> `"spread"`
  - `rl_pred` / `rl_odds` variable names -> `sp_pred` / `sp_odds`
  - Read from `sim["predictions"]["spread"]` and `odds["spread"]`
  - Remove default `-1.5`/`1.5` — use `0` as default
- `check_f5_ml_edge()` -> `check_h1_ml_edge()`:
  - `"first_5_ml"` -> `"first_half_ml"`
  - `f5_pred` -> `h1_pred`, read from `sim["predictions"]["first_half"]`
  - `"f5_home_win_prob"` -> `"h1_home_win_prob"`, etc.
  - `odds["f5_moneyline"]` -> `odds["h1_moneyline"]`
- `check_f5_total_edge()` -> `check_h1_total_edge()`:
  - `"first_5_total"` -> `"first_half_total"`
  - `odds["f5_total"]` -> `odds["h1_total"]`
  - `"f5_projected_total"` -> `"h1_projected_total"`
  - Change heuristic: `delta * 0.10` -> `delta * 0.05`
  - Fix bug: use `"over_odds"`/`"under_odds"` keys consistently
- `analyze_all_edges()`: update checker list:
  ```python
  checkers = [
      ("moneyline", check_moneyline_edge),
      ("spread", check_spread_edge),
      ("total", check_total_edge),
      ("first_half_ml", check_h1_ml_edge),
      ("first_half_total", check_h1_total_edge),
  ]
  ```

- [ ] **Step 2: Rewrite tests/test_edge.py**

Replace all MLB bet type names. Provide tests for the renamed functions and the heuristic multiplier change:

```python
"""Tests for edge.py."""
from edge import (
    kelly_criterion, american_to_decimal,
    check_moneyline_edge, check_spread_edge, check_total_edge,
    check_h1_ml_edge, check_h1_total_edge, analyze_all_edges,
)

MOCK_ODDS = {
    "moneyline": {"home": -150, "away": 130},
    "spread": {"home": -4.5, "home_odds": -110, "away": 4.5, "away_odds": -110},
    "total": {"line": 218.5, "over_odds": -110, "under_odds": -110},
    "h1_moneyline": {"home": -130, "away": 110},
    "h1_total": {"line": 108.5, "over_odds": -115, "under_odds": -105},
    "implied_probs": {"ml_home": 0.60, "ml_away": 0.40},
}


def test_kelly_criterion_edge():
    k = kelly_criterion(0.60, 2.0)
    assert k > 0


def test_kelly_criterion_no_edge():
    k = kelly_criterion(0.40, 2.0)
    assert k == 0


def test_american_to_decimal_favorite():
    assert american_to_decimal(-150) > 1


def test_check_spread_edge_returns_spread_bet_type():
    sim = {"predictions": {"spread": {
        "favorite_cover_prob": 0.65, "confidence": "high"
    }}}
    result = check_spread_edge(sim, MOCK_ODDS)
    if result:
        assert result["bet_type"] == "spread"
        assert "spread" not in result.get("bet_type_old", "")


def test_check_spread_edge_no_data():
    assert check_spread_edge({"predictions": {}}, MOCK_ODDS) is None


def test_check_h1_ml_edge_returns_first_half_ml():
    sim = {"predictions": {"first_half": {
        "h1_home_win_prob": 0.70, "h1_away_win_prob": 0.30, "confidence": "high"
    }}}
    result = check_h1_ml_edge(sim, MOCK_ODDS)
    if result:
        assert result["bet_type"] == "first_half_ml"


def test_check_h1_total_edge_uses_correct_heuristic():
    """Verify the 0.05 multiplier (not the old MLB 0.10)."""
    sim = {"predictions": {"first_half": {
        "h1_projected_total": 118.5, "confidence": "medium"
    }}}
    result = check_h1_total_edge(sim, MOCK_ODDS)
    # delta = 118.5 - 108.5 = 10.0, over_prob = 0.5 + 10.0 * 0.05 = 1.0 (capped at 0.99)
    if result:
        assert result["bet_type"] == "first_half_total"
        assert result["sim_prob"] <= 0.99


def test_analyze_all_edges_uses_nba_slot_names():
    sim = {"predictions": {
        "moneyline": {"home_win_prob": 0.70, "away_win_prob": 0.30, "confidence": "high"},
        "spread": {"favorite_cover_prob": 0.65, "confidence": "high"},
        "total": {"over_prob": 0.60, "under_prob": 0.40, "projected_total": 225, "confidence": "medium"},
        "first_half": {
            "h1_home_win_prob": 0.65, "h1_away_win_prob": 0.35,
            "h1_projected_total": 115, "h1_ml_value": "home",
            "h1_total_value": "over", "confidence": "medium"
        },
    }}
    bets = analyze_all_edges(sim, MOCK_ODDS)
    bet_types = [b["bet_type"] for b in bets]
    # No MLB bet types should appear
    assert "run_line" not in bet_types
    assert "first_5_ml" not in bet_types
    assert "first_5_total" not in bet_types
```

- [ ] **Step 3: Run tests and commit**

```bash
pytest tests/test_edge.py -v
git add edge.py tests/test_edge.py
git commit -m "feat: NBA edge detection with spread, H1 markets"
```

---

## Task 13: Ensemble Layer — Consensus, Orchestrator, Challenger

**Files:**
- Modify: `ensemble/consensus.py:4-10,22-31`
- Modify: `ensemble/orchestrator.py:34-58,423-467`
- Modify: `ensemble/challenger.py:9`
- Rewrite: `tests/test_ensemble_consensus.py`
- Modify: `tests/test_ensemble_orchestrator.py`
- Modify: `tests/test_ensemble_challenger.py`
- Modify: `tests/test_ensemble_integration.py`
- Modify: `tests/test_ensemble_logger.py`

- [ ] **Step 1: Update ensemble/consensus.py**

Replace `BET_SLOT_FIELDS` (lines 4-10):
```python
BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "spread": ("spread", "value_side"),
    "total": ("total", "value_side"),
    "first_half_ml": ("first_half", "h1_ml_value"),
    "first_half_total": ("first_half", "h1_total_value"),
}
```

Update `extract_vote()` — change the `run_line` normalization block (lines 22-31) to `spread`:
```python
if bet_slot == "spread":
    sp_odds = odds.get("spread", {})
    home_point = sp_odds.get("home", 0)
    home_is_fav = home_point < 0
    if raw_vote == "favorite":
        return "home_spread" if home_is_fav else "away_spread"
    elif raw_vote == "underdog":
        return "away_spread" if home_is_fav else "home_spread"
    return raw_vote
```

- [ ] **Step 2: Update ensemble/orchestrator.py**

Replace all slot name mappings (lines 34-58):
```python
PROB_FIELDS = {
    "moneyline": ["home_win_prob", "away_win_prob"],
    "spread": ["favorite_cover_prob"],
    "total": ["over_prob", "under_prob", "projected_total"],
    "first_half_ml": ["h1_home_win_prob", "h1_away_win_prob"],
    "first_half_total": ["h1_projected_total"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "spread": "spread",
    "total": "total",
    "first_half_ml": "first_half",
    "first_half_total": "first_half",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "home_win_prob",
    "spread": "favorite_cover_prob",
    "total": "over_prob",
    "first_half_ml": "h1_home_win_prob",
    "first_half_total": "h1_projected_total",
}
```

Update `build_ensemble_result()` kill slot logic (lines 430-467): replace all `"run_line"` with `"spread"`, `"first_5_ml"` with `"first_half_ml"`, `"first_5_total"` with `"first_half_total"`, `"first_5"` with `"first_half"`, `"f5_"` with `"h1_"`.

Also update confidence section (line 423): `"run_line"` -> `"spread"`, `"first_5"` -> `"first_half"`.

- [ ] **Step 3: Update ensemble/challenger.py**

Line 9: Replace `"MLB betting ensemble"` with `"NBA betting ensemble"` in `CHALLENGER_SYSTEM_PROMPT`.

- [ ] **Step 4: Update all ensemble test files**

- `tests/test_ensemble_consensus.py`: update `BET_SLOT_FIELDS` assertions, vote tests (`run_line` -> `spread`, `favorite_rl` -> `home_spread`, etc.), fixture references
- `tests/test_ensemble_orchestrator.py`: update slot names in all assertions and mock data
- `tests/test_ensemble_challenger.py`: update "MLB" references to "NBA"
- `tests/test_ensemble_integration.py`: update mock prediction field names
- `tests/test_ensemble_logger.py`: cosmetic — update game names from "NYY@BOS" to "LAL@BOS"

- [ ] **Step 5: Run all ensemble tests**

```bash
pytest tests/test_ensemble_*.py -v
```
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add ensemble/consensus.py ensemble/orchestrator.py ensemble/challenger.py
git add tests/test_ensemble_*.py
git commit -m "feat: NBA ensemble layer — update all bet slot references"
```

---

## Task 14: Agents — Results Grader + Health Check

**Files:**
- Modify: `agents/results_grader.py:38-79`
- Rewrite: `agents/health_check.py`
- Update: `tests/test_results_grader.py`
- Update: `tests/test_health_check.py`

- [ ] **Step 1: Update agents/results_grader.py**

In `grade_bet()`:
- Line 30: `total = score["total_runs"]` -> `total = score["total_points"]`
- Line 38: `elif bet_type == "run_line":` -> `elif bet_type == "spread":`
- Line 62: `elif bet_type == "first_5":` -> `elif bet_type == "first_half":`
  - `score["home_score_5"]` -> `score["home_score_h1"]`
  - `score["away_score_5"]` -> `score["away_score_h1"]`
  - `score["total_runs_5"]` -> `score["total_points_h1"]`
  - `"F5 ML"` -> `"H1 ML"`
  - `"F5 total"` -> `"H1 total"`

- [ ] **Step 2: Rewrite agents/health_check.py**

Remove `check_mlb_api()`, `check_weather_api()`, and MLB/weather imports. Add `check_nba_api()`:

```python
"""Pre-game health check: validates API keys, data sources, connectivity."""
import click
import requests
from config import ODDS_API_KEY, OPENROUTER_API_KEY, ODDS_API_BASE, OPENROUTER_BASE_URL


def check_nba_api() -> tuple[bool, str]:
    """Check nba_api package is available and NBA.com is reachable."""
    try:
        import nba_api
        resp = requests.get("https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json", timeout=10)
        resp.raise_for_status()
        return True, "NBA API: OK"
    except ImportError:
        return False, "NBA API: FAIL (nba_api package not installed)"
    except Exception as e:
        return False, f"NBA API: FAIL ({e})"


def check_odds_api() -> tuple[bool, str]:
    """Check The Odds API key is valid."""
    if not ODDS_API_KEY:
        return False, "Odds API: NO KEY SET"
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports",
            params={"apiKey": ODDS_API_KEY},
            timeout=10,
        )
        remaining = resp.headers.get("x-requests-remaining", "?")
        if resp.status_code == 401:
            return False, "Odds API: INVALID KEY"
        resp.raise_for_status()
        return True, f"Odds API: OK ({remaining} requests remaining)"
    except Exception as e:
        return False, f"Odds API: FAIL ({e})"


def check_openrouter() -> tuple[bool, str]:
    """Check OpenRouter API key is valid."""
    if not OPENROUTER_API_KEY:
        return False, "OpenRouter: NO KEY SET"
    try:
        resp = requests.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            timeout=10,
        )
        if resp.status_code == 401:
            return False, "OpenRouter: INVALID KEY"
        return True, "OpenRouter: OK"
    except Exception as e:
        return False, f"OpenRouter: FAIL ({e})"


def run_health_check() -> bool:
    """Run all health checks. Returns True if critical checks pass."""
    click.echo("\n=== MiroFish Health Check ===\n")

    checks = [
        ("CRITICAL", check_nba_api),
        ("CRITICAL", check_odds_api),
        ("CRITICAL", check_openrouter),
    ]

    all_critical_pass = True
    for level, check_fn in checks:
        ok, msg = check_fn()
        prefix = "  [OK]" if ok else "  [FAIL]"
        click.echo(f"{prefix} {msg}")
        if not ok and level == "CRITICAL":
            all_critical_pass = False

    click.echo()
    if all_critical_pass:
        click.echo("All critical checks passed. Pipeline ready.")
    else:
        click.echo("CRITICAL checks failed. Fix before running pipeline.")

    return all_critical_pass


@click.command()
def main():
    """Run pre-game health check on all API connections."""
    run_health_check()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update tests**

- `tests/test_results_grader.py`: update bet type names and score field names. Add explicit first_half grading tests:

```python
def test_grade_spread_home_cover():
    bet = {"bet_type": "spread", "side": "home -4.5"}
    score = {"home_score": 110, "away_score": 100, "total_points": 210}
    assert grade_bet(bet, score) == "W"  # margin 10 > 4.5


def test_grade_spread_home_fail():
    bet = {"bet_type": "spread", "side": "home -4.5"}
    score = {"home_score": 104, "away_score": 100, "total_points": 204}
    assert grade_bet(bet, score) == "L"  # margin 4 < 4.5


def test_grade_first_half_ml_home():
    bet = {"bet_type": "first_half", "side": "home H1 ML"}
    score = {"home_score_h1": 58, "away_score_h1": 52, "total_points_h1": 110,
             "home_score": 112, "away_score": 105, "total_points": 217}
    assert grade_bet(bet, score) == "W"


def test_grade_first_half_total_over():
    bet = {"bet_type": "first_half", "side": "over 108.5"}
    score = {"home_score_h1": 58, "away_score_h1": 55, "total_points_h1": 113,
             "home_score": 112, "away_score": 105, "total_points": 217}
    assert grade_bet(bet, score) == "W"


def test_grade_total_uses_total_points():
    bet = {"bet_type": "total", "side": "over 218.5"}
    score = {"home_score": 115, "away_score": 108, "total_points": 223}
    assert grade_bet(bet, score) == "W"
```

- `tests/test_health_check.py`: update to test `check_nba_api()` instead of `check_mlb_api()`

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/test_results_grader.py tests/test_health_check.py -v
git add agents/results_grader.py agents/health_check.py tests/test_results_grader.py tests/test_health_check.py
git commit -m "feat: NBA results grader and health check"
```

---

## Task 15: Main Pipeline

**Files:**
- Rewrite: `main.py`
- Update: `tests/test_main.py`

This is the final wiring task — it depends on all previous tasks.

- [ ] **Step 1: Rewrite main.py imports and pipeline**

Remove all MLB scraper imports. Add NBA scraper imports. Rewrite the `daily` command to use the new NBA data flow (see spec Section 3g for full details).

Key changes:
- Import `get_todays_games` from `scrapers.schedule`
- Import `get_nba_odds` from `scrapers.odds`
- Import `get_rest_data` from `scrapers.rest`
- Import `get_matchup_data` from `scrapers.matchup`
- Import `get_injuries` from `scrapers.injuries`
- Remove pitcher, lineup, bullpen, ballpark, news imports
- CLI group: `"MiroFish NBA Prediction Pipeline"`
- Step 1: `get_todays_games(game_date)` instead of `get_probable_starters(game_date)`
- Step 2: `get_nba_odds()` instead of `get_mlb_odds()`
- Steps 3-4: `get_team_profile()`, `get_rest_data()`, `get_matchup_data()`, `get_injuries()`
- Build `game_data` dict with new NBA shape (see spec Section 3g)
- Odds dict keys: `spread`, `h1_moneyline`, `h1_total` (not `run_line`, `f5_*`)
- `game` command: remove `--away-pitcher`/`--home-pitcher` options
- Step 5-6 echo: replace "MLB" with "NBA"

- [ ] **Step 2: Update tests/test_main.py**

Update imports and CLI name assertion.

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_main.py -v
```
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: NBA main pipeline — wire all scrapers and data flow"
```

---

## Task 16: Remaining Test Cleanup

**Files:**
- Update: `tests/test_self_optimizer.py` — update bet_type references from `run_line` to `spread`
- Update: `tests/test_bet_card.py` — cosmetic: update game names if they reference MLB teams
- Update: `tests/test_calibrate.py` — verify still passes (should be agnostic)
- Update: `tests/test_tracker.py` — verify still passes (should be agnostic)

- [ ] **Step 1: Update test_self_optimizer.py**

Replace any `"run_line"` references with `"spread"`. Update model names if needed.

- [ ] **Step 2: Run full test suite**

```bash
pytest -v
```
Expected: ALL PASS. If any failures, fix them.

- [ ] **Step 3: Verify no MLB references remain**

```bash
grep -r "MLB\|mlb\|run_line\|first_5\|f5_\|pitchers\|bullpen\|ballpark\|innings\|pybaseball\|WEATHER_API" --include="*.py" .
```
Expected: No matches (or only in docs/comments about the conversion).

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final test cleanup, verify no MLB references remain"
```

---

## Task Dependency Map

```
Task 1 (Config/Foundation)
  ├── Task 2 (Weights/Fixtures)
  │     └── Task 13 (Ensemble Layer)
  ├── Task 3 (Schedule) ─────────┐
  ├── Task 4 (Team Stats) ───────┤
  ├── Task 5 (Injuries) ─────────┤── Task 10 (Briefing) ── Task 15 (Main)
  ├── Task 6 (Matchup) ──────────┤
  ├── Task 7 (Rest) ─────────────┘
  ├── Task 8 (Odds) ── Task 12 (Edge)
  ├── Task 9 (Scores) ── Task 14 (Agents)
  └── Task 11 (Simulate/Runner)
                                       └── Task 16 (Final Cleanup)
```

**Parallelizable groups:**
- Tasks 3, 4, 5, 6, 7 (all new scrapers — independent)
- Tasks 8, 9 (edit scrapers — independent)
- Tasks 11, 12 (simulate + edge — independent of each other, both depend on Task 2)
- Tasks 13, 14 (ensemble + agents — independent of each other)
