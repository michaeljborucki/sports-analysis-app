# Parallel Pipeline + Full Market Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallelize the MiroFish pipeline so a 5-game slate completes in <3 minutes, and expand from 5 to 19 bet types by adding team totals, quarters, first-half spread, and player props.

**Architecture:** Async pipeline with `asyncio` orchestrating 6 parallel phases. Two-tier LLM prediction: existing 6-model ensemble for game-level bets, plus a lightweight 3-model ensemble for player props. Two-phase odds fetching: bulk endpoint for core lines + per-event endpoint for extended markets.

**Tech Stack:** Python 3.11+, asyncio, click, openai, requests, nba_api, pandas

**Spec:** `docs/superpowers/specs/2026-03-22-parallel-pipeline-full-markets-design.md`

---

## File Map

### Modified Files
| File | Responsibility |
|------|---------------|
| `config.py` | New thresholds, endpoints, concurrency settings, slot lists |
| `scrapers/odds.py` | Expand `OddsData`, add `get_event_odds()`, bookmaker preference, event_id extraction |
| `briefing.py` | Add team totals + Q1 lines to briefing text |
| `simulate.py` | Expand system prompt, add `PROP_SYSTEM_PROMPT`, `run_prop_ensemble()`, expand `_average_results()` |
| `edge.py` | 11 new edge check functions, `analyze_prop_edges()`, `optimize_with_alt_lines()` |
| `tracker.py` | Add columns, backward-compatible CSV loading |
| `ensemble/weights.py` | Expand `BET_SLOTS` to `GAME_BET_SLOTS` + `PROP_BET_SLOTS` |
| `ensemble/consensus.py` | Expand `BET_SLOT_FIELDS` for new game-level slots |
| `ensemble/orchestrator.py` | Expand mapping dicts, generalize kill logic, skip derived/prop slots |
| `main.py` | Rewrite `daily()` as async with parallel phases |
| `agents/daily_runner.py` | Call pipeline directly, remove subprocess |
| `agents/results_grader.py` | Fix first_half bug, add quarter/team-total/player-prop grading |

### Modified Files (also)
| File | Responsibility |
|------|---------------|
| `scrapers/scores.py` | Add individual quarter scores (Q1-Q4) to final score output |

### New Files
| File | Responsibility |
|------|---------------|
| `scrapers/player_stats.py` | Fetch player box scores via `BoxScoreTraditionalV2` for prop grading |
| `derive.py` | Derive Q2-Q4 projections from game/half/Q1 predictions |
| `pipeline_utils.py` | Shared helpers: `format_prop_lines()`, `build_game_odds_dict()` |
| `tests/test_derive.py` | Tests for quarter derivation |
| `tests/test_player_stats.py` | Tests for player stats scraper |

---

## Task 1: Config & Slot Expansion

**Files:**
- Modify: `config.py`
- Modify: `ensemble/weights.py`
- Test: `tests/test_config.py`, `tests/test_ensemble_weights.py`

- [ ] **Step 1: Write tests for new config values**

In `tests/test_config.py`, add:

```python
def test_edge_thresholds_has_all_19_slots():
    from config import EDGE_THRESHOLDS
    expected = [
        "moneyline", "spread", "total",
        "first_half_ml", "first_half_total", "first_half_spread",
        "q1_ml", "q1_spread", "q1_total",
        "q2_total", "q3_total", "q4_total",
        "team_total_home", "team_total_away",
        "player_points", "player_rebounds", "player_assists",
        "player_threes", "player_pra",
    ]
    for slot in expected:
        assert slot in EDGE_THRESHOLDS, f"Missing threshold for {slot}"


def test_odds_event_markets_string():
    from config import ODDS_EVENT_MARKETS
    assert "player_points" in ODDS_EVENT_MARKETS
    assert "team_totals" in ODDS_EVENT_MARKETS
    assert "totals_q2" in ODDS_EVENT_MARKETS


def test_prop_ensemble_models():
    from config import PROP_ENSEMBLE_MODELS
    assert len(PROP_ENSEMBLE_MODELS) == 3
    assert "kimi" in PROP_ENSEMBLE_MODELS


def test_concurrency_settings():
    from config import MAX_CONCURRENT_GAMES, MAX_CONCURRENT_API_CALLS
    assert MAX_CONCURRENT_GAMES >= 1
    assert MAX_CONCURRENT_API_CALLS >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v -k "edge_thresholds_has_all or odds_event or prop_ensemble or concurrency"`
Expected: FAIL — new config values don't exist yet

- [ ] **Step 3: Add new config values to config.py**

Add after the existing `EDGE_THRESHOLDS` dict in `config.py`:

