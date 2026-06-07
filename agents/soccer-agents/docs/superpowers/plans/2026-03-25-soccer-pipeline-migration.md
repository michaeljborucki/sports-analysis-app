# Soccer Pipeline Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing MLB prediction pipeline to a soccer/football pipeline targeting MLS, Eredivisie, and Serie A with Asian Handicap, Over/Under 2.5, and BTTS as primary bet markets.

**Architecture:** The 6-layer pipeline (SCRAPE -> BRIEFING -> SCREEN -> ENSEMBLE -> EDGE -> BET) stays intact. The sport-agnostic ensemble engine (orchestrator, runner, consensus, weights, challenger, logger) transfers with only bet-slot constant changes. All MLB-specific scrapers (pitchers, bullpen, lineups, ballpark) are deleted and replaced with soccer scrapers (schedule, team_stats, xg, injuries, context). The odds scraper, edge detection, briefing, system prompt, and results grader are rewritten for soccer's 3 bet types: asian_handicap, total, btts.

**Tech Stack:** Python 3.12, Click CLI, OpenRouter (6 LLM ensemble), The Odds API, FBref/soccerdata for stats, requests, pytest

**Spec document:** `docs/sport-prompts/05-soccer.md`

---

## File Structure

### Files to DELETE (MLB-only, no soccer equivalent):
- `scrapers/pitchers.py` — MLB pitcher profiles (no soccer equivalent)
- `scrapers/lineups.py` — MLB lineup hydration
- `scrapers/bullpen.py` — MLB bullpen state
- `scrapers/ballpark.py` — MLB park factors + weather
- `tests/test_pitchers.py`
- `tests/test_lineups.py`
- `tests/test_bullpen.py`
- `tests/test_ballpark.py`

### Files to CREATE:
- `scrapers/schedule.py` — Fetch fixtures from ESPN API
- `scrapers/xg.py` — Expected goals data from FBref
- `scrapers/injuries.py` — Squad availability (injuries, suspensions)
- `scrapers/context.py` — Match context (motivation, congestion, derbies)
- `tests/test_schedule.py`
- `tests/test_xg.py`
- `tests/test_injuries.py`
- `tests/test_context.py`

### Files to REWRITE (sport-specific layers):
- `config.py` — Replace MLB teams/parks with soccer leagues/config
- `scrapers/odds.py` — Replace MLB odds with soccer odds (AH, O/U 2.5, BTTS)
- `scrapers/team_stats.py` — Rewrite for soccer (xG, xGA, form, clean sheets)
- `scrapers/scores.py` — Rewrite for soccer final scores
- `scrapers/news.py` — Rewrite for soccer news/injuries source
- `briefing.py` — Soccer match briefing template
- `simulate.py` — Replace MLB_SYSTEM_PROMPT with SOCCER_SYSTEM_PROMPT
- `edge.py` — Replace run_line/F5 with asian_handicap/btts
- `agents/results_grader.py` — Rewrite grade_bet for soccer
- `agents/health_check.py` — Replace check_mlb_api with soccer API check
- `main.py` — Rewrite pipeline flow for soccer data

### Files to UPDATE (bet-slot constants only):
- `ensemble/weights.py` — BET_SLOTS list
- `ensemble/consensus.py` — BET_SLOT_FIELDS mapping
- `ensemble/orchestrator.py` — PROB_FIELDS, SLOT_SECTION, PRIMARY_PROB_FIELD
- `ensemble/runner.py` — Import rename (MLB_SYSTEM_PROMPT -> SOCCER_SYSTEM_PROMPT)
- `ensemble/challenger.py` — CHALLENGER_SYSTEM_PROMPT text
- `tests/ensemble_fixtures.py` — Mock prediction/odds fixtures
- `tests/test_ensemble_orchestrator.py` — Bet slot references
- `tests/test_ensemble_runner.py` — System prompt references
- `tests/test_ensemble_consensus.py` — BET_SLOT_FIELDS references
- `tests/test_ensemble_challenger.py` — Prompt references
- `tests/test_ensemble_weights.py` — BET_SLOTS references

---

## Task 1: Delete MLB-Only Scrapers & Tests

**Files:**
- Delete: `scrapers/pitchers.py`, `scrapers/lineups.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`
- Delete: `tests/test_pitchers.py`, `tests/test_lineups.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`

- [ ] **Step 1: Delete MLB-only scraper files**

```bash
git rm scrapers/pitchers.py scrapers/lineups.py scrapers/bullpen.py scrapers/ballpark.py
```

- [ ] **Step 2: Delete MLB-only test files**

```bash
git rm tests/test_pitchers.py tests/test_lineups.py tests/test_bullpen.py tests/test_ballpark.py
```

- [ ] **Step 3: Verify no import breakage in remaining files**

```bash
python -c "import config; print('config OK')"
```

Expected: OK (config has no imports from deleted files)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove MLB-only scrapers (pitchers, lineups, bullpen, ballpark)"
```

---

## Task 2: Rewrite config.py for Soccer

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import config


def test_supported_leagues_exist():
    assert "MLS" in config.SUPPORTED_LEAGUES
    assert "Eredivisie" in config.SUPPORTED_LEAGUES
    assert "Serie A" in config.SUPPORTED_LEAGUES


def test_active_leagues_are_subset_of_supported():
    for league in config.ACTIVE_LEAGUES:
        assert league in config.SUPPORTED_LEAGUES


def test_edge_thresholds_cover_soccer_bet_types():
    assert "asian_handicap" in config.EDGE_THRESHOLDS
    assert "total" in config.EDGE_THRESHOLDS
    assert "btts" in config.EDGE_THRESHOLDS
    # MLB types should NOT exist
    assert "moneyline" not in config.EDGE_THRESHOLDS
    assert "run_line" not in config.EDGE_THRESHOLDS
    assert "first_5_ml" not in config.EDGE_THRESHOLDS
    assert "first_5_total" not in config.EDGE_THRESHOLDS


def test_kelly_fraction_eighth_kelly():
    assert config.KELLY_FRACTION == 0.125


def test_home_advantage_by_league():
    assert "MLS" in config.HOME_ADVANTAGE_BY_LEAGUE
    assert all(0 < v < 0.30 for v in config.HOME_ADVANTAGE_BY_LEAGUE.values())


def test_no_mlb_remnants():
    assert not hasattr(config, "TEAM_ABBREVS")
    assert not hasattr(config, "TEAM_NAME_TO_ABBREV")
    assert not hasattr(config, "PARK_FACTORS")
    assert not hasattr(config, "PARK_COORDS")
    assert not hasattr(config, "MLB_API_BASE")


def test_bet_slots():
    assert config.BET_SLOTS == ["asian_handicap", "total", "btts"]


def test_game_timeout():
    assert config.GAME_TIMEOUT == 180


def test_ensemble_models():
    assert len(config.ENSEMBLE_MODELS) == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — MLB config still present

- [ ] **Step 3: Rewrite config.py**

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
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03  # 3% edge to trigger full MiroFish sim
GAME_TIMEOUT = 180  # 3 min per match

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing — eighth-Kelly for soccer (low scoring = high variance)
KELLY_FRACTION = 0.125

# Bet types for soccer — avoid 1X2, focus on 2-way markets
BET_SLOTS = ["asian_handicap", "total", "btts"]

# Edge thresholds per bet type
EDGE_THRESHOLDS = {
    "asian_handicap": 0.05,   # 5% min edge
    "total": 0.05,            # 5% min edge
    "btts": 0.06,             # 6% min edge (harder to calibrate)
}

# Supported leagues and their Odds API sport keys
SUPPORTED_LEAGUES = {
    "MLS": "soccer_usa_mls",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "La Liga": "soccer_spain_la_liga",
    "EPL": "soccer_epl",
    "Ligue 1": "soccer_france_ligue_one",
}

# Start with softer markets
ACTIVE_LEAGUES = ["MLS", "Eredivisie", "Serie A"]

# Home advantage varies by league (approximate % boost)
HOME_ADVANTAGE_BY_LEAGUE = {
    "MLS": 0.08,
    "Eredivisie": 0.10,
    "Serie A": 0.12,
    "EPL": 0.08,
    "Bundesliga": 0.10,
    "La Liga": 0.10,
    "Ligue 1": 0.10,
}

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: rewrite config.py for soccer (leagues, bet types, eighth-Kelly)"
```

---

## Task 3: Rewrite scrapers/odds.py for Soccer

**Files:**
- Modify: `scrapers/odds.py`
- Modify: `tests/test_odds.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_odds.py
import pytest
from unittest.mock import patch, MagicMock
from scrapers.odds import OddsData, get_soccer_odds, american_to_implied_prob


def test_american_to_implied_prob_negative():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.01


def test_american_to_implied_prob_positive():
    assert abs(american_to_implied_prob(150) - 0.4) < 0.01


def test_odds_data_has_soccer_fields():
    od = OddsData(home="Inter", away="Milan", commence_time="2026-03-25T20:00:00Z")
    assert hasattr(od, "asian_handicap")
    assert hasattr(od, "total")
    assert hasattr(od, "btts")
    assert hasattr(od, "moneyline_1x2")
    assert hasattr(od, "implied_probs")
    # MLB fields should NOT exist
    assert not hasattr(od, "run_line")
    assert not hasattr(od, "f5_moneyline")
    assert not hasattr(od, "f5_total")


MOCK_API_RESPONSE = [
    {
        "home_team": "Inter Miami CF",
        "away_team": "LA Galaxy",
        "commence_time": "2026-03-25T23:30:00Z",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Inter Miami CF", "price": -120},
                            {"name": "LA Galaxy", "price": 300},
                            {"name": "Draw", "price": 260},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Inter Miami CF", "price": -110, "point": -0.5},
                            {"name": "LA Galaxy", "price": -110, "point": 0.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -115, "point": 2.5},
                            {"name": "Under", "price": -105},
                        ],
                    },
                ],
            }
        ],
    }
]


@patch("scrapers.odds.requests.get")
def test_get_soccer_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_API_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    results = get_soccer_odds(league="MLS")
    assert len(results) == 1
    od = results[0]
    assert od.home == "Inter Miami CF"
    assert od.away == "LA Galaxy"
    assert od.asian_handicap["home"] == -0.5
    assert od.asian_handicap["home_odds"] == -110
    assert od.total["line"] == 2.5
    assert od.moneyline_1x2["home"] == -120
    assert od.moneyline_1x2["draw"] == 260


@patch("scrapers.odds.requests.get")
def test_get_soccer_odds_no_games(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    results = get_soccer_odds(league="MLS")
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_odds.py -v`
Expected: FAIL — get_soccer_odds and new OddsData fields don't exist

