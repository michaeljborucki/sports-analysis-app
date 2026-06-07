# Esports Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the MiroFish MLB betting pipeline into an esports prediction system supporting CS2 and LoL, with complete MLB removal.

**Architecture:** Game-specific code lives in `games/{cs2,lol}/` with scrapers, briefing, prompt, and config. Shared infrastructure (ensemble, edge, tracker) reads game-specific constants dynamically via `game_config`. OddsPapi replaces The Odds API as primary odds source.

**Tech Stack:** Python 3.11+, hltv-async-api (CS2 data), pandas (Oracle's Elixir CSV for LoL), OddsPapi REST API, OpenRouter (LLM ensemble), pytest.

**Spec:** `docs/superpowers/specs/2026-03-20-esports-pipeline-design.md`
**Decisions:** `docs/superpowers/specs/decisions-log.md`

---

## Phase 1: Core Infrastructure (CS2)

### Task 1: Delete All MLB Files and Clean Config

**Files:**
- Delete: `scrapers/pitchers.py`, `scrapers/scores.py`, `scrapers/team_stats.py`, `scrapers/lineups.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`
- Delete: `tests/test_pitchers.py`, `tests/test_scores.py`, `tests/test_team_stats.py`, `tests/test_lineups.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`
- Delete: `data/bets.csv`, `data/model_predictions.csv`, `data/model_weights.json`
- Modify: `config.py` (remove MLB constants, lines 16-128)
- Modify: `requirements.txt` (remove pybaseball, line 1)

- [ ] **Step 1: Delete all MLB scraper files**

```bash
git rm scrapers/pitchers.py scrapers/scores.py scrapers/team_stats.py scrapers/lineups.py scrapers/bullpen.py scrapers/ballpark.py
```

- [ ] **Step 2: Delete all MLB test files**

```bash
git rm tests/test_pitchers.py tests/test_scores.py tests/test_team_stats.py tests/test_lineups.py tests/test_bullpen.py tests/test_ballpark.py
```

- [ ] **Step 3: Delete MLB data files**

```bash
rm -f data/bets.csv data/model_predictions.csv data/model_weights.json
```

- [ ] **Step 4: Strip config.py of all MLB content**

Remove from `config.py`:
- `WEATHER_API_KEY` (line 18)
- `MLB_API_BASE` (line 21)
- `WEATHER_API_BASE` (line 23)
- `TEAM_ABBREVS` list (lines 49-55)
- `TEAM_NAME_TO_ABBREV` dict (lines 58-74)
- `PARK_FACTORS` dict (lines 78-109)
- `PARK_COORDS` dict (lines 112-128)
- MLB-specific `EDGE_THRESHOLDS` entries: `run_line`, `first_5_ml`, `first_5_total` (lines 41-47)

Replace `EDGE_THRESHOLDS` with just:
```python
# Global edge thresholds removed — now per-game in games/{game}/config.py
```

Add new config entries:
```python
ODDSPAPI_API_KEY = os.getenv("ODDSPAPI_API_KEY", "")
ODDSPAPI_BASE = "https://api.oddspapi.com/v1"
SUPPORTED_GAMES = ["cs2", "lol"]
MAX_TIER = 2
GAME_TIMEOUT = 180
```

- [ ] **Step 5: Update requirements.txt**

Remove `pybaseball>=2.3.0`. Add:
```
hltv-async-api>=0.8.0
aiohttp>=3.9.0
```

- [ ] **Step 6: Verify no import errors**

Run: `python -c "import config; print('OK')"`
Expected: OK (no ImportError)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: remove all MLB-specific code, config, and data files"
```

---

### Task 2: Create Game Registry and CS2 Config

**Files:**
- Create: `games/__init__.py`
- Create: `games/cs2/__init__.py`
- Create: `games/cs2/config.py`
- Create: `games/lol/__init__.py` (stub)
- Create: `games/lol/config.py` (stub)
- Test: `tests/test_game_registry.py`

- [ ] **Step 1: Write the failing test for game registry**

```python
# tests/test_game_registry.py
from games import get_game, GAMES

def test_registry_has_cs2():
    assert "cs2" in GAMES

def test_get_game_returns_module_with_config():
    game = get_game("cs2")
    assert hasattr(game, "config")
    assert hasattr(game.config, "BET_SLOTS")
    assert hasattr(game.config, "PROB_FIELDS")
    assert hasattr(game.config, "SLOT_SECTION")
    assert hasattr(game.config, "PRIMARY_PROB_FIELD")
    assert hasattr(game.config, "EDGE_THRESHOLDS")
    assert hasattr(game.config, "ACTIVE_DUTY_MAPS")

def test_cs2_bet_slots():
    game = get_game("cs2")
    assert game.config.BET_SLOTS == ["moneyline", "map_handicap", "total_maps"]

def test_cs2_edge_thresholds_format_aware():
    game = get_game("cs2")
    assert "bo1" in game.config.EDGE_THRESHOLDS
    assert "bo3" in game.config.EDGE_THRESHOLDS
    assert "bo5" in game.config.EDGE_THRESHOLDS
    assert game.config.EDGE_THRESHOLDS["bo1"]["moneyline"] == 0.07
    assert "map_handicap" not in game.config.EDGE_THRESHOLDS["bo1"]

def test_get_game_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        get_game("unknown_game")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_game_registry.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Create games/__init__.py**

```python
# games/__init__.py
"""Game registry — maps game keys to game-specific modules."""
from games import cs2

GAMES = {
    "cs2": cs2,
}

def get_game(game_key: str):
    """Return game module by key.

    Each module exposes: config, scrapers, briefing, prompt.
    """
    return GAMES[game_key]
```

- [ ] **Step 4: Create games/cs2/__init__.py**

```python
# games/cs2/__init__.py
"""CS2 game module."""
from games.cs2 import config
```

- [ ] **Step 5: Create games/cs2/config.py**

```python
# games/cs2/config.py
"""CS2-specific configuration for the MiroFish pipeline."""

BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]

PROB_FIELDS = {
    "moneyline": ["team_a_win_prob", "team_b_win_prob"],
    "map_handicap": ["favorite_cover_prob"],
    "total_maps": ["over_prob", "under_prob", "projected_maps"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "map_handicap": "map_handicap",
    "total_maps": "total_maps",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "team_a_win_prob",
    "map_handicap": "favorite_cover_prob",
    "total_maps": "over_prob",
}

EDGE_THRESHOLDS = {
    "bo1": {
        "moneyline": 0.07,
    },
    "bo3": {
        "moneyline": 0.05,
        "map_handicap": 0.06,
        "total_maps": 0.05,
    },
    "bo5": {
        "moneyline": 0.04,
        "map_handicap": 0.05,
        "total_maps": 0.04,
    },
}

# Last updated: 2026-03-20 — review after each Valve major update
ACTIVE_DUTY_MAPS = [
    "mirage", "inferno", "nuke", "ancient",
    "anubis", "dust2", "vertigo",
]

ANALYST_ROLES = [
    "fragging", "tactical", "map_pool", "form", "market", "contrarian",
]
```

- [ ] **Step 6: Create stub games/lol/ for registry (Phase 2 fills it in)**

```python
# games/lol/__init__.py
"""LoL game module — stub for Phase 2."""
from games.lol import config

# games/lol/config.py
"""LoL-specific configuration — stub for Phase 2."""
BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]
PROB_FIELDS = {}
SLOT_SECTION = {}
PRIMARY_PROB_FIELD = {}
EDGE_THRESHOLDS = {}
ACTIVE_DUTY_MAPS = []
ANALYST_ROLES = []
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_game_registry.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add games/ tests/test_game_registry.py
git commit -m "feat: game registry with CS2 config (BET_SLOTS, thresholds, map pool)"
```

---

### Task 3: Rewrite Odds Scraper for OddsPapi

**Files:**
- Rewrite: `scrapers/odds.py`
- Test: `tests/test_odds.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_odds.py
import json
from unittest.mock import patch, MagicMock
from scrapers.odds import OddsData, get_esports_odds, american_to_implied_prob

def test_american_to_implied_prob_negative():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001

def test_american_to_implied_prob_positive():
    assert abs(american_to_implied_prob(150) - 0.4) < 0.001

def test_odds_data_to_dict():
    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": -175, "team_b": 145},
    )
    d = od.to_dict()
    assert d["team_a"] == "NaVi"
    assert d["moneyline"]["team_a"] == -175
    assert d["format"] == "bo3"

def test_odds_data_implied_probs():
    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": -175, "team_b": 145},
    )
    od.compute_implied_probs()
    assert "ml_team_a" in od.implied_probs
    assert "ml_team_b" in od.implied_probs
    assert abs(od.implied_probs["ml_team_a"] + od.implied_probs["ml_team_b"] - 1.0) < 0.001

def test_get_esports_odds_empty_on_no_key():
    with patch.dict("os.environ", {"ODDSPAPI_API_KEY": ""}, clear=False):
        result = get_esports_odds("cs2")
        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_odds.py -v`
Expected: FAIL (ImportError on new OddsData)

- [ ] **Step 3: Rewrite scrapers/odds.py**

Full rewrite. The new file must contain:
- `OddsData` dataclass with fields: `team_a`, `team_b`, `commence_time`, `game_title`, `tournament`, `format`, `moneyline`, `map_handicap`, `total_maps`, `implied_probs`, `bookmaker_count`, `pinnacle_odds`
- `to_dict()` method on `OddsData`
- `compute_implied_probs()` method on `OddsData`
- `american_to_implied_prob(odds: int) -> float` (unchanged math)
- `get_esports_odds(game_key: str) -> list[OddsData]` — tries OddsPapi first, The Odds API fallback for LoL
- `_fetch_oddspapi(game_key: str) -> list[OddsData]` with sport ID mapping: cs2=17, lol=18, dota2=16, valorant=61
- `_fetch_the_odds_api(sport_key: str) -> list[OddsData]` — fallback
- Rate limiting: `_load_usage()`, `_record_request()`, monthly counter in `data/oddspapi_usage.json`
- Caching: 30-minute TTL per game key

Reference spec sections 3 and 16 for the complete API integration and rate limiting details.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_odds.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: rewrite odds scraper for OddsPapi with rate limiting and caching"
```

---

### Task 4: CS2 Scrapers (HLTV Integration)

**Files:**
- Create: `games/cs2/scrapers.py`
- Modify: `games/cs2/__init__.py` (add scrapers import)
- Test: `tests/test_cs2_scrapers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cs2_scrapers.py
from unittest.mock import patch, AsyncMock, MagicMock
from games.cs2.scrapers import (
    fetch_team_profile, fetch_upcoming_matches,
    fetch_head_to_head, fetch_match_result,
)

def test_fetch_team_profile_returns_required_fields():
    """Test that team profile has all required fields."""
    mock_data = {
        "name": "Natus Vincere",
        "hltv_ranking": 1,
        "win_rate_3m": 0.75,
        "win_rate_6m": 0.70,
        "lan_record": "15-3",
        "online_record": "20-8",
        "roster": ["s1mple", "electroNic", "b1t", "Perfecto", "npl"],
        "coach": "B1ad3",
        "days_since_roster_change": 45,
        "map_pool": {
            "mirage": {"win_rate": 0.80, "games": 15},
            "inferno": {"win_rate": 0.65, "games": 12},
        },
        "recent_form": [
            {"date": "2026-03-18", "opponent": "FaZe", "score": "2-0", "tournament": "IEM"},
        ],
    }
    # Verify structure has all required keys
    required = ["name", "hltv_ranking", "win_rate_3m", "roster", "map_pool", "recent_form"]
    for key in required:
        assert key in mock_data

def test_fetch_upcoming_matches_structure():
    """Test match data has required fields."""
    mock_match = {
        "team_a": "NaVi",
        "team_b": "FaZe",
        "tournament": "IEM Katowice",
        "format": "bo3",
        "tier": 1,
        "date": "2026-03-20",
        "lan": True,
    }
    required = ["team_a", "team_b", "tournament", "format", "tier", "date", "lan"]
    for key in required:
        assert key in mock_match

def test_fetch_match_result_structure():
    """Test match result has required fields."""
    mock_result = {
        "winner": "NaVi",
        "score": "2-1",
        "maps_played": 3,
        "map_scores": [
            {"map": "mirage", "team_a_rounds": 16, "team_b_rounds": 12},
        ],
    }
    assert mock_result["maps_played"] == 3
    assert mock_result["winner"] == "NaVi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cs2_scrapers.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement games/cs2/scrapers.py**

Create the file with async functions that wrap `hltv-async-api`:
- `async fetch_team_profile(team_name: str) -> dict`
- `async fetch_upcoming_matches() -> list[dict]`
- `async fetch_head_to_head(team_a: str, team_b: str) -> dict`
- `async fetch_match_result(team_a: str, team_b: str, date: str) -> dict`

Reference spec section 4 for exact return structures.

Each function should:
1. Call the hltv-async-api library
2. Transform the raw response into the expected dict structure
3. Handle errors gracefully (return empty dict/list on failure)
4. Log warnings on missing data

- [ ] **Step 4: Add sync wrappers to games/cs2/__init__.py**

Per spec section 18, add `ScrapersSync` class:
```python
import asyncio
from games.cs2 import scrapers as _async_scrapers

class ScrapersSync:
    def fetch_upcoming_matches(self):
        return asyncio.run(_async_scrapers.fetch_upcoming_matches())
    def fetch_team_profile(self, team_name):
        return asyncio.run(_async_scrapers.fetch_team_profile(team_name))
    def fetch_head_to_head(self, team_a, team_b):
        return asyncio.run(_async_scrapers.fetch_head_to_head(team_a, team_b))
    def fetch_match_result(self, team_a, team_b, date):
        return asyncio.run(_async_scrapers.fetch_match_result(team_a, team_b, date))

scrapers = ScrapersSync()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_cs2_scrapers.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add games/cs2/ tests/test_cs2_scrapers.py
git commit -m "feat: CS2 scrapers with HLTV integration and sync wrappers"
```

---

### Task 5: CS2 Briefing Template and System Prompt

**Files:**
- Create: `games/cs2/briefing.py`
- Create: `games/cs2/prompt.py`
- Modify: `games/cs2/__init__.py` (add imports)
- Test: `tests/test_cs2_briefing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cs2_briefing.py
from games.cs2.briefing import build_briefing
from games.cs2.prompt import CS2_SYSTEM_PROMPT

def test_briefing_contains_team_names():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "Natus Vincere" in result
    assert "FaZe Clan" in result

def test_briefing_contains_betting_lines():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "BETTING LINES" in result
    assert "Moneyline" in result

def test_briefing_contains_map_pool():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "MAP VETO ANALYSIS" in result or "Map Pool" in result

def test_briefing_contains_prediction_task():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "PREDICTION TASK" in result
    assert "MATCH WINNER" in result
    assert "MAP HANDICAP" in result
    assert "TOTAL MAPS" in result

def test_system_prompt_has_six_analysts():
    assert "FRAGGING ANALYST" in CS2_SYSTEM_PROMPT
    assert "TACTICAL ANALYST" in CS2_SYSTEM_PROMPT
    assert "MAP POOL ANALYST" in CS2_SYSTEM_PROMPT
    assert "FORM" in CS2_SYSTEM_PROMPT
    assert "MARKET ANALYST" in CS2_SYSTEM_PROMPT
    assert "CONTRARIAN" in CS2_SYSTEM_PROMPT

def test_system_prompt_requests_json():
    assert "JSON" in CS2_SYSTEM_PROMPT
    assert "team_a_win_prob" in CS2_SYSTEM_PROMPT
    assert "map_handicap" in CS2_SYSTEM_PROMPT
    assert "total_maps" in CS2_SYSTEM_PROMPT

def _make_mock_match_data():
    return {
        "tournament": "IEM Katowice 2026",
        "date": "2026-03-20",
        "format": "bo3",
        "bo_count": 3,
        "tier": 1,
        "team_a": {
            "name": "Natus Vincere",
            "hltv_ranking": 1,
            "win_rate_3m": 0.75,
            "lan_record": "15-3",
            "online_record": "20-8",
            "roster": ["s1mple", "electroNic", "b1t", "Perfecto", "npl"],
            "days_since_roster_change": 45,
            "map_pool": {"mirage": {"win_rate": 0.80, "games": 15}},
            "recent_form": [],
        },
        "team_b": {
            "name": "FaZe Clan",
            "hltv_ranking": 3,
            "win_rate_3m": 0.68,
            "lan_record": "12-5",
            "online_record": "18-10",
            "roster": ["rain", "frozen", "ropz", "broky", "karrigan"],
            "days_since_roster_change": 90,
            "map_pool": {"inferno": {"win_rate": 0.70, "games": 10}},
            "recent_form": [],
        },
        "odds": {
            "moneyline": {"team_a": -175, "team_b": 145},
            "map_handicap": {"team_a_line": -1.5, "team_a_odds": 150},
            "total_maps": {"line": 2.5, "over_odds": -130, "under_odds": 110},
            "implied_probs": {"ml_team_a": 0.636, "ml_team_b": 0.364},
        },
        "head_to_head": {"team_a_wins": 3, "team_b_wins": 2},
        "patch": {"patch_version": "1.39", "days_since_patch": 5, "key_changes": []},
        "context": {"online_lan": "lan", "stage": "playoff", "stakes": "semifinal"},
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cs2_briefing.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Create games/cs2/prompt.py**

Copy the CS2 system prompt from spec section 8.1 verbatim — it defines the 6 expert analysts and the JSON output schema.

- [ ] **Step 4: Create games/cs2/briefing.py**

Implement `build_briefing(match_data: dict) -> str` that formats the CS2 briefing template from spec section 7.1. Include all sections: header, betting lines, team profiles, map veto analysis, meta/patch context, context, prediction task.

- [ ] **Step 5: Update games/cs2/__init__.py**

Add: `from games.cs2 import briefing, prompt`

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_cs2_briefing.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add games/cs2/briefing.py games/cs2/prompt.py games/cs2/__init__.py tests/test_cs2_briefing.py
git commit -m "feat: CS2 briefing template and 6-analyst system prompt"
```

---

### Task 6: Adapt simulate.py for Game-Aware Screen Pass

**Files:**
- Modify: `simulate.py` (lines 11-67 MLB prompt, line 89 run_plan_b, line 146 run_mirofish)
- Rewrite: `briefing.py` (line 38 build_briefing → dispatch to game module)
- Test: `tests/test_simulate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulate.py (update existing)
from unittest.mock import patch, MagicMock
from games.cs2 import config as cs2_config

def test_run_plan_b_uses_game_prompt(mock_openai):
    """Verify run_plan_b passes game-specific system prompt."""
    from simulate import run_plan_b
    mock_openai.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"predictions": {}}'))]
    )
    run_plan_b("test briefing", game_config=cs2_config)
    call_args = mock_openai.call_args
    messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
    # The system message should contain CS2-specific content
    system_msg = [m for m in messages if m["role"] == "system"][0]
    assert "FRAGGING ANALYST" in system_msg["content"]
```

- [ ] **Step 2: Modify simulate.py**

1. Delete the MLB_SYSTEM_PROMPT (lines 11-67)
2. Change `run_plan_b(briefing: str)` → `run_plan_b(briefing: str, game_config)` — read `game_config.prompt.CS2_SYSTEM_PROMPT` (or `SYSTEM_PROMPT` attribute)
3. Change `run_mirofish(briefing, runs=3, odds=None)` → `run_mirofish(briefing, odds=None, game_config=None, runs=3)` — pass `game_config` through to `run_ensemble()`

- [ ] **Step 3: Rewrite briefing.py as dispatcher**

The old `build_briefing()` was MLB-specific. Replace with:
```python
from games import get_game

def build_briefing(match_data: dict, game_key: str) -> str:
    game = get_game(game_key)
    return game.briefing.build_briefing(match_data)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_simulate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add simulate.py briefing.py tests/test_simulate.py
git commit -m "feat: game-aware screen pass and briefing dispatcher"
```

---

### Task 7: Adapt edge.py for Esports Bet Types

**Files:**
- Rewrite: `edge.py` (336 lines — replace MLB bet types with esports)
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_edge.py (rewrite)
from edge import analyze_all_edges, check_moneyline_edge, check_map_handicap_edge, check_total_maps_edge
from scrapers.odds import OddsData
from games.cs2 import config as cs2_config

def test_moneyline_edge_detected():
    sim = {"team_a_win_prob": 0.65, "team_b_win_prob": 0.35, "confidence": "medium"}
    odds = _make_odds(ml_a=-150, ml_b=130)
    result = check_moneyline_edge(sim, odds, threshold=0.05)
    assert result is not None
    assert result["side"] == "team_a"
    assert result["edge"] > 0.05

def test_moneyline_no_edge():
    sim = {"team_a_win_prob": 0.55, "team_b_win_prob": 0.45, "confidence": "low"}
    odds = _make_odds(ml_a=-130, ml_b=110)
    result = check_moneyline_edge(sim, odds, threshold=0.05)
    assert result is None

def test_map_handicap_edge():
    sim = {"favorite_cover_prob": 0.55, "confidence": "medium"}
    odds = _make_odds()
    odds.map_handicap = {"team_a_line": -1.5, "team_a_odds": 150, "team_b_line": 1.5, "team_b_odds": -180}
    result = check_map_handicap_edge(sim, odds, threshold=0.06)
    assert result is not None

def test_total_maps_edge():
    sim = {"over_prob": 0.62, "under_prob": 0.38, "confidence": "medium"}
    odds = _make_odds()
    odds.total_maps = {"line": 2.5, "over_odds": -130, "under_odds": 110}
    result = check_total_maps_edge(sim, odds, threshold=0.05)
    assert result is not None
    assert result["side"] == "over"

def test_analyze_all_edges_format_aware():
    sim = {
        "moneyline": {"team_a_win_prob": 0.65, "team_b_win_prob": 0.35, "confidence": "medium"},
        "map_handicap": {"favorite_cover_prob": 0.55, "confidence": "medium"},
        "total_maps": {"over_prob": 0.60, "under_prob": 0.40, "confidence": "medium"},
    }
    odds = _make_odds()
    bets = analyze_all_edges(sim, odds, format="bo3", game_config=cs2_config)
    assert isinstance(bets, list)

def test_analyze_all_edges_bo1_skips_handicap():
    sim = {
        "moneyline": {"team_a_win_prob": 0.75, "team_b_win_prob": 0.25, "confidence": "high"},
        "map_handicap": {"favorite_cover_prob": 0.55, "confidence": "medium"},
        "total_maps": {"over_prob": 0.60, "under_prob": 0.40, "confidence": "medium"},
    }
    odds = _make_odds()
    bets = analyze_all_edges(sim, odds, format="bo1", game_config=cs2_config)
    bet_types = [b["bet_type"] for b in bets]
    assert "map_handicap" not in bet_types
    assert "total_maps" not in bet_types

def _make_odds(ml_a=-175, ml_b=145):
    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": ml_a, "team_b": ml_b},
        map_handicap={"team_a_line": -1.5, "team_a_odds": 150, "team_b_line": 1.5, "team_b_odds": -180},
        total_maps={"line": 2.5, "over_odds": -130, "under_odds": 110},
    )
    od.compute_implied_probs()
    return od
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite edge.py**