```python
# Expanded edge thresholds (replace existing EDGE_THRESHOLDS)
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "spread": 0.06,
    "total": 0.05,
    "first_half_ml": 0.05,
    "first_half_total": 0.05,
    "first_half_spread": 0.05,
    "q1_ml": 0.04,
    "q1_spread": 0.05,
    "q1_total": 0.04,
    "q2_total": 0.05,
    "q3_total": 0.05,
    "q4_total": 0.05,
    "team_total_home": 0.04,
    "team_total_away": 0.04,
    "player_points": 0.04,
    "player_rebounds": 0.03,
    "player_assists": 0.03,
    "player_threes": 0.05,
    "player_pra": 0.03,
}

# Odds API — per-event endpoint
ODDS_EVENT_ENDPOINT = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/events"
ODDS_EVENT_MARKETS = (
    "h2h_h1,spreads_h1,totals_h1,"
    "h2h_h2,spreads_h2,totals_h2,"
    "h2h_q1,spreads_q1,totals_q1,"
    "totals_q2,totals_q3,totals_q4,"
    "team_totals,"
    "alternate_spreads,alternate_totals,"
    "player_points,player_rebounds,player_assists,"
    "player_threes,player_points_rebounds_assists"
)

PROP_ENSEMBLE_MODELS = ["kimi", "gpt4o", "deepseek"]
MAX_CONCURRENT_GAMES = 6
MAX_CONCURRENT_API_CALLS = 5
Q3_SCORING_SHARE = 0.52
Q4_SCORING_SHARE = 0.48

# Slot lists
GAME_BET_SLOTS = [
    "moneyline", "spread", "total",
    "first_half_ml", "first_half_total", "first_half_spread",
    "q1_ml", "q1_spread", "q1_total",
    "q2_total", "q3_total", "q4_total",
    "team_total_home", "team_total_away",
]
DERIVED_SLOTS = {"q2_total", "q3_total", "q4_total"}
PROP_BET_SLOTS = [
    "player_points", "player_rebounds", "player_assists",
    "player_threes", "player_pra",
]
```

- [ ] **Step 4: Update ensemble/weights.py to use new slot lists**

Replace `BET_SLOTS` line with:
```python
from config import GAME_BET_SLOTS, PROP_BET_SLOTS
BET_SLOTS = GAME_BET_SLOTS + PROP_BET_SLOTS
```

Update `default_weights()` accordingly.

**CRITICAL: Update existing tests that will break:**

In `tests/test_config.py`, find and update `test_edge_thresholds_has_all_bet_types` — it asserts exact set equality with the old 5 slots. Replace the `expected` set with the new 19 slots.

In `tests/test_ensemble_weights.py`, update:
- `test_bet_slots`: Change `assert BET_SLOTS == [...]` to check for 19 items
- `test_default_weights`: Change `assert len(slots) == 5` to `assert len(slots) == 19`

- [ ] **Step 5: Run all tests to verify pass**

Run: `python -m pytest tests/test_config.py tests/test_ensemble_weights.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add config.py ensemble/weights.py tests/test_config.py tests/test_ensemble_weights.py
git commit -m "feat: expand config to 19 bet slots with new markets and concurrency settings"
```

---

## Task 2: Expanded OddsData + Two-Phase Odds Fetch

**Files:**
- Modify: `scrapers/odds.py`
- Test: `tests/test_odds.py`

- [ ] **Step 1: Write tests for expanded OddsData**

Add to `tests/test_odds.py`:

```python
def test_odds_data_has_event_id():
    od = OddsData(home="BOS", away="LAL", event_id="abc123", commence_time="2026-03-22T00:30:00Z")
    assert od.event_id == "abc123"

def test_odds_data_has_quarter_fields():
    od = OddsData(home="BOS", away="LAL", event_id="abc", commence_time="t")
    assert od.q1_moneyline == {}
    assert od.q1_total == {}
    assert od.team_totals == {}
    assert od.player_props == {}
    assert od.alt_spreads == []

def test_odds_data_has_h2_fields():
    od = OddsData(home="BOS", away="LAL", event_id="abc", commence_time="t")
    assert od.h2_moneyline == {}
    assert od.h2_spread == {}
    assert od.h2_total == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odds.py -v -k "event_id or quarter or h2_fields"`
Expected: FAIL — OddsData doesn't have these fields yet

- [ ] **Step 3: Expand OddsData dataclass**

In `scrapers/odds.py`, add `event_id` AFTER `commence_time` (not before it) with default `""` so all existing callers (`OddsData(home=X, away=Y, commence_time=Z)`) continue to work:

```python
@dataclass
class OddsData:
    home: str
    away: str
    commence_time: str
    event_id: str = ""  # NEW — after commence_time to preserve backward compat
    # ... all new fields with field(default_factory=...) ...
```

Add all new fields per the spec (Section 4.3): h2_*, q1-q4_*, team_totals, alt_spreads, alt_totals, player_props.

- [ ] **Step 4: Update get_nba_odds() to extract event_id and implement bookmaker preference**

In the bulk fetch, extract `event["id"]` and store in `OddsData.event_id`. Replace the `break`-after-first-bookmaker with bookmaker preference ordering:

```python
BOOKMAKER_PREFERENCE = ["draftkings", "fanduel", "betmgm"]

def _pick_bookmaker(bookmakers: list) -> dict | None:
    by_key = {bk["key"]: bk for bk in bookmakers}
    for pref in BOOKMAKER_PREFERENCE:
        if pref in by_key:
            return by_key[pref]
    return bookmakers[0] if bookmakers else None
```

- [ ] **Step 5: Add get_event_odds() function**

```python
def get_event_odds(event_id: str) -> dict:
    """Fetch extended markets for a single event via per-event endpoint."""
    from config import ODDS_EVENT_ENDPOINT, ODDS_EVENT_MARKETS
    url = f"{ODDS_EVENT_ENDPOINT}/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": ODDS_EVENT_MARKETS,
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()
```