- [ ] **Step 3: Rewrite scrapers/odds.py**

```python
"""Fetch soccer betting odds from The Odds API."""
from dataclasses import dataclass, field
import logging
import requests
from config import ODDS_API_KEY, ODDS_API_BASE, SUPPORTED_LEAGUES

logger = logging.getLogger("mirofish.scrapers.odds")


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
    asian_handicap: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    btts: dict = field(default_factory=dict)
    moneyline_1x2: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def get_soccer_odds(league: str = "MLS") -> list[OddsData]:
    """Fetch soccer odds for a given league.

    Returns OddsData with asian_handicap, total (O/U 2.5), BTTS, and 1X2.
    """
    sport_key = SUPPORTED_LEAGUES.get(league)
    if not sport_key:
        logger.warning("Unsupported league: %s", league)
        return []

    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals,btts",
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Odds API error for %s: %s", league, e)
        return []

    data = resp.json()
    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("[odds] %s: %d games, %s API requests remaining", league, len(data), remaining)

    results = []
    for event in data:
        home_full = event["home_team"]
        away_full = event["away_team"]

        od = OddsData(
            home=home_full,
            away=away_full,
            commence_time=event["commence_time"],
        )

        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            # 1X2 moneyline (informational — not primary bet type)
            if "h2h" in markets:
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == home_full:
                        od.moneyline_1x2["home"] = outcome["price"]
                    elif outcome["name"] == away_full:
                        od.moneyline_1x2["away"] = outcome["price"]
                    elif outcome["name"] == "Draw":
                        od.moneyline_1x2["draw"] = outcome["price"]

            # Asian Handicap (spreads market in Odds API)
            if "spreads" in markets:
                for outcome in markets["spreads"]["outcomes"]:
                    if outcome["name"] == home_full:
                        od.asian_handicap["home"] = outcome.get("point", -0.5)
                        od.asian_handicap["home_odds"] = outcome["price"]
                    else:
                        od.asian_handicap["away"] = outcome.get("point", 0.5)
                        od.asian_handicap["away_odds"] = outcome["price"]

            # Total goals (O/U, typically 2.5)
            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        od.total["line"] = outcome.get("point", 2.5)
                        od.total["over_odds"] = outcome["price"]
                    else:
                        od.total["under_odds"] = outcome["price"]

            # BTTS (Both Teams to Score)
            if "btts" in markets:
                for outcome in markets["btts"]["outcomes"]:
                    if outcome["name"] == "Yes":
                        od.btts["yes_odds"] = outcome["price"]
                    else:
                        od.btts["no_odds"] = outcome["price"]

            if od.moneyline_1x2:
                break  # got data from this bookmaker

        # Compute implied probabilities (normalized, vig-removed)
        if od.asian_handicap:
            ah_home = american_to_implied_prob(od.asian_handicap.get("home_odds", -110))
            ah_away = american_to_implied_prob(od.asian_handicap.get("away_odds", -110))
            total_prob = ah_home + ah_away
            if total_prob > 0:
                od.implied_probs["ah_home"] = ah_home / total_prob
                od.implied_probs["ah_away"] = ah_away / total_prob

        if od.total:
            ov = american_to_implied_prob(od.total.get("over_odds", -110))
            un = american_to_implied_prob(od.total.get("under_odds", -110))
            total_prob = ov + un
            if total_prob > 0:
                od.implied_probs["over"] = ov / total_prob
                od.implied_probs["under"] = un / total_prob

        if od.btts:
            yes_imp = american_to_implied_prob(od.btts.get("yes_odds", -110))
            no_imp = american_to_implied_prob(od.btts.get("no_odds", -110))
            total_prob = yes_imp + no_imp
            if total_prob > 0:
                od.implied_probs["btts_yes"] = yes_imp / total_prob
                od.implied_probs["btts_no"] = no_imp / total_prob

        results.append(od)

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_odds.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: rewrite odds scraper for soccer (AH, O/U, BTTS, 1X2)"
```

---

## Task 4: Create scrapers/schedule.py

**Files:**
- Create: `scrapers/schedule.py`
- Create: `tests/test_schedule.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schedule.py
import pytest
from unittest.mock import patch, MagicMock
from scrapers.schedule import get_fixtures


MOCK_ESPN_RESPONSE = {
    "events": [
        {
            "id": "12345",
            "date": "2026-03-25T23:30Z",
            "name": "Inter Miami CF vs LA Galaxy",
            "competitions": [
                {
                    "venue": {"fullName": "Chase Stadium"},
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {"displayName": "Inter Miami CF", "abbreviation": "MIA"},
                        },
                        {
                            "homeAway": "away",
                            "team": {"displayName": "LA Galaxy", "abbreviation": "LA"},
                        },
                    ],
                }
            ],
        }
    ],
    "leagues": [{"name": "Major League Soccer", "slug": "usa.1"}],
}


@patch("scrapers.schedule.requests.get")
def test_get_fixtures_returns_matches(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fixtures = get_fixtures(league="MLS", game_date="2026-03-25")
    assert len(fixtures) == 1
    f = fixtures[0]
    assert f["home_team"] == "Inter Miami CF"
    assert f["away_team"] == "LA Galaxy"
    assert f["venue"] == "Chase Stadium"
    assert f["league"] == "MLS"


@patch("scrapers.schedule.requests.get")
def test_get_fixtures_no_events(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"events": []}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fixtures = get_fixtures(league="MLS", game_date="2026-03-25")
    assert fixtures == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schedule.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write scrapers/schedule.py**

```python
"""Fetch soccer fixture schedules from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

logger = logging.getLogger("mirofish.scrapers.schedule")

# ESPN league slugs
LEAGUE_SLUGS = {
    "MLS": "usa.1",
    "Eredivisie": "ned.1",
    "Serie A": "ita.1",
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "La Liga": "esp.1",
    "Ligue 1": "fra.1",
}


def get_fixtures(league: str = "MLS", game_date: str = None) -> list[dict]:
    """Fetch fixtures for a league on a given date.

    Returns list of dicts with: home_team, away_team, venue, league,
    kickoff_time, event_id.
    """
    slug = LEAGUE_SLUGS.get(league)
    if not slug:
        logger.warning("Unknown league slug for: %s", league)
        return []

    url = f"{ESPN_API_BASE}/{slug}/scoreboard"
    params = {}
    if game_date:
        params["dates"] = game_date.replace("-", "")

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("ESPN API error for %s: %s", league, e)
        return []

    data = resp.json()
    fixtures = []

    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])

        home = away = None
        for team_entry in competitors:
            if team_entry.get("homeAway") == "home":
                home = team_entry.get("team", {})
            else:
                away = team_entry.get("team", {})

        if not home or not away:
            continue

        fixtures.append({
            "event_id": event.get("id"),
            "home_team": home.get("displayName", ""),
            "away_team": away.get("displayName", ""),
            "venue": comp.get("venue", {}).get("fullName", ""),
            "kickoff_time": event.get("date", ""),
            "league": league,
        })

    logger.info("[schedule] %s on %s: %d fixtures", league, game_date, len(fixtures))
    return fixtures
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schedule.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/schedule.py tests/test_schedule.py
git commit -m "feat: add soccer schedule scraper (ESPN API)"
```

---

## Task 5: Rewrite scrapers/team_stats.py for Soccer

**Files:**
- Modify: `scrapers/team_stats.py`
- Modify: `tests/test_team_stats.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_team_stats.py
import pytest
from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_team_profile


MOCK_ESPN_TEAM = {
    "sports": [{"leagues": [{"teams": [
        {
            "team": {
                "displayName": "Inter Miami CF",
                "record": {
                    "items": [
                        {
                            "summary": "8-3-4",
                            "stats": [
                                {"name": "wins", "value": 8},
                                {"name": "losses", "value": 4},
                                {"name": "ties", "value": 3},
                                {"name": "points", "value": 27},
                                {"name": "pointsFor", "value": 24},
                                {"name": "pointsAgainst", "value": 15},
                                {"name": "gamesPlayed", "value": 15},
                            ],
                        }
                    ]
                },
                "standingSummary": "1st in Eastern Conference",
            }
        }
    ]}]}],
}


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_basic(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_TEAM
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    profile = get_team_profile("Inter Miami CF", league="MLS")
    assert profile["team"] == "Inter Miami CF"
    assert profile["record"] == "8-3-4"
    assert profile["points"] == 27
    assert profile["goals_for"] == 24
    assert profile["goals_against"] == 15
    assert profile["goal_diff"] == 9
    assert profile["standing"] == "1st in Eastern Conference"


def test_get_team_profile_no_mlb_fields():
    """Ensure no MLB remnants."""
    # The function signature should not accept 'season' as positional int
    # It should accept league as a keyword
    import inspect
    sig = inspect.signature(get_team_profile)
    params = list(sig.parameters.keys())
    assert "team_name" in params or "team" in params
    assert "league" in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_team_stats.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite scrapers/team_stats.py**

```python
"""Fetch soccer team season stats from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

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