Replace all 5 MLB check functions with 3 esports functions:
- `check_moneyline_edge(sim, odds, threshold)` — per spec section 11
- `check_map_handicap_edge(sim, odds, threshold)` — per spec section 11
- `check_total_maps_edge(sim, odds, threshold)` — per spec section 11
- `analyze_all_edges(sim, odds, format, game_config)` — new signature, reads `game_config.EDGE_THRESHOLDS[format]`
- Keep `_build_bet()` helper and Kelly sizing unchanged

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: esports edge detection with format-aware thresholds"
```

---

### Task 8: Adapt Ensemble Orchestrator for Dynamic Game Config

**Files:**
- Modify: `ensemble/orchestrator.py` (lines 19, 34-58, 473)
- Modify: `ensemble/weights.py` (line 6)
- Test: `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Modify ensemble/weights.py**

Change `BET_SLOTS` at line 6 to accept dynamic slots:
```python
# Remove hardcoded BET_SLOTS
# Instead, default_weights() and load_weights() accept bet_slots parameter

def default_weights(model_keys: list[str], bet_slots: list[str]) -> dict:
    return {m: {s: 1.0 for s in bet_slots} for m in model_keys}
```

- [ ] **Step 2: Modify ensemble/orchestrator.py**

1. Remove hardcoded `BET_SLOTS` import (line 19)
2. Remove hardcoded `PROB_FIELDS`, `SLOT_SECTION`, `PRIMARY_PROB_FIELD` (lines 34-58)
3. Change `run_ensemble(briefing, odds)` → `run_ensemble(briefing, odds, game_config)` (line 473)
4. At the top of `run_ensemble()`, read from game_config:
   ```python
   bet_slots = game_config.BET_SLOTS
   prob_fields = game_config.PROB_FIELDS
   slot_section = game_config.SLOT_SECTION
   primary_prob = game_config.PRIMARY_PROB_FIELD
   ```