Add a `merge_event_odds(odds_data: OddsData, event_response: dict)` function that parses all extended markets from the per-event response and merges them into the existing `OddsData` object (H1/H2, Q1-Q4, team totals, alternates, player props).

- [ ] **Step 6: Write test for get_event_odds with mock**

Mock the per-event endpoint response with sample Q1, team totals, and player prop data. Verify `merge_event_odds` correctly populates the OddsData fields.

- [ ] **Step 7: Run all odds tests**

Run: `python -m pytest tests/test_odds.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: two-phase odds fetch with event endpoint, bookmaker preference, expanded OddsData"
```

---

## Task 3: Quarter Derivation Module

**Files:**
- Create: `derive.py`
- Create: `tests/test_derive.py`

- [ ] **Step 1: Write tests for quarter derivation**

```python
# tests/test_derive.py
from derive import derive_quarter_projections

def test_q2_total_derived_from_h1_minus_q1():
    preds = {
        "total": {"projected_total": 220.0},
        "first_half": {"h1_projected_total": 112.0},
        "q1": {"q1_projected_total": 57.0},
    }
    derived = derive_quarter_projections(preds)
    assert derived["q2_projected_total"] == 55.0  # 112 - 57

def test_h2_total_derived_from_game_minus_h1():
    preds = {
        "total": {"projected_total": 220.0},
        "first_half": {"h1_projected_total": 112.0},
        "q1": {"q1_projected_total": 57.0},
    }
    derived = derive_quarter_projections(preds)
    assert derived["h2_projected_total"] == 108.0  # 220 - 112

def test_q3_q4_split():
    preds = {
        "total": {"projected_total": 220.0},
        "first_half": {"h1_projected_total": 112.0},
        "q1": {"q1_projected_total": 57.0},
    }
    derived = derive_quarter_projections(preds)
    # H2 = 108. Q3 = 108 * 0.52 = 56.16, Q4 = 108 * 0.48 = 51.84
    assert abs(derived["q3_projected_total"] - 56.16) < 0.01
    assert abs(derived["q4_projected_total"] - 51.84) < 0.01

def test_missing_predictions_returns_empty():
    derived = derive_quarter_projections({})
    assert derived == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_derive.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement derive.py**

```python
"""Derive Q2-Q4 projections from game/half/Q1 predictions."""
from config import Q3_SCORING_SHARE, Q4_SCORING_SHARE