def _find_stat(stats: list[dict], name: str, default=0):
    """Find a stat value by name from ESPN stats array."""
    for s in stats:
        if s.get("name") == name:
            return s.get("value", default)
    return default


def get_team_profile(team_name: str, league: str = "MLS") -> dict:
    """Fetch team record and basic stats.

    Returns dict with: team, record, points, goals_for, goals_against,
    goal_diff, games_played, standing.
    """
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"{ESPN_API_BASE}/{slug}/teams"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("ESPN team stats error: %s", e)
        return {"team": team_name, "record": "", "points": 0,
                "goals_for": 0, "goals_against": 0, "goal_diff": 0,
                "games_played": 0, "standing": ""}

    # Search for team in response
    for group in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        team_data = group.get("team", {})
        if team_data.get("displayName") == team_name:
            record_items = team_data.get("record", {}).get("items", [{}])
            if not record_items:
                break
            rec = record_items[0]
            stats = rec.get("stats", [])

            gf = int(_find_stat(stats, "pointsFor"))
            ga = int(_find_stat(stats, "pointsAgainst"))

            return {
                "team": team_name,
                "record": rec.get("summary", ""),
                "points": int(_find_stat(stats, "points")),
                "goals_for": gf,
                "goals_against": ga,
                "goal_diff": gf - ga,
                "games_played": int(_find_stat(stats, "gamesPlayed")),
                "standing": team_data.get("standingSummary", ""),
            }

    logger.warning("Team not found: %s in %s", team_name, league)
    return {"team": team_name, "record": "", "points": 0,
            "goals_for": 0, "goals_against": 0, "goal_diff": 0,
            "games_played": 0, "standing": ""}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_team_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/team_stats.py tests/test_team_stats.py
git commit -m "feat: rewrite team_stats scraper for soccer (ESPN API)"
```

---

## Task 6: Create scrapers/xg.py (Expected Goals)

**Files:**
- Create: `scrapers/xg.py`
- Create: `tests/test_xg.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_xg.py
import pytest
from scrapers.xg import get_xg_profile


def test_get_xg_profile_returns_defaults():
    """When API is unavailable, returns sane defaults."""
    profile = get_xg_profile("Nonexistent FC", league="MLS")
    assert profile["team"] == "Nonexistent FC"
    assert "xg_per_match" in profile
    assert "xga_per_match" in profile
    assert "xg_diff" in profile
    assert isinstance(profile["xg_per_match"], float)
    assert isinstance(profile["xga_per_match"], float)


def test_xg_profile_has_regression_field():
    profile = get_xg_profile("Test FC", league="MLS")
    assert "xg_overperformance" in profile
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_xg.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write scrapers/xg.py**

```python
"""Expected goals (xG) data scraper.

Fetches xG data from FBref or returns defaults when unavailable.
This is a critical data source — xG regression is the primary edge in soccer.
"""
import logging

logger = logging.getLogger("mirofish.scrapers.xg")


def get_xg_profile(team_name: str, league: str = "MLS") -> dict:
    """Fetch xG profile for a team.

    Returns dict with: team, xg_per_match, xga_per_match, xg_diff,
    xg_overperformance, goals_per_match.

    TODO: Implement FBref scraping via soccerdata package.
    Currently returns league-average defaults.
    """
    # Default to league averages (~1.3 xG per match)
    defaults = {
        "team": team_name,
        "xg_per_match": 1.30,
        "xga_per_match": 1.30,
        "xg_diff": 0.0,
        "xg_overperformance": 0.0,
        "goals_per_match": 1.30,
        "clean_sheet_pct": 0.25,
    }

    logger.info("[xg] Using defaults for %s (FBref integration TODO)", team_name)
    return defaults
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_xg.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/xg.py tests/test_xg.py
git commit -m "feat: add xG scraper stub with defaults (FBref integration TODO)"
```

---

## Task 7: Create scrapers/injuries.py (Squad Availability)