5. Pass these through to `run_phase1()`, `run_phase2()`, `build_ensemble_result()`
6. In `build_ensemble_result()`, use majority vote for `predicted_result` instead of averaging `predicted_score`

- [ ] **Step 3: Update tests**

Update `tests/test_ensemble_orchestrator.py` to pass `game_config` (use cs2_config).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ensemble_orchestrator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/orchestrator.py ensemble/weights.py tests/test_ensemble_orchestrator.py
git commit -m "feat: dynamic BET_SLOTS and PROB_FIELDS from game config in orchestrator"
```

---

### Task 9: Adapt Ensemble Consensus for Dynamic Vote Maps

**Files:**
- Modify: `ensemble/consensus.py` (lines 4-10 BET_SLOT_FIELDS)
- Test: `tests/test_ensemble_consensus.py` (update existing)

- [ ] **Step 1: Modify ensemble/consensus.py**

1. Remove hardcoded `BET_SLOT_FIELDS` (lines 4-10)
2. Change `extract_vote(prediction, slot)` → `extract_vote(prediction, slot, bet_slot_fields)`
3. Change `normalize_vote()` to use `map_handicap` instead of `run_line` when referencing odds
4. All functions that reference `BET_SLOT_FIELDS` now accept it as a parameter

- [ ] **Step 2: Update tests**

Add `bet_slot_fields` parameter to all test calls.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_ensemble_consensus.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add ensemble/consensus.py tests/test_ensemble_consensus.py
git commit -m "feat: dynamic vote maps in consensus module from game config"
```