def derive_quarter_projections(predictions: dict) -> dict:
    """Derive Q2-Q4 projected totals from game, H1, and Q1 predictions.

    Returns dict with q2_projected_total, q3_projected_total, q4_projected_total,
    h2_projected_total. Empty dict if inputs are insufficient.
    """
    total_pred = predictions.get("total", {})
    h1_pred = predictions.get("first_half", {})
    q1_pred = predictions.get("q1", {})

    game_total = total_pred.get("projected_total")
    h1_total = h1_pred.get("h1_projected_total")
    q1_total = q1_pred.get("q1_projected_total")

    if game_total is None or h1_total is None or q1_total is None:
        return {}

    h2_total = game_total - h1_total
    q2_total = h1_total - q1_total
    q3_total = round(h2_total * Q3_SCORING_SHARE, 2)
    q4_total = round(h2_total * Q4_SCORING_SHARE, 2)

    return {
        "h2_projected_total": round(h2_total, 2),
        "q2_projected_total": round(q2_total, 2),
        "q3_projected_total": q3_total,
        "q4_projected_total": q4_total,
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_derive.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add derive.py tests/test_derive.py
git commit -m "feat: add quarter derivation module for Q2-Q4 projections"
```

---

## Task 4: Expanded Edge Detection

**Files:**
- Modify: `edge.py`
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write tests for new edge check functions**

Add to `tests/test_edge.py`:

```python
from edge import (
    check_first_half_spread_edge, check_q1_ml_edge, check_q1_spread_edge,
    check_q1_total_edge, check_quarter_total_edge, check_team_total_edge,
    check_player_prop_edge, analyze_prop_edges, optimize_with_alt_lines,
)

EXTENDED_ODDS = {
    **MOCK_ODDS,
    "h1_spread": {"home": -2.5, "home_odds": -110, "away": 2.5, "away_odds": -110},
    "q1_moneyline": {"home": -120, "away": 100},
    "q1_spread": {"home": -1.5, "home_odds": -110, "away": 1.5, "away_odds": -110},
    "q1_total": {"line": 55.5, "over_odds": -110, "under_odds": -110},
    "q2_total": {"line": 54.5, "over_odds": -110, "under_odds": -110},
    "team_totals": {
        "home": {"line": 112.5, "over_odds": -110, "under_odds": -110},
        "away": {"line": 106.5, "over_odds": -110, "under_odds": -110},
    },
    "player_props": {
        "Jayson Tatum": {
            "points": {"line": 26.5, "over_odds": -115, "under_odds": -105},
            "rebounds": {"line": 8.5, "over_odds": -110, "under_odds": -110},
        },
    },
}

def test_check_first_half_spread_edge_returns_correct_type():
    sim = {"predictions": {"first_half": {"h1_favorite_cover_prob": 0.65, "confidence": "high"}}}
    result = check_first_half_spread_edge(sim, EXTENDED_ODDS)
    if result:
        assert result["bet_type"] == "first_half_spread"

def test_check_q1_ml_edge_returns_correct_type():
    sim = {"predictions": {"q1": {"q1_home_win_prob": 0.65, "q1_away_win_prob": 0.35}}}
    result = check_q1_ml_edge(sim, EXTENDED_ODDS)
    if result:
        assert result["bet_type"] == "q1_ml"

def test_check_team_total_edge_home():
    sim = {"predictions": {"team_totals": {"home_projected": 118.0}}}
    result = check_team_total_edge(sim, EXTENDED_ODDS, "home")
    if result:
        assert result["bet_type"] == "team_total_home"

def test_check_player_prop_edge_returns_list():
    prop_preds = {"player_props": {
        "Jayson Tatum": {"points": {"over_prob": 0.65, "projected": 29.0}},
    }}
    result = check_player_prop_edge(prop_preds, EXTENDED_ODDS, "points")
    assert isinstance(result, list)

def test_analyze_prop_edges_combines_all_props():
    prop_preds = {"player_props": {
        "Jayson Tatum": {
            "points": {"over_prob": 0.65, "projected": 29.0},
            "rebounds": {"over_prob": 0.62, "projected": 10.0},
        },
    }}
    bets = analyze_prop_edges(prop_preds, EXTENDED_ODDS)
    assert isinstance(bets, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_edge.py -v -k "first_half_spread or q1_ml or team_total or player_prop or prop_edges"`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement new edge check functions**

Add to `edge.py`:
- `check_first_half_spread_edge(sim, odds)` — mirrors `check_spread_edge` with `h1_spread` odds and `h1_favorite_cover_prob`
- `check_q1_ml_edge(sim, odds)` — mirrors `check_moneyline_edge` with `q1_moneyline` odds and `q1_home_win_prob`/`q1_away_win_prob`
- `check_q1_spread_edge(sim, odds)` — mirrors `check_spread_edge` with `q1_spread` odds
- `check_q1_total_edge(sim, odds)` — mirrors `check_total_edge` with `q1_total` odds and `q1_projected_total`
- `check_quarter_total_edge(sim, odds, quarter)` — for Q2-Q4 using derived projected total vs `q{N}_total` odds
- `check_team_total_edge(sim, odds, side)` — over/under on team-specific total
- `check_player_prop_edge(prop_preds, odds, prop_type)` — iterates players, returns list of bets
- `analyze_prop_edges(prop_preds, odds)` — aggregates all prop types
- `optimize_with_alt_lines(bet, alt_lines)` — finds best Kelly-optimal alt line

Update `analyze_all_edges()` to include all 14 game-level checkers (existing 5 + new 9).

- [ ] **Step 4: Run all edge tests**

Run: `python -m pytest tests/test_edge.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: expand edge detection to 19 bet types with props and quarters"
```

---

## Task 5: Ensemble Internals Expansion

**Files:**
- Modify: `ensemble/consensus.py`
- Modify: `ensemble/orchestrator.py`
- Test: `tests/test_ensemble_consensus.py`, `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Write tests for expanded BET_SLOT_FIELDS**

Add to `tests/test_ensemble_consensus.py`:

```python
def test_bet_slot_fields_has_new_slots():
    from ensemble.consensus import BET_SLOT_FIELDS
    new_slots = ["first_half_spread", "q1_ml", "q1_spread", "q1_total",
                 "team_total_home", "team_total_away"]
    for slot in new_slots:
        assert slot in BET_SLOT_FIELDS, f"Missing BET_SLOT_FIELDS entry for {slot}"

def test_extract_vote_q1_ml():
    from ensemble.consensus import extract_vote
    prediction = {"predictions": {"q1": {"q1_ml_value": "home"}}}
    vote = extract_vote(prediction, "q1_ml", {})
    assert vote == "home"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ensemble_consensus.py -v -k "new_slots or q1_ml"`
Expected: FAIL

- [ ] **Step 3: Expand BET_SLOT_FIELDS in consensus.py**

Add entries per spec Section 7.3. Add spread normalization for `first_half_spread` and `q1_spread` in `extract_vote()` (same pattern as existing `spread` normalization using odds to determine home/away favorite).

**CRITICAL: Update existing test that will break:**

In `tests/test_ensemble_consensus.py`, find `test_bet_slot_fields_has_five_slots` and change `assert len(BET_SLOT_FIELDS) == 5` to `assert len(BET_SLOT_FIELDS) == 11` (5 existing + 6 new game-level slots; Q2-Q4 derived slots are excluded).

- [ ] **Step 4: Update orchestrator.py mapping dicts and iteration**

Expand `PROB_FIELDS`, `SLOT_SECTION`, `PRIMARY_PROB_FIELD` per spec Section 7.2.

Replace hardcoded kill logic in `build_ensemble_result()` with generalized approach per spec Section 7.4.

**CRITICAL: Change consensus/reclassify iteration to use GAME_BET_SLOTS excluding DERIVED_SLOTS:**

In `orchestrator.py`, replace:
```python
# OLD: iterates ALL BET_SLOTS (19 including props and derived)
from ensemble.weights import BET_SLOTS
for slot in BET_SLOTS:
```

With:
```python
from config import GAME_BET_SLOTS, DERIVED_SLOTS

# Slots that go through LLM consensus (exclude derived and props)
CONSENSUS_SLOTS = [s for s in GAME_BET_SLOTS if s not in DERIVED_SLOTS]
```

Update `classify_consensus()`, `reclassify_consensus()`, `_log_all_predictions()`, and `build_ensemble_result()` to iterate `CONSENSUS_SLOTS` instead of `BET_SLOTS`. The logging function should still iterate all `GAME_BET_SLOTS` (including derived) for completeness, but consensus functions must skip derived slots since there are no LLM votes for them.

- [ ] **Step 5: Run all ensemble tests**

Run: `python -m pytest tests/test_ensemble_consensus.py tests/test_ensemble_orchestrator.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add ensemble/consensus.py ensemble/orchestrator.py tests/test_ensemble_consensus.py tests/test_ensemble_orchestrator.py
git commit -m "feat: expand ensemble internals for 14 game-level bet slots"
```

---

## Task 6: Expanded LLM Prompts + Player Prop Ensemble

**Files:**
- Modify: `simulate.py`
- Modify: `briefing.py`
- Test: `tests/test_simulate.py`, `tests/test_briefing.py`

- [ ] **Step 1: Write tests for expanded prompt and prop ensemble**

Add to `tests/test_simulate.py`:

```python
def test_nba_system_prompt_includes_q1():
    from simulate import NBA_SYSTEM_PROMPT
    assert "q1" in NBA_SYSTEM_PROMPT.lower()

def test_nba_system_prompt_includes_team_totals():
    from simulate import NBA_SYSTEM_PROMPT
    assert "team_totals" in NBA_SYSTEM_PROMPT

def test_prop_system_prompt_exists():
    from simulate import PROP_SYSTEM_PROMPT
    assert "player_props" in PROP_SYSTEM_PROMPT

def test_average_results_covers_q1():
    from simulate import _average_results
    results = [
        {"predictions": {"q1": {"q1_home_win_prob": 0.55, "q1_projected_total": 56.0}}},
        {"predictions": {"q1": {"q1_home_win_prob": 0.60, "q1_projected_total": 58.0}}},
    ]
    avg = _average_results(results)
    assert abs(avg["predictions"]["q1"]["q1_home_win_prob"] - 0.575) < 0.01
```

Add to `tests/test_briefing.py`:

```python
def test_briefing_includes_team_totals():
    from briefing import build_briefing
    game_data = _make_game_data()  # use existing fixture
    game_data["odds"]["team_totals"] = {
        "home": {"line": 112.5, "over_odds": -110, "under_odds": -110},
        "away": {"line": 106.5, "over_odds": -110, "under_odds": -110},
    }
    brief = build_briefing(game_data)
    assert "TEAM TOTALS" in brief
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulate.py tests/test_briefing.py -v -k "q1 or team_totals or prop_system"`
Expected: FAIL

- [ ] **Step 3: Expand NBA_SYSTEM_PROMPT in simulate.py**

Add the new JSON sections (second_half, q1, team_totals, first_half expanded with h1_favorite_cover_prob and h1_spread_value) to the prompt per spec Section 5.1. Add Q1 lines and team totals to the prediction task instructions.

- [ ] **Step 4: Add PROP_SYSTEM_PROMPT and run_prop_ensemble()**

Add the player prop system prompt per spec Section 5.2.

```python
def run_prop_ensemble(briefing: str, prop_lines: str) -> dict | None:
    """Run lightweight 3-model ensemble for player prop predictions."""
    from config import PROP_ENSEMBLE_MODELS, OPENROUTER_API_KEY, OPENROUTER_BASE_URL
    from ensemble.models import MODEL_REGISTRY
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = openai.OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)
    user_msg = f"{briefing}\n\n== PLAYER PROP LINES ==\n{prop_lines}"
    results = []

    def _call(model_key):
        spec = MODEL_REGISTRY[model_key]
        try:
            resp = client.chat.completions.create(
                model=spec["id"],
                messages=[
                    {"role": "system", "content": PROP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            return parse_simulation_result(resp.choices[0].message.content)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_call, mk): mk for mk in PROP_ENSEMBLE_MODELS}
        for f in as_completed(futures):
            r = f.result(timeout=60)
            if r:
                results.append(r)

    if not results:
        return None
    return _average_prop_results(results)
```

- [ ] **Step 5: Expand _average_results() prob_fields and add _average_prop_results()**

Add `second_half`, `q1`, `team_totals` sections to `_average_results()` per spec Section 7.6.

Add new function for prop results averaging:

```python
def _average_prop_results(results: list[dict]) -> dict:
    """Average player prop probability estimates across multiple model runs."""
    if len(results) == 1:
        return results[0]
    base = results[0].copy()
    players = base.get("player_props", {})
    prop_types = ["points", "rebounds", "assists", "threes", "pra"]
    for player in players:
        for prop in prop_types:
            values = []
            projected = []
            for r in results:
                pp = r.get("player_props", {}).get(player, {}).get(prop, {})
                if "over_prob" in pp:
                    values.append(float(pp["over_prob"]))
                if "projected" in pp:
                    projected.append(float(pp["projected"]))
            if values:
                players[player][prop]["over_prob"] = round(sum(values) / len(values), 4)
            if projected:
                players[player][prop]["projected"] = round(sum(projected) / len(projected), 1)
    base["player_props"] = players
    return base
```

- [ ] **Step 6: Expand build_briefing() in briefing.py**

Add TEAM TOTALS and QUARTER 1 LINES sections. Add H1 spread to the existing BETTING LINES section. Update the PREDICTION TASK section to mention Q1 and team totals.

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/test_simulate.py tests/test_briefing.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add simulate.py briefing.py tests/test_simulate.py tests/test_briefing.py
git commit -m "feat: expand LLM prompts for Q1/team-totals/H1-spread, add player prop ensemble"
```

---

## Task 7: Tracker + Results Grader Expansion

**Files:**
- Modify: `tracker.py`
- Modify: `agents/results_grader.py`
- Create: `scrapers/player_stats.py`
- Test: `tests/test_tracker.py`, `tests/test_results_grader.py`, `tests/test_player_stats.py`

- [ ] **Step 1: Write tests for backward-compatible tracker**

Add to `tests/test_tracker.py`:

```python
import tempfile, os
import pandas as pd

def test_load_bets_backward_compat(tmp_path):
    """Existing CSV without new columns still loads correctly."""
    csv = tmp_path / "bets.csv"
    old_cols = ["date", "game", "bet_type", "side", "odds", "sim_prob",
                "edge", "kelly_pct", "result", "profit"]
    pd.DataFrame(columns=old_cols).to_csv(csv, index=False)
    from tracker import load_bets, COLUMNS
    df = load_bets(str(csv))
    for col in COLUMNS:
        assert col in df.columns

def test_log_bet_includes_market_and_player(tmp_path):
    csv = tmp_path / "bets.csv"
    from tracker import log_bet, load_bets
    bet = {"date": "2026-03-22", "game": "BOS@NYK", "bet_type": "player_points",
           "side": "over 26.5", "odds": -115, "sim_prob": 0.58,
           "edge": 0.05, "kelly_pct": 0.02, "market": "prop", "player": "Jayson Tatum"}
    log_bet(bet, str(csv))
    df = load_bets(str(csv))
    assert df.iloc[0]["market"] == "prop"
    assert df.iloc[0]["player"] == "Jayson Tatum"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tracker.py -v -k "backward_compat or market_and_player"`
Expected: FAIL

- [ ] **Step 3: Update tracker.py**

Add `"confidence"`, `"market"`, `"player"` to `COLUMNS`. Update `load_bets()` to add missing columns with empty string defaults per spec Section 8.1.

- [ ] **Step 4: Update scrapers/scores.py to return individual quarter scores**

The current `get_final_scores()` only returns `home_score_h1` and `away_score_h1`. It needs to also return `home_score_q1` through `home_score_q4` (and away) for quarter bet grading. The `ScoreboardV2` `LineScore` result already contains `PTS_QTR1`-`PTS_QTR4` fields. Add them to the returned dict:

```python
# In get_final_scores(), for each team line:
for q in range(1, 5):
    score_dict[f"home_score_q{q}"] = int(home_line.get(f"PTS_QTR{q}", 0) or 0)
    score_dict[f"away_score_q{q}"] = int(away_line.get(f"PTS_QTR{q}", 0) or 0)
```

- [ ] **Step 5: Fix results_grader.py first_half bug and add new bet type grading**

Replace the `elif bet_type == "first_half":` block (line 62) with separate handlers:

```python
elif bet_type == "first_half_ml":
    h1_home = score["home_score_h1"]
    h1_away = score["away_score_h1"]
    if "home" in side:
        return "W" if h1_home > h1_away else ("P" if h1_home == h1_away else "L")
    else:
        return "W" if h1_away > h1_home else ("P" if h1_away == h1_home else "L")

elif bet_type == "first_half_total":
    h1_total = score["total_points_h1"]
    tokens = side.split()
    direction, line = tokens[0], float(tokens[-1])
    if direction == "over":
        return "W" if h1_total > line else ("P" if h1_total == line else "L")
    else:
        return "W" if h1_total < line else ("P" if h1_total == line else "L")

elif bet_type == "first_half_spread":
    # Same spread logic as full game but using H1 scores
    ...

elif bet_type.startswith("q") and bet_type.endswith(("_ml", "_spread", "_total")):
    quarter = int(bet_type[1])  # e.g., "q1_total" -> 1
    q_home = score.get(f"home_score_q{quarter}", 0)
    q_away = score.get(f"away_score_q{quarter}", 0)
    q_total = q_home + q_away
    # Route to ML, spread, or total grading using quarter scores
    ...

elif bet_type.startswith("team_total_"):
    team_side = bet_type.split("_")[-1]  # "home" or "away"
    team_score = score[f"{team_side}_score"]
    tokens = side.split()
    direction, line = tokens[0], float(tokens[-1])
    if direction == "over":
        return "W" if team_score > line else ("P" if team_score == line else "L")
    else:
        return "W" if team_score < line else ("P" if team_score == line else "L")

elif bet_type.startswith("player_"):
    # Player prop grading delegated to grade_player_props()
    return grade_player_prop(bet_row, score)
```

- [ ] **Step 5: Create scrapers/player_stats.py**

```python
"""Fetch player box scores for prop grading."""
import logging
from nba_api.stats.endpoints import BoxScoreTraditionalV2

logger = logging.getLogger("mirofish.scrapers.player_stats")

def get_player_box_scores(game_id: str) -> list[dict]:
    """Fetch player stats for a completed game."""
    try:
        box = BoxScoreTraditionalV2(game_id=game_id)
        df = box.get_data_frames()[0]
        players = []
        for _, row in df.iterrows():
            players.append({
                "player": row.get("PLAYER_NAME", ""),
                "team": row.get("TEAM_ABBREVIATION", ""),
                "minutes": row.get("MIN", "0"),
                "points": int(row.get("PTS", 0) or 0),
                "rebounds": int(row.get("REB", 0) or 0),
                "assists": int(row.get("AST", 0) or 0),
                "threes": int(row.get("FG3M", 0) or 0),
            })
        return players
    except Exception as e:
        logger.error("Failed to fetch box scores for %s: %s", game_id, e)
        return []
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/test_tracker.py tests/test_results_grader.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add tracker.py agents/results_grader.py scrapers/player_stats.py tests/test_tracker.py tests/test_results_grader.py tests/test_player_stats.py
git commit -m "feat: expand tracker with prop columns, fix grader bug, add player stats scraper"
```

---

## Task 8: Async Pipeline Orchestration

**Files:**
- Modify: `main.py`
- Modify: `agents/daily_runner.py`
- Test: `tests/test_main.py`

This is the final integration task. It rewrites the sequential `daily()` into a parallel async pipeline.

- [ ] **Step 1: Write integration test for async pipeline structure**

Add to `tests/test_main.py`:

```python
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

def test_daily_is_async():
    """Verify daily command uses async orchestration."""
    from main import run_daily_pipeline
    assert asyncio.iscoroutinefunction(run_daily_pipeline)
```

- [ ] **Step 2: Create pipeline_utils.py with shared helpers**

Create `pipeline_utils.py`:

```python
"""Shared pipeline helpers."""
from scrapers.odds import OddsData

def format_prop_lines(odds: OddsData) -> str:
    """Format player prop lines for the Tier 2 LLM prompt."""
    lines = []
    for player, props in odds.player_props.items():
        parts = []
        for prop_type, data in props.items():
            parts.append(f"  {prop_type}: {data.get('line', '?')} "
                        f"(O {data.get('over_odds', '?')} / U {data.get('under_odds', '?')})")
        lines.append(f"{player}:\n" + "\n".join(parts))
    return "\n".join(lines) if lines else "No player props available"

def build_game_odds_dict(odds: OddsData) -> dict:
    """Build the full odds dict from OddsData for game_data['odds'].
    Includes all markets: core, H1/H2, Q1-Q4, team totals, alternates, player props."""
    return {
        "moneyline": odds.moneyline,
        "spread": odds.spread,
        "total": odds.total,
        "h1_moneyline": odds.h1_moneyline,
        "h1_total": odds.h1_total,
        "h1_spread": odds.h1_spread,
        "h2_moneyline": odds.h2_moneyline,
        "h2_total": odds.h2_total,
        "h2_spread": odds.h2_spread,
        "q1_moneyline": odds.q1_moneyline,
        "q1_spread": odds.q1_spread,
        "q1_total": odds.q1_total,
        "q2_total": odds.q2_total,
        "q3_total": odds.q3_total,
        "q4_total": odds.q4_total,
        "team_totals": odds.team_totals,
        "alt_spreads": odds.alt_spreads,
        "alt_totals": odds.alt_totals,
        "player_props": odds.player_props,
        "implied_probs": odds.implied_probs,
    }
```

- [ ] **Step 3: Extract pipeline logic into run_daily_pipeline() async function**

Create `async def run_daily_pipeline(game_date: str) -> int` in `main.py` that returns the number of bets logged. The click command calls `asyncio.run(run_daily_pipeline(game_date))`.

Implement the 6-phase parallel architecture:

```python
async def run_daily_pipeline(game_date: str) -> int:
    import asyncio
    from config import MAX_CONCURRENT_GAMES, MAX_CONCURRENT_API_CALLS

    nba_sem = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS)
    odds_sem = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS)

    # Phase 1: Parallel data gathering
    games, odds_list, all_injuries = await asyncio.gather(
        asyncio.to_thread(get_todays_games, game_date),
        asyncio.to_thread(get_nba_odds),
        asyncio.to_thread(get_injuries),
    )
    # ... build odds_by_teams, injuries_by_team ...

    # Phase 2: Extended odds (parallel per game)
    async def fetch_extended(odds_data):
        async with odds_sem:
            event_resp = await asyncio.to_thread(get_event_odds, odds_data.event_id)
            merge_event_odds(odds_data, event_resp)
    await asyncio.gather(*[fetch_extended(o) for o in odds_list if o.event_id])

    # Phase 3: Per-game enrichment (parallel, semaphore per individual call)
    async def nba_call(fn, *args):
        """Wrap each NBA API call with the semaphore."""
        async with nba_sem:
            return await asyncio.to_thread(fn, *args)

    async def enrich_game(game):
        away_profile, home_profile, away_rest, home_rest, matchup = await asyncio.gather(
            nba_call(get_team_profile, game["away_team"]),
            nba_call(get_team_profile, game["home_team"]),
            nba_call(get_rest_data, game["away_team"], game_date),
            nba_call(get_rest_data, game["home_team"], game_date),
            nba_call(get_matchup_data, game["home_team"], game["away_team"]),
        )
        return {**game, "away_stats": away_profile, "home_stats": home_profile,
                "away_rest": away_rest, "home_rest": home_rest, "matchup": matchup}
    enriched = await asyncio.gather(*[enrich_game(g) for g in games])

    # Phase 4: Screen (parallel)
    async def screen_game(game_data, odds):
        brief = build_briefing(game_data)
        screen = await asyncio.to_thread(run_plan_b, brief)
        if not screen:
            return None
        edges = analyze_all_edges(screen, game_data["odds"])
        max_edge = max((e["edge"] for e in edges), default=0)
        if max_edge >= SCREEN_EDGE_THRESHOLD:
            return (game_data, brief, odds)
        return None
    # ... gather screens, filter flagged ...

    # Phase 5 + 6: Full ensemble + props (parallel per game)
    async def simulate_game(game_data, brief, odds):
        result = await asyncio.to_thread(run_mirofish, brief, 3, game_data["odds"])
        bets = analyze_all_edges(result, game_data["odds"]) if result else []
        # Derive Q2-Q4 and check those edges too
        if result:
            derived = derive_quarter_projections(result.get("predictions", {}))
            # ... check Q2-Q4 edges against odds ...

        # Props (parallel with game ensemble for next game)
        prop_bets = []
        if odds.player_props:
            from pipeline_utils import format_prop_lines
            prop_result = await asyncio.to_thread(run_prop_ensemble, brief, format_prop_lines(odds))
            if prop_result:
                prop_bets = analyze_prop_edges(prop_result, game_data["odds"])

        # Set market/player fields on all bets before returning
        for bet in bets:
            bet["market"] = "game"
            bet["player"] = ""
        for bet in prop_bets:
            bet["market"] = "prop"
            # bet["player"] is set by check_player_prop_edge
        return bets + prop_bets
    # ... gather all bets, log them ...