**Files:**
- Create: `scrapers/injuries.py`
- Create: `tests/test_injuries.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_injuries.py
import pytest
from unittest.mock import patch, MagicMock
from scrapers.injuries import get_squad_injuries


MOCK_ESPN_INJURIES = {
    "sports": [{"leagues": [{"teams": [
        {
            "team": {
                "displayName": "Inter Miami CF",
                "injuries": [
                    {
                        "athlete": {"displayName": "Lionel Messi"},
                        "status": "Out",
                        "type": {"description": "Knee"},
                    },
                    {
                        "athlete": {"displayName": "Sergio Busquets"},
                        "status": "Doubtful",
                        "type": {"description": "Hamstring"},
                    },
                ],
            }
        }
    ]}]}],
}


@patch("scrapers.injuries.requests.get")
def test_get_squad_injuries(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_INJURIES
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    injuries = get_squad_injuries("Inter Miami CF", league="MLS")
    assert len(injuries) == 2
    assert injuries[0]["player"] == "Lionel Messi"
    assert injuries[0]["status"] == "Out"
    assert injuries[0]["injury"] == "Knee"


def test_get_squad_injuries_handles_failure():
    """Should return empty list on failure, not crash."""
    injuries = get_squad_injuries("Nonexistent FC", league="MLS")
    assert injuries == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_injuries.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write scrapers/injuries.py**

```python
"""Fetch squad availability (injuries, suspensions) from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

logger = logging.getLogger("mirofish.scrapers.injuries")

LEAGUE_SLUGS = {
    "MLS": "usa.1",
    "Eredivisie": "ned.1",
    "Serie A": "ita.1",
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "La Liga": "esp.1",
    "Ligue 1": "fra.1",
}


def get_squad_injuries(team_name: str, league: str = "MLS") -> list[dict]:
    """Fetch injury list for a team.

    Returns list of dicts with: player, status, injury, team.
    """
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"{ESPN_API_BASE}/{slug}/teams"

    try:
        resp = requests.get(url, params={"limit": 100}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("ESPN injuries error for %s: %s", team_name, e)
        return []

    # Find team and its injuries
    for group in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        team_data = group.get("team", {})
        if team_data.get("displayName") == team_name:
            injuries_raw = team_data.get("injuries", [])
            return [
                {
                    "player": inj.get("athlete", {}).get("displayName", "Unknown"),
                    "status": inj.get("status", "Unknown"),
                    "injury": inj.get("type", {}).get("description", "Unknown"),
                    "team": team_name,
                }
                for inj in injuries_raw
            ]

    logger.debug("No injury data found for %s", team_name)
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_injuries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/injuries.py tests/test_injuries.py
git commit -m "feat: add squad injuries scraper (ESPN API)"
```

---

## Task 8: Create scrapers/context.py (Match Context)

**Files:**
- Create: `scrapers/context.py`
- Create: `tests/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context.py
import pytest
from scrapers.context import get_match_context


def test_get_match_context_returns_expected_fields():
    ctx = get_match_context("Inter Miami CF", "LA Galaxy", league="MLS")
    assert "home_motivation" in ctx
    assert "away_motivation" in ctx
    assert "derby" in ctx
    assert "fixture_congestion" in ctx


def test_get_match_context_defaults():
    ctx = get_match_context("Team A", "Team B", league="MLS")
    assert isinstance(ctx["derby"], bool)
    assert isinstance(ctx["home_motivation"], str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_context.py -v`
Expected: FAIL

- [ ] **Step 3: Write scrapers/context.py**

```python
"""Match context: motivation, fixture congestion, derbies."""
import logging

logger = logging.getLogger("mirofish.scrapers.context")


def get_match_context(home_team: str, away_team: str, league: str = "MLS") -> dict:
    """Analyze match context factors.

    Returns dict with: home_motivation, away_motivation, derby,
    fixture_congestion, manager_notes.

    TODO: Implement full context analysis from league tables + fixture lists.
    Currently returns neutral defaults.
    """
    return {
        "home_motivation": "Standard league match",
        "away_motivation": "Standard league match",
        "derby": False,
        "fixture_congestion": "Normal schedule",
        "manager_notes": "",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_context.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/context.py tests/test_context.py
git commit -m "feat: add match context scraper stub"
```

---

## Task 9: Rewrite scrapers/scores.py for Soccer

**Files:**
- Modify: `scrapers/scores.py`
- Modify: `tests/test_scores.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scores.py
import pytest
from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores


MOCK_ESPN_SCOREBOARD = {
    "events": [
        {
            "competitions": [
                {
                    "status": {"type": {"name": "STATUS_FINAL"}},
                    "competitors": [
                        {
                            "homeAway": "home",
                            "team": {"displayName": "Inter Miami CF"},
                            "score": "2",
                        },
                        {
                            "homeAway": "away",
                            "team": {"displayName": "LA Galaxy"},
                            "score": "1",
                        },
                    ],
                }
            ]
        }
    ]
}


@patch("scrapers.scores.requests.get")
def test_get_final_scores(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_SCOREBOARD
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    scores = get_final_scores(game_date="2026-03-25", league="MLS")
    assert len(scores) == 1
    s = scores[0]
    assert s["home"] == "Inter Miami CF"
    assert s["away"] == "LA Galaxy"
    assert s["home_score"] == 2
    assert s["away_score"] == 1
    assert s["total_goals"] == 3
    assert s["both_scored"] is True


@patch("scrapers.scores.requests.get")
def test_get_final_scores_no_finals(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"events": []}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    scores = get_final_scores(game_date="2026-03-25", league="MLS")
    assert scores == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scores.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite scrapers/scores.py**

```python
"""Fetch soccer final scores from ESPN API."""
import logging
import requests
from config import ESPN_API_BASE

logger = logging.getLogger("mirofish.scrapers.scores")

LEAGUE_SLUGS = {
    "MLS": "usa.1",
    "Eredivisie": "ned.1",
    "Serie A": "ita.1",
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "La Liga": "esp.1",
    "Ligue 1": "fra.1",
}


def get_final_scores(game_date: str = None, league: str = "MLS") -> list[dict]:
    """Fetch final scores for completed matches.

    Returns list of dicts with: home, away, home_score, away_score,
    total_goals, both_scored.
    """
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    url = f"{ESPN_API_BASE}/{slug}/scoreboard"
    params = {}
    if game_date:
        params["dates"] = game_date.replace("-", "")

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("ESPN scores error: %s", e)
        return []

    data = resp.json()
    results = []

    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")

        if status != "STATUS_FINAL":
            continue

        home = away = None
        home_score = away_score = 0

        for team_entry in comp.get("competitors", []):
            team_info = team_entry.get("team", {})
            score = int(team_entry.get("score", 0))
            if team_entry.get("homeAway") == "home":
                home = team_info.get("displayName", "")
                home_score = score
            else:
                away = team_info.get("displayName", "")
                away_score = score

        if home and away:
            results.append({
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
                "total_goals": home_score + away_score,
                "both_scored": home_score > 0 and away_score > 0,
            })

    logger.info("[scores] %s on %s: %d final scores", league, game_date, len(results))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scores.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/scores.py tests/test_scores.py
git commit -m "feat: rewrite scores scraper for soccer (ESPN API)"
```

---

## Task 10: Rewrite scrapers/news.py for Soccer

**Files:**
- Modify: `scrapers/news.py`
- Modify: `tests/test_news.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news.py
import pytest
from scrapers.news import get_injuries


def test_get_injuries_returns_list():
    result = get_injuries(league="MLS")
    assert isinstance(result, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_news.py -v`
Expected: FAIL — old function signature incompatible

- [ ] **Step 3: Rewrite scrapers/news.py**

```python
"""Fetch soccer news and injury aggregation."""
import logging
from scrapers.injuries import get_squad_injuries

logger = logging.getLogger("mirofish.scrapers.news")


def get_injuries(league: str = "MLS", teams: list[str] = None) -> list[dict]:
    """Aggregate injuries across teams in a league.

    If teams is provided, only fetch for those teams.
    Returns flat list of injury dicts.
    """
    if not teams:
        return []

    all_injuries = []
    for team in teams:
        injuries = get_squad_injuries(team, league=league)
        all_injuries.extend(injuries)

    logger.info("[news] Fetched %d injuries across %d teams", len(all_injuries), len(teams))
    return all_injuries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_news.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/news.py tests/test_news.py
git commit -m "feat: rewrite news scraper for soccer injury aggregation"
```

---

## Task 11: Rewrite briefing.py for Soccer

**Files:**
- Modify: `briefing.py`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_briefing.py
import pytest
from briefing import build_briefing

MOCK_MATCH_DATA = {
    "home_team": "Inter Miami CF",
    "away_team": "LA Galaxy",
    "league": "MLS",
    "matchday": "15",
    "venue": "Chase Stadium",
    "kickoff_time": "2026-03-25T23:30Z",
    "odds": {
        "asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
        "total": {"line": 2.5, "over_odds": -115, "under_odds": -105},
        "btts": {"yes_odds": -110, "no_odds": -110},
        "moneyline_1x2": {"home": -120, "draw": 260, "away": 300},
        "implied_probs": {"ah_home": 0.52, "ah_away": 0.48, "over": 0.54, "under": 0.46},
    },
    "home_stats": {
        "record": "8-3-4", "points": 27, "goals_for": 24, "goals_against": 15,
        "goal_diff": 9, "standing": "1st in Eastern Conference",
    },
    "away_stats": {
        "record": "6-5-4", "points": 22, "goals_for": 20, "goals_against": 18,
        "goal_diff": 2, "standing": "4th in Western Conference",
    },
    "home_xg": {"xg_per_match": 1.6, "xga_per_match": 1.0, "xg_overperformance": 0.2},
    "away_xg": {"xg_per_match": 1.3, "xga_per_match": 1.2, "xg_overperformance": 0.0},
    "home_injuries": [{"player": "Messi", "status": "Out", "injury": "Knee"}],
    "away_injuries": [],
    "context": {"home_motivation": "Title race", "away_motivation": "Mid-table",
                 "derby": False, "fixture_congestion": "Normal"},
}


def test_briefing_contains_soccer_sections():
    brief = build_briefing(MOCK_MATCH_DATA)
    assert "SOCCER MATCH PREDICTION" in brief
    assert "Asian Handicap" in brief
    assert "BTTS" in brief
    assert "xG" in brief
    assert "SQUAD AVAILABILITY" in brief
    assert "Inter Miami CF" in brief
    assert "LA Galaxy" in brief


def test_briefing_no_mlb_remnants():
    brief = build_briefing(MOCK_MATCH_DATA)
    assert "MLB" not in brief
    assert "PITCHING" not in brief
    assert "BULLPEN" not in brief
    assert "RUN LINE" not in brief
    assert "FIRST 5" not in brief
    assert "F5" not in brief
    assert "BALLPARK" not in brief


def test_briefing_contains_prediction_task():
    brief = build_briefing(MOCK_MATCH_DATA)
    assert "ASIAN HANDICAP" in brief
    assert "TOTAL GOALS" in brief
    assert "BOTH TEAMS TO SCORE" in brief
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_briefing.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite briefing.py**

```python
"""Compile soccer match data into a briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _format_injuries(injuries: list[dict]) -> str:
    if not injuries:
        return "No notable injuries"
    return ", ".join(f"{i['player']} ({i.get('status', 'unknown')} - {i.get('injury', '')})" for i in injuries)


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def build_briefing(match_data: dict) -> str:
    """Build the full briefing string from compiled match data."""
    home = match_data["home_team"]
    away = match_data["away_team"]
    league = match_data.get("league", "")
    odds = match_data.get("odds", {})
    ah = odds.get("asian_handicap", {})
    total = odds.get("total", {})
    btts = odds.get("btts", {})
    ml = odds.get("moneyline_1x2", {})
    implied = odds.get("implied_probs", {})

    h_stats = match_data.get("home_stats", {})
    a_stats = match_data.get("away_stats", {})
    h_xg = match_data.get("home_xg", {})
    a_xg = match_data.get("away_xg", {})
    ctx = match_data.get("context", {})

    total_line = total.get("line", 2.5)

    briefing = f"""SOCCER MATCH PREDICTION ANALYSIS
==============================
{league} — Matchday {match_data.get('matchday', '')} | {match_data.get('kickoff_time', '')}
{home} vs {away}
{match_data.get('venue', '')}

BETTING LINES:
  Asian Handicap: {home} {ah.get('home', 'N/A')} ({ah.get('home_odds', 'N/A')}) / {away} {ah.get('away', 'N/A')} ({ah.get('away_odds', 'N/A')})
  Total: O/U {total_line} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  BTTS: Yes {btts.get('yes_odds', 'N/A')} / No {btts.get('no_odds', 'N/A')}
  1X2: {home} {ml.get('home', 'N/A')} / Draw {ml.get('draw', 'N/A')} / {away} {ml.get('away', 'N/A')}
  Implied AH Prob: {home} {implied.get('ah_home', 0):.1%} / {away} {implied.get('ah_away', 0):.1%}

== TEAM PROFILES ==

{home} — {h_stats.get('standing', '')} | {h_stats.get('record', '')} | {h_stats.get('points', 0)} pts
  Goals: {h_stats.get('goals_for', 0)} scored / {h_stats.get('goals_against', 0)} conceded (GD: {h_stats.get('goal_diff', 0)})
  xG: {h_xg.get('xg_per_match', 'N/A')} / xGA: {h_xg.get('xga_per_match', 'N/A')}
  xG Overperformance: {h_xg.get('xg_overperformance', 'N/A')} (positive = regression risk)
  Clean Sheets: {h_xg.get('clean_sheet_pct', 'N/A')}

{away} — {a_stats.get('standing', '')} | {a_stats.get('record', '')} | {a_stats.get('points', 0)} pts
  Goals: {a_stats.get('goals_for', 0)} scored / {a_stats.get('goals_against', 0)} conceded (GD: {a_stats.get('goal_diff', 0)})
  xG: {a_xg.get('xg_per_match', 'N/A')} / xGA: {a_xg.get('xga_per_match', 'N/A')}
  xG Overperformance: {a_xg.get('xg_overperformance', 'N/A')} (positive = regression risk)
  Clean Sheets: {a_xg.get('clean_sheet_pct', 'N/A')}

== SQUAD AVAILABILITY ==
{home}: {_format_injuries(match_data.get('home_injuries', []))}
{away}: {_format_injuries(match_data.get('away_injuries', []))}

== MATCH CONTEXT ==
  {home} Motivation: {ctx.get('home_motivation', 'N/A')}
  {away} Motivation: {ctx.get('away_motivation', 'N/A')}
  Derby/Rivalry: {ctx.get('derby', False)}
  Fixture Congestion: {ctx.get('fixture_congestion', 'N/A')}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. ASIAN HANDICAP ({home} {ah.get('home', 'N/A')}): Will the home team cover the handicap? Factor in xG trends, home advantage, and squad availability.
2. TOTAL GOALS (O/U {total_line}): Projected total goals. Does the xG matchup, defensive quality, and motivation suggest goals or a tight affair?
3. BOTH TEAMS TO SCORE: Will both teams find the net? Factor in defensive vulnerabilities, clean sheet rates, and attacking quality.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""
    logger.debug("Briefing built for %s vs %s: %d chars", home, away, len(briefing))
    return briefing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_briefing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat: rewrite briefing for soccer (xG, AH, BTTS, match context)"
```

---

## Task 12: Rewrite simulate.py (System Prompt + Parsing)

**Files:**
- Modify: `simulate.py`
- Modify: `tests/test_simulate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulate.py
import json
import pytest
from unittest.mock import patch, MagicMock
from simulate import SOCCER_SYSTEM_PROMPT, parse_simulation_result, run_plan_b


def test_system_prompt_is_soccer():
    assert "soccer" in SOCCER_SYSTEM_PROMPT.lower() or "football" in SOCCER_SYSTEM_PROMPT.lower()
    assert "MLB" not in SOCCER_SYSTEM_PROMPT
    assert "pitching" not in SOCCER_SYSTEM_PROMPT.lower()
    assert "asian_handicap" in SOCCER_SYSTEM_PROMPT
    assert "btts" in SOCCER_SYSTEM_PROMPT


def test_parse_simulation_result_soccer():
    raw = json.dumps({
        "analyst_assessments": [
            {"role": "xg_attacking", "pick": "Inter Miami CF", "reasoning": "Strong xG"}
        ],
        "predictions": {
            "asian_handicap": {
                "home_cover_prob": 0.55,
                "away_cover_prob": 0.45,
                "value_side": "home",
                "edge": 0.05,
                "confidence": "medium",
            },
            "total": {
                "projected_goals": 2.8,
                "over_prob": 0.58,
                "under_prob": 0.42,
                "value_side": "over",
                "edge": 0.04,
                "confidence": "medium",
            },
            "btts": {
                "btts_yes_prob": 0.60,
                "btts_no_prob": 0.40,
                "value_side": "yes",
                "edge": 0.05,
                "confidence": "medium",
            },
            "predicted_score": {"home": 2, "away": 1},
            "key_factors": ["xG advantage", "home form"],
        },
    })
    result = parse_simulation_result(raw)
    assert result is not None
    assert "asian_handicap" in result["predictions"]
    assert "btts" in result["predictions"]
    assert result["predictions"]["total"]["projected_goals"] == 2.8


def test_parse_simulation_result_strips_markdown():
    raw = '```json\n{"predictions": {}}\n```'
    result = parse_simulation_result(raw)
    assert result is not None


def test_parse_simulation_result_returns_none_for_garbage():
    assert parse_simulation_result("not json") is None
    assert parse_simulation_result(None) is None
    assert parse_simulation_result("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulate.py -v`
Expected: FAIL — SOCCER_SYSTEM_PROMPT doesn't exist

- [ ] **Step 3: Rewrite simulate.py**

Replace the entire `MLB_SYSTEM_PROMPT` with `SOCCER_SYSTEM_PROMPT` and update `_average_results` probability fields. The `parse_simulation_result`, `run_plan_b`, and `run_mirofish` functions keep the same structure but reference the new prompt.

Key changes:
- Rename `MLB_SYSTEM_PROMPT` -> `SOCCER_SYSTEM_PROMPT`
- New analyst panel: xg_attacking, defensive_tactical, squad_rotation, motivation_context, market, contrarian
- New JSON output: asian_handicap, total, btts (remove moneyline, run_line, first_5)
- Update `_average_results` prob_fields to match new structure
- Update `run_plan_b` to use `SOCCER_SYSTEM_PROMPT`

Full implementation in `simulate.py`:

```python
"""Simulation layer: Plan B (direct Kimi) and MiroFish ensemble."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