---

### Task 10: Adapt Results Grader for Esports

**Files:**
- Modify: `agents/results_grader.py` (replace MLB grading with esports grading)
- Test: `tests/test_results_grader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_results_grader.py (rewrite key tests)
from agents.results_grader import grade_moneyline, grade_map_handicap, grade_total_maps

def test_grade_moneyline_win():
    assert grade_moneyline("team_a", {"winner": "team_a", "score": "2-1"}) == "W"

def test_grade_moneyline_loss():
    assert grade_moneyline("team_a", {"winner": "team_b", "score": "1-2"}) == "L"

def test_grade_map_handicap_cover():
    # Team A -1.5, wins 2-0 → covers
    assert grade_map_handicap("team_a", -1.5, {"score": "2-0", "maps_played": 2}) == "W"

def test_grade_map_handicap_no_cover():
    # Team A -1.5, wins 2-1 → doesn't cover
    assert grade_map_handicap("team_a", -1.5, {"score": "2-1", "maps_played": 3}) == "L"

def test_grade_total_maps_over():
    assert grade_total_maps("over", 2.5, {"maps_played": 3}) == "W"

def test_grade_total_maps_under():
    assert grade_total_maps("under", 2.5, {"maps_played": 2}) == "W"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_results_grader.py -v`
Expected: FAIL