```

- [ ] **Step 3: Update daily_runner.py to call pipeline directly**

Replace `subprocess.run()` with direct async call:

```python
def run_pipeline(game_date: str, max_retries: int = 2) -> bool:
    import asyncio
    from main import run_daily_pipeline
    for attempt in range(max_retries + 1):
        try:
            total_bets = asyncio.run(run_daily_pipeline(game_date))
            return True
        except Exception as e:
            click.echo(f"  Pipeline error: {e}")
            if attempt < max_retries:
                time.sleep(10)
    return False
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 5: Manual smoke test**

Run: `python main.py health` to verify APIs work.
Run: `python main.py daily --date 2026-03-22` to verify the async pipeline runs end-to-end.
Verify it completes in <3 minutes and produces output for all phases.

- [ ] **Step 6: Note: `game` CLI command is out of scope**

The `game` command in `main.py` (lines 163-241) runs the same sequential flow for a single game. It is NOT converted to async in this task — it will still work with existing bet types only. A follow-up task can update it to use `run_daily_pipeline` internally with a single-game filter.

- [ ] **Step 7: Commit**

```bash
git add main.py agents/daily_runner.py pipeline_utils.py tests/test_main.py
git commit -m "feat: rewrite pipeline as async with 6 parallel phases"
```

---