SOCCER_SYSTEM_PROMPT = """You are an elite soccer/football prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. xG & ATTACKING ANALYST: Evaluates expected goals data, shot quality,
   chance creation, and whether teams are over/underperforming their xG.
   Teams overperforming xG are regression candidates (bearish). Teams
   underperforming are value candidates (bullish).
2. DEFENSIVE & TACTICAL ANALYST: Evaluates defensive structure, pressing
   intensity (PPDA), clean sheet rate, and how the defensive approach
   matches up against the opponent's attacking style. Set piece vulnerability.
3. SQUAD & ROTATION ANALYST: Evaluates injuries, suspensions, and expected
   rotation. If a team has a Champions League match in 3 days, will they
   rest key players? How deep is the squad? New signings settling in?
4. MOTIVATION & CONTEXT ANALYST: Evaluates what's at stake. Title race teams
   play differently than mid-table teams with nothing to play for. Relegation
   battles create desperate, defensive football. Derbies are unpredictable.
5. MARKET ANALYST: Evaluates the betting lines for value. Is the Asian
   handicap reflecting the true quality gap? Is the total line accounting
   for both teams' xG profiles? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is the home team's form masking
   poor underlying xG numbers? Is the away team better than their league
   position suggests? What narrative is the market overweighting?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "xg_attacking", "pick": "TEAM_OR_SIDE", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "asian_handicap": {
      "home_cover_prob": 0.XX,
      "away_cover_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_goals": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "btts": {
      "btts_yes_prob": 0.XX,
      "btts_no_prob": 0.XX,
      "value_side": "yes|no|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_score": {"home": X, "away": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""


def parse_simulation_result(raw: str | None) -> dict | None:
    """Parse JSON response from LLM, handling common issues."""
    if not raw:
        return None
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
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/match."""
    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=120,
    )

    logger.info("Plan B: starting %d run(s) via %s", runs, KIMI_MODEL)
    results = []
    for run_idx in range(runs):
        try:
            t0 = time.time()
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": SOCCER_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=12288,
            )
            elapsed = time.time() - t0
            choice = response.choices[0]
            if choice.finish_reason == "length":
                logger.warning("Plan B run %d: response truncated", run_idx + 1)
            raw = choice.message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
            else:
                logger.warning("Plan B run %d: failed to parse JSON", run_idx + 1)
        except Exception as e:
            logger.error("Plan B run %d error: %s", run_idx + 1, e)

    if not results:
        return None
    if len(results) == 1:
        return results[0]
    return _average_results(results)


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback."""
    try:
        from ensemble import run_ensemble
        t0 = time.time()
        result = run_ensemble(briefing, odds=odds)
        elapsed = time.time() - t0
        if result:
            meta = result.get("ensemble_meta", {})
            logger.info("MiroFish: ensemble succeeded in %.1fs (phase=%d, calls=%d, cost=$%.4f)",
                        elapsed, meta.get("phase_reached", 0),
                        meta.get("total_calls", 0), meta.get("cost_usd", 0))
            return result
        logger.warning("MiroFish: ensemble returned None, falling back to Plan B")
    except Exception as e:
        logger.error("MiroFish: ensemble failed (%s), falling back to Plan B", e)
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "asian_handicap": ["home_cover_prob", "away_cover_prob", "edge"],
        "total": ["projected_goals", "over_prob", "under_prob", "edge"],
        "btts": ["btts_yes_prob", "btts_no_prob", "edge"],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for f in fields:
            values = []
            for r in results:
                val = r.get("predictions", {}).get(section, {}).get(f)
                if val is not None:
                    values.append(float(val))
            if values:
                preds[section][f] = round(sum(values) / len(values), 4)

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add simulate.py tests/test_simulate.py
git commit -m "feat: rewrite simulate.py with soccer system prompt and bet types"
```

---

## Task 13: Rewrite edge.py for Soccer Bet Types

**Files:**
- Modify: `edge.py`
- Modify: `tests/test_edge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_edge.py
import pytest
from edge import (
    american_to_decimal, kelly_criterion,
    check_asian_handicap_edge, check_total_edge, check_btts_edge,
    analyze_all_edges,
)


def test_american_to_decimal():
    assert american_to_decimal(-110) == pytest.approx(1.9091, abs=0.001)
    assert american_to_decimal(200) == pytest.approx(3.0, abs=0.001)


def test_kelly_criterion():
    assert kelly_criterion(0.55, 2.0) == pytest.approx(0.10, abs=0.01)
    assert kelly_criterion(0.40, 2.0) == 0  # no edge


def test_check_asian_handicap_edge_home():
    sim = {"predictions": {"asian_handicap": {
        "home_cover_prob": 0.60, "away_cover_prob": 0.40,
        "value_side": "home", "confidence": "medium",
    }}}
    odds = {"asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
            "implied_probs": {"ah_home": 0.524, "ah_away": 0.476}}
    result = check_asian_handicap_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "asian_handicap"
    assert result["side"] == "home -0.5"
    assert result["edge"] > 0.05


def test_check_asian_handicap_edge_no_value():
    sim = {"predictions": {"asian_handicap": {
        "home_cover_prob": 0.53, "away_cover_prob": 0.47,
        "confidence": "low",
    }}}
    odds = {"asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
            "implied_probs": {"ah_home": 0.524, "ah_away": 0.476}}
    result = check_asian_handicap_edge(sim, odds)
    assert result is None


def test_check_total_edge_over():
    sim = {"predictions": {"total": {
        "over_prob": 0.62, "under_prob": 0.38,
        "projected_goals": 3.0, "confidence": "high",
    }}}
    odds = {"total": {"line": 2.5, "over_odds": -115, "under_odds": -105}}
    result = check_total_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "total"
    assert "over" in result["side"]


def test_check_btts_edge_yes():
    sim = {"predictions": {"btts": {
        "btts_yes_prob": 0.65, "btts_no_prob": 0.35,
        "confidence": "medium",
    }}}
    odds = {"btts": {"yes_odds": -110, "no_odds": -110},
            "implied_probs": {}}
    result = check_btts_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "btts"
    assert result["side"] == "yes"


def test_check_btts_edge_no_value():
    sim = {"predictions": {"btts": {
        "btts_yes_prob": 0.52, "btts_no_prob": 0.48,
        "confidence": "low",
    }}}
    odds = {"btts": {"yes_odds": -110, "no_odds": -110},
            "implied_probs": {}}
    result = check_btts_edge(sim, odds)
    assert result is None


def test_analyze_all_edges():
    sim = {"predictions": {
        "asian_handicap": {"home_cover_prob": 0.60, "away_cover_prob": 0.40, "confidence": "medium"},
        "total": {"over_prob": 0.62, "under_prob": 0.38, "projected_goals": 3.0, "confidence": "high"},
        "btts": {"btts_yes_prob": 0.65, "btts_no_prob": 0.35, "confidence": "medium"},
    }}
    odds = {
        "asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
        "total": {"line": 2.5, "over_odds": -115, "under_odds": -105},
        "btts": {"yes_odds": -110, "no_odds": -110},
        "implied_probs": {"ah_home": 0.524, "ah_away": 0.476},
    }
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    assert len(bets) <= 3
    # Should NOT contain MLB types
    for b in bets:
        assert b["bet_type"] in ("asian_handicap", "total", "btts")


def test_no_mlb_edge_functions():
    """Ensure MLB edge functions are removed."""
    import edge
    assert not hasattr(edge, "check_moneyline_edge")
    assert not hasattr(edge, "check_run_line_edge")
    assert not hasattr(edge, "check_f5_ml_edge")
    assert not hasattr(edge, "check_f5_total_edge")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite edge.py**

```python
"""Edge detection and Kelly criterion sizing for soccer bet types."""
import logging
from config import EDGE_THRESHOLDS, KELLY_FRACTION
from scrapers.odds import american_to_implied_prob

logger = logging.getLogger("mirofish.edge")


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds < 0:
        return round(100 / abs(odds) + 1, 4)
    return round(odds / 100 + 1, 4)


def kelly_criterion(prob: float, decimal_odds: float) -> float:
    """Calculate Kelly fraction. Returns 0 if no edge."""
    b = decimal_odds - 1
    q = 1 - prob
    if b <= 0:
        return 0
    kelly = (b * prob - q) / b
    return max(0, round(kelly, 4))


def check_asian_handicap_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Asian Handicap value on either side."""
    ah_pred = sim.get("predictions", {}).get("asian_handicap", {})
    ah_odds = odds.get("asian_handicap", {})
    if not ah_pred or not ah_odds:
        return None

    threshold = EDGE_THRESHOLDS["asian_handicap"]

    home_prob = ah_pred.get("home_cover_prob", 0)
    away_prob = ah_pred.get("away_cover_prob", 0)

    home_implied = odds.get("implied_probs", {}).get("ah_home", 0)
    away_implied = odds.get("implied_probs", {}).get("ah_away", 0)

    # If implied probs not pre-computed, compute from odds
    if not home_implied and ah_odds.get("home_odds"):
        h_imp = american_to_implied_prob(ah_odds["home_odds"])
        a_imp = american_to_implied_prob(ah_odds["away_odds"])
        total = h_imp + a_imp
        home_implied = h_imp / total
        away_implied = a_imp / total

    home_edge = home_prob - home_implied
    away_edge = away_prob - away_implied

    home_point = ah_odds.get("home", -0.5)
    away_point = ah_odds.get("away", 0.5)

    if home_edge >= threshold and home_edge >= away_edge:
        dec = american_to_decimal(ah_odds["home_odds"])
        return {
            "bet_type": "asian_handicap",
            "side": f"home {home_point}",
            "odds": ah_odds["home_odds"],
            "sim_prob": home_prob,
            "market_prob": round(home_implied, 4),
            "edge": round(home_edge, 4),
            "kelly_pct": round(kelly_criterion(home_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ah_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        dec = american_to_decimal(ah_odds["away_odds"])
        return {
            "bet_type": "asian_handicap",
            "side": f"away {away_point}",
            "odds": ah_odds["away_odds"],
            "sim_prob": away_prob,
            "market_prob": round(away_implied, 4),
            "edge": round(away_edge, 4),
            "kelly_pct": round(kelly_criterion(away_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ah_pred.get("confidence", "medium"),
        }

    return None


def check_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total goals (over/under) value."""
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

    line = total_odds.get("line", 2.5)

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


def check_btts_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Both Teams to Score value."""
    btts_pred = sim.get("predictions", {}).get("btts", {})
    btts_odds = odds.get("btts", {})
    if not btts_pred or not btts_odds:
        return None

    threshold = EDGE_THRESHOLDS["btts"]

    yes_prob = btts_pred.get("btts_yes_prob", 0)
    no_prob = btts_pred.get("btts_no_prob", 0)

    yes_odds = btts_odds.get("yes_odds", -110)
    no_odds = btts_odds.get("no_odds", -110)
    yes_implied = american_to_implied_prob(yes_odds)
    no_implied = american_to_implied_prob(no_odds)
    total_impl = yes_implied + no_implied
    yes_implied /= total_impl
    no_implied /= total_impl

    yes_edge = yes_prob - yes_implied
    no_edge = no_prob - no_implied

    if yes_edge >= threshold and yes_edge >= no_edge:
        dec = american_to_decimal(yes_odds)
        return {
            "bet_type": "btts",
            "side": "yes",
            "odds": yes_odds,
            "sim_prob": yes_prob,
            "market_prob": round(yes_implied, 4),
            "edge": round(yes_edge, 4),
            "kelly_pct": round(kelly_criterion(yes_prob, dec) * KELLY_FRACTION, 4),
            "confidence": btts_pred.get("confidence", "medium"),
        }
    elif no_edge >= threshold:
        dec = american_to_decimal(no_odds)
        return {
            "bet_type": "btts",
            "side": "no",
            "odds": no_odds,
            "sim_prob": no_prob,
            "market_prob": round(no_implied, 4),
            "edge": round(no_edge, 4),
            "kelly_pct": round(kelly_criterion(no_prob, dec) * KELLY_FRACTION, 4),
            "confidence": btts_pred.get("confidence", "medium"),
        }

    return None


def analyze_all_edges(sim: dict, odds: dict) -> list[dict]:
    """Run all edge checks for a single match. Returns 0-3 bet signals."""
    bets = []
    checkers = [
        ("asian_handicap", check_asian_handicap_edge),
        ("total", check_total_edge),
        ("btts", check_btts_edge),
    ]

    for name, checker in checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])
        else:
            logger.debug("Edge check %s: no value (threshold=%.3f)",
                         name, EDGE_THRESHOLDS.get(name, 0))

    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_edge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: rewrite edge detection for soccer (AH, total, BTTS)"
```

---

## Task 14: Update Ensemble Bet-Slot Constants

**Files:**
- Modify: `ensemble/weights.py`
- Modify: `ensemble/consensus.py`
- Modify: `ensemble/orchestrator.py:33-58`
- Modify: `ensemble/runner.py:7`
- Modify: `ensemble/challenger.py:9-23`
- Modify: `tests/test_ensemble_weights.py`
- Modify: `tests/test_ensemble_consensus.py`
- Modify: `tests/test_ensemble_orchestrator.py`
- Modify: `tests/test_ensemble_runner.py`
- Modify: `tests/test_ensemble_challenger.py`
- Modify: `tests/ensemble_fixtures.py`

- [ ] **Step 1: Update ensemble/weights.py**

Change `BET_SLOTS` from MLB to soccer:

```python
BET_SLOTS = ["asian_handicap", "total", "btts"]
```

- [ ] **Step 2: Update ensemble/consensus.py**

Replace `BET_SLOT_FIELDS`:

```python
BET_SLOT_FIELDS = {
    "asian_handicap": ("asian_handicap", "value_side"),
    "total": ("total", "value_side"),
    "btts": ("btts", "value_side"),
}
```

Remove the `run_line` normalization block in `extract_vote` (lines 22-31). The function becomes:

```python
def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    return raw_vote
```

- [ ] **Step 3: Update ensemble/orchestrator.py constants (lines 33-58)**

Replace the 3 constant dicts:

```python
PROB_FIELDS = {
    "asian_handicap": ["home_cover_prob", "away_cover_prob"],
    "total": ["over_prob", "under_prob", "projected_goals"],
    "btts": ["btts_yes_prob", "btts_no_prob"],
}

SLOT_SECTION = {
    "asian_handicap": "asian_handicap",
    "total": "total",
    "btts": "btts",
}

PRIMARY_PROB_FIELD = {
    "asian_handicap": "home_cover_prob",
    "total": "over_prob",
    "btts": "btts_yes_prob",
}
```

Also update any reference to `market_prob = implied.get("ml_home", 0.5)` to use `"ah_home"` instead. Search for `ml_home` in orchestrator.py and replace.

**CRITICAL: Also rewrite `build_ensemble_result()` lines 414-467.** This section has hardcoded MLB logic:

Replace the confidence section (lines 414-425):
```python
    # Confidence: majority vote across models
    confidence_values = []
    for r in results:
        preds = r["parsed"].get("predictions", {})
        ah_conf = preds.get("asian_handicap", {}).get("confidence")
        if ah_conf:
            confidence_values.append(ah_conf)
    if confidence_values:
        overall_confidence = majority_vote(confidence_values, default="medium")
        for section_key in ["asian_handicap", "total", "btts"]:
            if section_key in predictions and isinstance(predictions[section_key], dict):
                predictions[section_key]["confidence"] = overall_confidence
```

Replace the kill logic (lines 429-467) — remove all `first_5` sub-slot handling:
```python
    # Kill slots from challenger
    for slot in killed_by_challenger:
        section_key = SLOT_SECTION.get(slot, slot)
        predictions.pop(section_key, None)

    # Remove slots with no consensus
    for slot, info in classification.items():
        if info["level"] == "none":
            section_key = SLOT_SECTION[slot]
            predictions.pop(section_key, None)
```

- [ ] **Step 4: Update ensemble/runner.py import (line 7)**

Change:

```python
from simulate import SOCCER_SYSTEM_PROMPT, parse_simulation_result
```

And update `sys_prompt = system_prompt or SOCCER_SYSTEM_PROMPT` (line 49).

- [ ] **Step 5: Update ensemble/challenger.py system prompt (lines 9-23)**

Replace `CHALLENGER_SYSTEM_PROMPT`:

```python
CHALLENGER_SYSTEM_PROMPT = """You are an adversarial analyst reviewing a soccer betting ensemble's output.
Your job is to find flaws, not confirm. Kill bets that don't hold up.

For each bet that passed consensus, respond in valid JSON only:
{
  "challenges": [
    {
      "bet_type": "asian_handicap",
      "verdict": "approve" or "kill",
      "reasoning": "...",
      "flaw_found": null or "description of flaw"
    }
  ]
}
No markdown, no backticks, no preamble. JSON only."""
```

- [ ] **Step 6: Update tests/ensemble_fixtures.py**

Replace mock predictions and odds with soccer equivalents. The mock prediction should have `asian_handicap`, `total`, and `btts` sections. The mock odds should have `asian_handicap`, `total`, `btts`, and `implied_probs` with `ah_home`/`ah_away`.

- [ ] **Step 7: Update ensemble test files**

Update ALL `tests/test_ensemble_*.py` files to reference the new bet slots (`asian_handicap`, `total`, `btts`) instead of MLB slots. Update mock data to use soccer field names. Update `test_ensemble_runner.py` to reference `SOCCER_SYSTEM_PROMPT`.

**Important: Don't miss these files (they also contain MLB bet type references):**
- `tests/test_ensemble_integration.py` — contains `"moneyline"` references, mock predictions with MLB structure
- `tests/test_ensemble_logger.py` — passes `bet_type="moneyline"` in test calls
- `tests/test_ensemble_consensus.py` — references `"run_line"` in vote extraction tests
- `tests/test_ensemble_weights.py` — references old BET_SLOTS list

All of these will fail if not updated.

- [ ] **Step 8: Run all ensemble tests**

Run: `pytest tests/test_ensemble_*.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add ensemble/ tests/ensemble_fixtures.py tests/test_ensemble_*.py
git commit -m "feat: update ensemble bet-slot constants for soccer"
```

---

## Task 15: Rewrite agents/results_grader.py for Soccer

**Files:**
- Modify: `agents/results_grader.py`
- Modify: `tests/test_results_grader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_results_grader.py
import pytest
from agents.results_grader import grade_bet


SCORE = {
    "home": "Inter Miami CF", "away": "LA Galaxy",
    "home_score": 2, "away_score": 1,
    "total_goals": 3, "both_scored": True,
}


def test_grade_asian_handicap_home_covers():
    bet = {"bet_type": "asian_handicap", "side": "home -0.5"}
    # Home won 2-1, adjusted 1.5-1, covers
    assert grade_bet(bet, SCORE) == "W"


def test_grade_asian_handicap_away_covers():
    bet = {"bet_type": "asian_handicap", "side": "away 0.5"}
    score = {"home_score": 1, "away_score": 1, "total_goals": 2, "both_scored": True}
    # Away adjusted 1.5-1, covers
    assert grade_bet(bet, score) == "W"


def test_grade_asian_handicap_push():
    bet = {"bet_type": "asian_handicap", "side": "home -1.0"}
    # Home won 2-1, adjusted 1-1, push
    assert grade_bet(bet, SCORE) == "P"


def test_grade_total_over():
    bet = {"bet_type": "total", "side": "over 2.5"}
    assert grade_bet(bet, SCORE) == "W"  # 3 > 2.5


def test_grade_total_under():
    bet = {"bet_type": "total", "side": "under 2.5"}
    assert grade_bet(bet, SCORE) == "L"  # 3 > 2.5


def test_grade_btts_yes():
    bet = {"bet_type": "btts", "side": "yes"}
    assert grade_bet(bet, SCORE) == "W"  # both scored


def test_grade_btts_no():
    bet = {"bet_type": "btts", "side": "no"}
    assert grade_bet(bet, SCORE) == "L"  # both scored, so "no" loses


def test_grade_btts_no_wins():
    bet = {"bet_type": "btts", "side": "no"}
    score = {"home_score": 1, "away_score": 0, "total_goals": 1, "both_scored": False}
    assert grade_bet(bet, score) == "W"


def test_no_mlb_grading():
    """Ensure MLB bet types are not handled."""
    bet = {"bet_type": "run_line", "side": "home -1.5"}
    assert grade_bet(bet, SCORE) == "L"  # unknown type defaults to L

    bet = {"bet_type": "first_5", "side": "home F5 ML"}
    assert grade_bet(bet, SCORE) == "L"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_results_grader.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite grade_bet in agents/results_grader.py**

Replace the `grade_bet` function body:

```python
def grade_bet(bet_row, score: dict) -> str:
    """Grade a single bet as W/L/P based on final score."""
    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])

    home_score = score["home_score"]
    away_score = score["away_score"]
    total_goals = score.get("total_goals", home_score + away_score)
    both_scored = score.get("both_scored", home_score > 0 and away_score > 0)

    if bet_type == "asian_handicap":
        tokens = side.split()
        ah_side = tokens[0] if tokens else ""
        handicap = float(tokens[1]) if len(tokens) > 1 else 0

        if ah_side == "home":
            adjusted = home_score + handicap
            return "W" if adjusted > away_score else ("P" if adjusted == away_score else "L")
        else:
            adjusted = away_score + handicap
            return "W" if adjusted > home_score else ("P" if adjusted == home_score else "L")

    elif bet_type == "total":
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0

        if direction == "over":
            return "W" if total_goals > line else ("P" if total_goals == line else "L")
        else:
            return "W" if total_goals < line else ("P" if total_goals == line else "L")

    elif bet_type == "btts":
        if side == "yes":
            return "W" if both_scored else "L"
        else:
            return "W" if not both_scored else "L"

    return "L"  # unknown bet type
```

Keep `_match_score`, `run_results_grader`, and the CLI `main()` largely the same, updating the scores import to use the new `get_final_scores(game_date, league)` signature. The `run_results_grader` needs to accept a `league` parameter and pass it to `get_final_scores`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_results_grader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/results_grader.py tests/test_results_grader.py
git commit -m "feat: rewrite results grader for soccer (AH, total, BTTS)"
```

---

## Task 16: Rewrite agents/health_check.py

**Files:**
- Modify: `agents/health_check.py`
- Modify: `tests/test_health_check.py`

- [ ] **Step 1: Replace check_mlb_api with check_espn_api**

```python
def check_espn_api() -> tuple[bool, str]:
    """Check ESPN Soccer API is reachable."""
    try:
        resp = requests.get(f"{ESPN_API_BASE}/usa.1/scoreboard", timeout=10)
        resp.raise_for_status()
        return True, "ESPN Soccer API: OK"
    except Exception as e:
        return False, f"ESPN Soccer API: FAIL ({e})"
```

Update `run_health_check` to use `check_espn_api` instead of `check_mlb_api`, and import `ESPN_API_BASE` from config instead of `MLB_API_BASE`.

- [ ] **Step 2: Update test**

```python
# tests/test_health_check.py
from unittest.mock import patch
from agents.health_check import run_health_check, check_espn_api


@patch("agents.health_check.check_espn_api", return_value=(True, "OK"))
@patch("agents.health_check.check_odds_api", return_value=(True, "OK"))
@patch("agents.health_check.check_openrouter", return_value=(True, "OK"))
@patch("agents.health_check.check_weather_api", return_value=(True, "OK"))
def test_health_check_all_pass(mock_w, mock_or, mock_odds, mock_espn):
    assert run_health_check() is True
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_health_check.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add agents/health_check.py tests/test_health_check.py
git commit -m "feat: update health check for soccer (ESPN API)"
```

---

## Task 17: Rewrite main.py Pipeline

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Rewrite main.py**

The pipeline changes from MLB's pitcher-centric flow to soccer's league-iteration flow:

```python
"""CLI entrypoint for MiroFish Soccer Prediction Pipeline."""
import logging
import time
import click
import signal
from datetime import date

from config import (
    SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT,
    ACTIVE_LEAGUES, SUPPORTED_LEAGUES,
)

logger = logging.getLogger("mirofish")
from scrapers.schedule import get_fixtures
from scrapers.team_stats import get_team_profile
from scrapers.xg import get_xg_profile
from scrapers.injuries import get_squad_injuries
from scrapers.context import get_match_context
from scrapers.odds import get_soccer_odds
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer


class GameTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise GameTimeout("Match processing timed out")


@click.group()
def cli():
    """MiroFish Soccer Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--league", default=None, help="Single league to run (default: all active)")
def daily(game_date, league):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    leagues = [league] if league else ACTIVE_LEAGUES
    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish Soccer Pipeline - {game_date} ===\n")

    total_bets = 0
    total_sim_cost = 0.0

    for lg in leagues:
        click.echo(f"\n--- {lg} ---\n")

        # Step 1: Get fixtures
        click.echo(f"[1/5] Fetching {lg} fixtures...")
        fixtures = get_fixtures(league=lg, game_date=game_date)
        if not fixtures:
            click.echo(f"  No fixtures found for {lg}")
            continue
        click.echo(f"  Found {len(fixtures)} matches")

        # Step 2: Get odds
        click.echo(f"[2/5] Fetching {lg} odds...")
        odds_list = get_soccer_odds(league=lg)
        odds_by_match = {}
        for o in odds_list:
            key = f"{o.away}@{o.home}"
            odds_by_match[key] = o

        # Step 3: Build briefings + screen
        click.echo(f"[3/5] Building briefings and screening...")
        screened = []

        for fixture in fixtures:
            home = fixture["home_team"]
            away = fixture["away_team"]
            match_key = f"{away}@{home}"

            odds = odds_by_match.get(match_key)
            if not odds:
                click.echo(f"  {match_key}: No odds, skipping")
                continue

            try:
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(GAME_TIMEOUT)

                home_stats = get_team_profile(home, league=lg)
                away_stats = get_team_profile(away, league=lg)
                home_xg = get_xg_profile(home, league=lg)
                away_xg = get_xg_profile(away, league=lg)
                home_injuries = get_squad_injuries(home, league=lg)
                away_injuries = get_squad_injuries(away, league=lg)
                context = get_match_context(home, away, league=lg)

                match_data = {
                    "home_team": home,
                    "away_team": away,
                    "league": lg,
                    "matchday": fixture.get("matchday", ""),
                    "venue": fixture.get("venue", ""),
                    "kickoff_time": fixture.get("kickoff_time", ""),
                    "odds": {
                        "asian_handicap": odds.asian_handicap,
                        "total": odds.total,
                        "btts": odds.btts,
                        "moneyline_1x2": odds.moneyline_1x2,
                        "implied_probs": odds.implied_probs,
                    },
                    "home_stats": home_stats,
                    "away_stats": away_stats,
                    "home_xg": home_xg,
                    "away_xg": away_xg,
                    "home_injuries": home_injuries,
                    "away_injuries": away_injuries,
                    "context": context,
                }

                brief = build_briefing(match_data)
                click.echo(f"  Screening {match_key}...")
                screen = run_plan_b(brief)
                if not screen:
                    click.echo(f"    Screen failed, skipping")
                    continue

                edges = analyze_all_edges(screen, match_data["odds"])
                max_edge = max((e["edge"] for e in edges), default=0)

                if max_edge >= SCREEN_EDGE_THRESHOLD:
                    click.echo(f"    FLAGGED - max edge {max_edge:.1%}")
                    screened.append((match_key, brief, match_data))
                else:
                    click.echo(f"    No edge (max {max_edge:.1%})")

            except GameTimeout:
                click.echo(f"  {match_key}: TIMEOUT, skipping")
                continue
            except Exception as e:
                click.echo(f"  {match_key}: ERROR - {e}, skipping")
                continue
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        # Step 4: Full sim on flagged matches
        click.echo(f"\n[4/5] Full simulation on {len(screened)} flagged matches...")

        for match_key, brief, match_data in screened:
            click.echo(f"\n  === {match_key} ===")
            try:
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(GAME_TIMEOUT)

                result = run_mirofish(brief, runs=3, odds=match_data["odds"])
                if not result:
                    click.echo("    Simulation failed")
                    continue

                meta = result.get("ensemble_meta", {})
                total_sim_cost += meta.get("cost_usd", 0)

                bets = analyze_all_edges(result, match_data["odds"])
                if not bets:
                    click.echo("    No bets after full sim")
                    continue

                for bet in bets:
                    bet["date"] = game_date
                    bet["game"] = match_key
                    click.echo(
                        f"    BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                        f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                    )
                    log_bet(bet)
                    total_bets += 1

            except GameTimeout:
                click.echo(f"    TIMEOUT, skipping")
                continue
            except Exception as e:
                click.echo(f"    ERROR - {e}, skipping")
                continue
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

    elapsed = time.time() - pipeline_start
    click.echo(f"\n=== Done. {total_bets} bets logged. Cost: ${total_sim_cost:.4f}. Time: {elapsed:.0f}s ===")


@cli.command()
@click.argument("away_team")
@click.argument("home_team")
@click.option("--date", "game_date", default=None)
@click.option("--league", default="MLS", help="League name")
def match(away_team, home_team, game_date, league):
    """Analyze a single match."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {away_team}@{home_team} ({league}) on {game_date}...")

    odds_list = get_soccer_odds(league=league)
    game_odds = None
    for o in odds_list:
        if o.away == away_team and o.home == home_team:
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this match.")
        return

    home_stats = get_team_profile(home_team, league=league)
    away_stats = get_team_profile(away_team, league=league)
    home_xg = get_xg_profile(home_team, league=league)
    away_xg = get_xg_profile(away_team, league=league)
    context = get_match_context(home_team, away_team, league=league)

    match_data = {
        "home_team": home_team,
        "away_team": away_team,
        "league": league,
        "odds": {
            "asian_handicap": game_odds.asian_handicap,
            "total": game_odds.total,
            "btts": game_odds.btts,
            "moneyline_1x2": game_odds.moneyline_1x2,
            "implied_probs": game_odds.implied_probs,
        },
        "home_stats": home_stats,
        "away_stats": away_stats,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_injuries": get_squad_injuries(home_team, league=league),
        "away_injuries": get_squad_injuries(away_team, league=league),
        "context": context,
    }

    brief = build_briefing(match_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3, odds=match_data["odds"])
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, match_data["odds"])
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


@cli.command()
@click.option("--date", "game_date", default=None)
def results(game_date):
    """Grade pending bets against final scores."""
    run_results_grader(game_date)


@cli.command()
@click.option("--date", "game_date", default=None)
def card(game_date):
    """Display formatted bet card."""
    click.echo(format_bet_card(game_date))


@cli.command()
def health():
    """Run pre-game health check."""
    run_health_check()


@cli.command()
@click.option("--min-bets", default=30)
def optimize(min_bets):
    """Analyze performance and recommend adjustments."""
    run_optimizer(min_bets)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Update tests/test_main.py**

Update the test to verify the CLI group exists and the `daily` command accepts `--league`:

```python
# tests/test_main.py
from click.testing import CliRunner
from main import cli


def test_cli_group():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Soccer" in result.output


def test_daily_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["daily", "--help"])
    assert result.exit_code == 0
    assert "--league" in result.output


def test_match_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["match", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: rewrite main.py pipeline for soccer (multi-league, match command)"
```

---

## Task 18: Update Daily Runner Agent

**Files:**
- Modify: `agents/daily_runner.py`

- [ ] **Step 1: Update daily_runner.py**

The daily runner needs minor updates: change CLI text from "MLB" to "Soccer" and ensure the subprocess call matches the new `daily` command signature.

- [ ] **Step 2: Commit**

```bash
git add agents/daily_runner.py
git commit -m "chore: update daily runner for soccer pipeline"
```

---

## Task 19: Run Full Test Suite & Fix Remaining Issues

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | head -100
```

- [ ] **Step 2: Fix any remaining import errors**

Likely issues:
- Stale imports in `scrapers/__init__.py` (should be empty, verify)
- `tests/test_ensemble_integration.py` may reference MLB-specific mocks
- `tests/test_self_optimizer.py` may reference old bet types in fixtures

- [ ] **Step 3: Run full suite again to confirm clean**

```bash
pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: resolve remaining test failures after soccer migration"
```

---

## Task 20: Clean Up Remaining MLB References

- [ ] **Step 1: Search for any remaining MLB references**

```bash
grep -ri "mlb\|baseball\|pitcher\|bullpen\|run_line\|first_5\|f5_\|park_factor\|ballpark\|inning" --include="*.py" . | grep -v __pycache__ | grep -v ".pyc"
```

- [ ] **Step 2: Fix any remaining references found**

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: remove all remaining MLB references"
```

---

## Summary of Bet Type Mapping

| MLB (removed) | Soccer (new) | Notes |
|---|---|---|
| moneyline | — | Avoided (3-way draw issue). 1X2 kept informational only |
| run_line | asian_handicap | Variable spread (-0.5, -1.0, -1.5) vs fixed -1.5 |
| total | total | O/U runs → O/U 2.5 goals |
| first_5_ml | — | No soccer equivalent |
| first_5_total | — | No soccer equivalent |
| — | btts | NEW: Both Teams to Score |

## Key Architecture Decisions

1. **Eighth-Kelly (0.125)** — Soccer averages ~2.5 goals vs ~9 runs. Higher variance demands more conservative sizing.
2. **No 1X2 as primary bet** — Draw exists in ~25% of matches, making calibration much harder. Asian Handicap removes the draw.
3. **Multi-league iteration** — Unlike MLB (one league), the daily pipeline iterates through ACTIVE_LEAGUES.
4. **xG regression as primary edge** — The xG scraper is critical infrastructure. Teams overperforming xG are short candidates.
5. **ESPN API for schedule/scores** — Free, no API key needed, reliable for MLS/European leagues.