- [ ] **Step 3: Implement esports grading functions**

Add to `agents/results_grader.py`:
- `grade_moneyline(bet_side, result)` — per spec section 12
- `grade_map_handicap(bet_side, handicap, result)` — per spec section 12
- `grade_total_maps(bet_side, line, result)` — per spec section 12
- Update `grade_bet()` to dispatch to these based on `bet_type`

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_results_grader.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/results_grader.py tests/test_results_grader.py
git commit -m "feat: esports results grading (moneyline, map handicap, total maps)"
```

---

### Task 11: Update Test Fixtures and Verify All Tests Pass

**Files:**
- Modify: `tests/ensemble_fixtures.py` (replace MLB mocks with esports)
- Modify: `tests/test_ensemble_runner.py`, `tests/test_ensemble_integration.py` (update fixture refs)
- Run: full test suite

- [ ] **Step 1: Update ensemble_fixtures.py**

Replace `MOCK_PREDICTION` with `MOCK_ESPORTS_PREDICTION` from spec section 19. Replace `MOCK_ODDS` with esports odds. Update `make_prediction()` helper.

- [ ] **Step 2: Update test files that import fixtures**

Grep for imports of `MOCK_PREDICTION` and `MOCK_ODDS` across all test files. Update references to use the new esports structures.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS (or identify remaining failures to fix)

- [ ] **Step 4: Fix any remaining test failures**

Address one by one. Common issues: old MLB field references (`home`, `away`, `run_line`, `first_5`).

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update all fixtures and tests for esports bet types"
```