## Task 9: End-to-End Validation

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS, no regressions

- [ ] **Step 2: Run daily pipeline**

Run: `python -m agents.daily_runner --grade-yesterday`
Verify: Completes in <3 minutes. Odds fetch shows extended markets. Games process in parallel.

- [ ] **Step 3: Verify bet card includes new bet types**

Run: `python main.py card`
Verify: Any new bets from the run appear correctly formatted.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final validation pass for parallel pipeline + full markets"
```

---

## Task Dependencies

```
Task 1 (Config) + Task 5 (Ensemble internals) ──→ Tasks 2, 3, 4, 6, 7 (parallel)
                                                ──→ Task 8 (Async Pipeline)
                                                    ──→ Task 9 (Validation)
```

**CRITICAL ordering note:** Task 1 expands `BET_SLOTS` from 5 to 19. The orchestrator iterates `BET_SLOTS` and calls `extract_vote()` which does an unguarded `BET_SLOT_FIELDS[bet_slot]` lookup. If `BET_SLOTS` has 19 entries but `BET_SLOT_FIELDS` still has 5 (Task 5 not yet done), any code path touching the ensemble will `KeyError`. Therefore **Tasks 1 and 5 must both complete before any other task runs.**

**Parallelizable groups:**
- **Group 0 (sequential, must complete first):** Task 1 then Task 5
- **Group A (independent, run in parallel after Group 0):** Tasks 2, 3, 4, 6, 7
- **Group B (sequential, depends on all of Group A):** Task 8
- **Group C (sequential, depends on Task 8):** Task 9