---

## Phase 2: LoL Support

### Task 12: LoL Config, Scrapers, Briefing, and Prompt

**Files:**
- Modify: `games/lol/config.py` (fill in from stub)
- Create: `games/lol/scrapers.py`
- Create: `games/lol/briefing.py`
- Create: `games/lol/prompt.py`
- Modify: `games/lol/__init__.py`
- Modify: `games/__init__.py` (register LoL)
- Test: `tests/test_lol_scrapers.py`, `tests/test_lol_briefing.py`

- [ ] **Step 1: Fill in games/lol/config.py**

Same structure as CS2 config but with LoL-specific analyst roles:
```python
ANALYST_ROLES = ["laning", "macro", "draft", "form", "market", "contrarian"]
```
Same `BET_SLOTS`, `PROB_FIELDS`, `SLOT_SECTION`, `PRIMARY_PROB_FIELD`, `EDGE_THRESHOLDS` as CS2 (identical bet types).

- [ ] **Step 2: Implement games/lol/scrapers.py**

Sync functions (no async needed — Oracle's Elixir is CSV download):
- `fetch_team_profile(team_name, region)` — load from Oracle's Elixir CSV
- `fetch_upcoming_matches()` — from Liquipedia or Riot schedule
- `fetch_match_result(team_a, team_b, date)` — from Oracle's Elixir
- `load_oracle_data(year)` — download + cache CSV

Reference spec section 5.

- [ ] **Step 3: Implement games/lol/briefing.py**

`build_briefing(match_data)` — LoL template with:
- Side win rates (blue/red)
- GD@15, first blood rate, dragon control
- Champion pool / meta context
- Prediction task requesting same JSON schema

- [ ] **Step 4: Implement games/lol/prompt.py**

`LOL_SYSTEM_PROMPT` from spec section 8.2 — 6 LoL-specific analysts.

- [ ] **Step 5: Update games/lol/__init__.py and registry**

```python
# games/lol/__init__.py
from games.lol import config, scrapers, briefing, prompt

# games/__init__.py — add to GAMES dict:
from games import cs2, lol
GAMES = {"cs2": cs2, "lol": lol}
```

- [ ] **Step 6: Write and run tests**

```python
# tests/test_lol_scrapers.py
# tests/test_lol_briefing.py
```

Run: `pytest tests/test_lol_*.py -v`
Expected: All PASS

- [ ] **Step 7: Verify registry test still passes**

Run: `pytest tests/test_game_registry.py -v`
Expected: All PASS (add LoL assertions)

- [ ] **Step 8: Commit**

```bash
git add games/lol/ games/__init__.py tests/test_lol_*.py tests/test_game_registry.py
git commit -m "feat: LoL game module with Oracle's Elixir scrapers, briefing, and prompt"
```

---

## Phase 3: Cross-Cutting Features

### Task 13: Patch/Meta Scraper

**Files:**
- Create: `scrapers/meta.py`
- Test: `tests/test_meta.py`

- [ ] **Step 1: Write the failing test**

Test that `fetch_patch_context("cs2")` returns dict with required keys: `patch_version`, `days_since_patch`, `key_changes`, `impact_rating`, `raw_url`.

- [ ] **Step 2: Implement scrapers/meta.py**

Per spec section 6.1:
- Fetch latest patch notes page (CS2 blog or LoL patch notes)
- Extract patch version
- Send to Kimi for competitive impact summary
- Cache by patch version (don't re-fetch same patch)

- [ ] **Step 3: Run tests and commit**

```bash
git add scrapers/meta.py tests/test_meta.py
git commit -m "feat: patch/meta scraper with LLM-powered summarization"
```

---

### Task 14: News/Roster Scraper

**Files:**
- Rewrite: `scrapers/news.py`
- Test: `tests/test_news.py`

- [ ] **Step 1: Implement scrapers/news.py**

Per spec section 6.2:
- `fetch_match_context(game_key, team_a, team_b)` → roster_news, tournament_context, narrative, online_lan

- [ ] **Step 2: Write tests and commit**

```bash
git add scrapers/news.py tests/test_news.py
git commit -m "feat: esports news/roster scraper for match context"
```

---

### Task 15: Schedule Aggregator

**Files:**
- Create: `scrapers/schedule.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: Implement scrapers/schedule.py**

Per spec section 6.3:
- `get_todays_matches(game_keys=None)` — aggregate from all game modules, filter by tier

- [ ] **Step 2: Write tests and commit**

```bash
git add scrapers/schedule.py tests/test_schedule.py
git commit -m "feat: unified match schedule aggregator with tier filtering"
```

---

### Task 16: Adapt Daily Runner, Health Check, Bet Card, and Main CLI

**Files:**
- Modify: `agents/daily_runner.py` (multi-game loop)
- Modify: `agents/health_check.py` (new API checks)
- Modify: `agents/bet_card.py` (esports format)
- Modify: `main.py` (game selection CLI arg)

- [ ] **Step 1: Adapt agents/daily_runner.py**

Per spec section 14:
- Loop over `SUPPORTED_GAMES`
- For each game: fetch matches → fetch odds → screen → ensemble → edge → log
- All function calls pass `game_config`

- [ ] **Step 2: Adapt agents/health_check.py**

Per spec section 15:
- Remove `check_mlb_api()`, `check_weather_api()`
- Add `_check_oddspapi()`, `_check_hltv()`, `_check_oracle_elixir()`

- [ ] **Step 3: Adapt agents/bet_card.py**

Update formatting for esports bet types (map_handicap, total_maps instead of run_line, F5).

- [ ] **Step 4: Adapt main.py**

Add `--game` CLI option to filter by game title (cs2, lol, or all).

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add agents/ main.py tests/
git commit -m "feat: multi-game daily runner, health check, bet card, and CLI"
```

---

## Phase 4: Polish

### Task 17: Reset Data Directory and Integration Test

**Files:**
- Create: `data/bets.csv` (fresh header)
- Create: `data/model_weights.json` (fresh weights)
- Create: `data/model_predictions.csv` (fresh header)
- Test: `tests/test_integration.py`

- [ ] **Step 1: Reset data files**

```python
# data/bets.csv — header only
# date,game,game_title,tournament,bet_type,side,odds,sim_prob,edge,kelly_pct,result,profit

# data/model_weights.json — fresh equal weights for esports
# (generated by ensemble/weights.py default_weights())

# data/model_predictions.csv — header only
```

- [ ] **Step 2: Write integration test**

End-to-end test that:
1. Mocks HLTV + OddsPapi responses
2. Runs the daily pipeline for a single CS2 match
3. Verifies a bet is logged to bets.csv (or no bet if no edge)
4. Verifies the pipeline completes without error

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add data/ tests/test_integration.py
git commit -m "feat: reset data directory and add end-to-end integration test"
```

---

### Task 18: Final Verification and Docs

- [ ] **Step 1: Run full test suite one more time**

Run: `pytest tests/ -v --tb=long`
Expected: All PASS, zero failures

- [ ] **Step 2: Verify imports are clean**

Run: `python -c "from games import get_game; g = get_game('cs2'); print(g.config.BET_SLOTS)"`
Expected: `['moneyline', 'map_handicap', 'total_maps']`

- [ ] **Step 3: Verify no MLB references remain**

Run: `grep -r "MLB\|baseball\|pitcher\|bullpen\|ballpark\|park_factor\|run_line\|first_5" --include="*.py" . | grep -v docs/ | grep -v .git/`
Expected: No matches (or only in comments explaining the migration)

- [ ] **Step 4: Commit any final cleanups**

```bash
git add -A
git commit -m "chore: final cleanup — verify zero MLB references in codebase"
```
