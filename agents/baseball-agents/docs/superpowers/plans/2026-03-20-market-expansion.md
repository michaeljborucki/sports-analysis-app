# Market Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand from 5 betting markets to 22 by adding 7 game-level markets (Phase 1) and 10 player prop markets via Monte Carlo simulation (Phase 2).

**Architecture:** Phase 1 extends the existing LLM ensemble pipeline (config → odds → briefing → sim → consensus → edge). Phase 2 adds a new `simulation/` package with a statistical PA-level Monte Carlo engine that runs alongside the LLM ensemble, using the free MLB Stats API for player data.

**Tech Stack:** Python 3, requests, openai, pandas, dataclasses, math (Poisson CDF), random, concurrent.futures, MLB Stats API (free, no auth)

**Spec:** `docs/superpowers/specs/2026-03-20-market-expansion-design.md`

---

## File Structure

### Modified Files
| File | Responsibility |
|------|---------------|
| `config.py` | Add 8 new EDGE_THRESHOLDS entries |
| `scrapers/odds.py` | Add 8 new OddsData fields + event_id, add `get_additional_odds()` |
| `briefing.py` | Display new odds lines in briefing text |
| `simulate.py` | Expand system prompt + `_average_results()` for new sections |
| `edge.py` | Add 7 new edge checkers + Poisson helper, update `analyze_all_edges()` |
| `ensemble/weights.py` | Expand BET_SLOTS list |
| `ensemble/consensus.py` | Add 8 new BET_SLOT_FIELDS entries |
| `ensemble/orchestrator.py` | Add PROB_FIELDS, SLOT_SECTION, PRIMARY_PROB_FIELD entries + kill logic |
| `main.py` | Pass OddsData directly, add per-event odds fetch, add MC integration |

### New Files
| File | Responsibility |
|------|---------------|
| `scrapers/player_stats.py` | Fetch per-player stats from MLB Stats API, name resolution |
| `simulation/__init__.py` | Package exports |
| `simulation/pa_engine.py` | Single PA outcome sampling via odds-ratio method |
| `simulation/game_sim.py` | Full 9-inning game simulation with state tracking |
| `simulation/monte_carlo.py` | Run N iterations, aggregate per-player distributions |
| `simulation/props_edge.py` | Fetch prop odds, compare distributions to lines |
| `tests/test_edge_phase1.py` | Tests for 7 new edge checkers |
| `tests/test_pa_engine.py` | Tests for PA outcome sampling |
| `tests/test_game_sim.py` | Tests for game simulation |
| `tests/test_monte_carlo.py` | Tests for MC aggregation |
| `tests/test_props_edge.py` | Tests for prop edge detection |
| `tests/test_player_stats.py` | Tests for player stats fetching |

---

## Phase 1: Game-Level Market Expansion

### Task 1: Config + Weights — Add New Market Slots

**Files:**
- Modify: `config.py:40-47`
- Modify: `ensemble/weights.py:6`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add new edge thresholds to config.py**

In `config.py`, replace lines 40-47:

```python
# Edge thresholds per bet type (minimum edge to signal a bet)
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "run_line": 0.06,
    "total": 0.05,
    "first_5_ml": 0.05,
    "first_5_total": 0.05,
    # Phase 1: game-level expansion
    "team_total_home": 0.05,
    "team_total_away": 0.05,
    "first_5_rl": 0.05,
    "nrfi": 0.06,
    "first_1_rl": 0.06,
    "first_3_ml": 0.05,
    "first_3_total": 0.05,
    "first_3_rl": 0.05,
    # Phase 2: player props
    "pitcher_strikeouts": 0.05,
    "pitcher_earned_runs": 0.05,
    "pitcher_outs": 0.05,
    "pitcher_hits_allowed": 0.05,
    "batter_total_bases": 0.05,
    "batter_rbis": 0.05,
    "batter_hits": 0.05,
    "batter_runs_scored": 0.05,
    "batter_hits_runs_rbis": 0.05,
    "batter_strikeouts": 0.05,
}
```

- [ ] **Step 2: Update BET_SLOTS in weights.py**

In `ensemble/weights.py`, replace line 6:

```python
BET_SLOTS = [
    "moneyline", "run_line", "total", "first_5_ml", "first_5_total",
    "team_total_home", "team_total_away", "first_5_rl", "nrfi",
    "first_1_rl", "first_3_ml", "first_3_total", "first_3_rl",
]
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `pytest tests/test_config.py tests/test_ensemble_weights.py -v`
Expected: PASS (existing tests still work with expanded dicts/lists)

- [ ] **Step 4: Commit**

```bash
git add config.py ensemble/weights.py
git commit -m "feat: add edge thresholds and bet slots for 17 new markets"
```

---

### Task 2: OddsData Extension — New Fields + Per-Event Fetching

**Files:**
- Modify: `scrapers/odds.py:1-148`
- Test: `tests/test_odds.py`

- [ ] **Step 1: Write test for new OddsData fields**

Create `tests/test_odds_phase1.py`:

```python
"""Tests for Phase 1 OddsData extensions."""
from scrapers.odds import OddsData


def test_odds_data_has_new_fields():
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    assert od.event_id == ""
    assert od.team_total_home == {}
    assert od.team_total_away == {}
    assert od.f5_spread == {}
    assert od.f1_total == {}
    assert od.f1_spread == {}
    assert od.f3_moneyline == {}
    assert od.f3_total == {}
    assert od.f3_spread == {}


def test_parse_team_totals():
    """Team totals should parse home/away lines from API response."""
    from scrapers.odds import _parse_additional_markets

    raw_markets = {
        "team_totals": {
            "key": "team_totals",
            "outcomes": [
                {"name": "Over", "description": "New York Yankees", "price": -110, "point": 4.5},
                {"name": "Under", "description": "New York Yankees", "price": -110, "point": 4.5},
                {"name": "Over", "description": "Boston Red Sox", "price": -115, "point": 3.5},
                {"name": "Under", "description": "Boston Red Sox", "price": -105, "point": 3.5},
            ],
        }
    }
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    _parse_additional_markets(od, raw_markets)
    assert od.team_total_home["line"] == 4.5
    assert od.team_total_home["over_odds"] == -110
    assert od.team_total_away["line"] == 3.5


def test_parse_f5_spread():
    raw_markets = {
        "spreads_1st_5_innings": {
            "key": "spreads_1st_5_innings",
            "outcomes": [
                {"name": "New York Yankees", "price": -125, "point": -0.5},
                {"name": "Boston Red Sox", "price": 105, "point": 0.5},
            ],
        }
    }
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    _parse_additional_markets(od, raw_markets)
    assert od.f5_spread["home"] == -0.5
    assert od.f5_spread["home_odds"] == -125
    assert od.f5_spread["away"] == 0.5
    assert od.f5_spread["away_odds"] == 105


def test_parse_nrfi():
    raw_markets = {
        "totals_1st_1_innings": {
            "key": "totals_1st_1_innings",
            "outcomes": [
                {"name": "Over", "price": 115, "point": 0.5},
                {"name": "Under", "price": -135, "point": 0.5},
            ],
        }
    }
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    _parse_additional_markets(od, raw_markets)
    assert od.f1_total["line"] == 0.5
    assert od.f1_total["over_odds"] == 115   # YRFI
    assert od.f1_total["under_odds"] == -135  # NRFI
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_odds_phase1.py -v`
Expected: FAIL (new fields and `_parse_additional_markets` don't exist yet)

- [ ] **Step 3: Add new fields to OddsData and implement parsing**

In `scrapers/odds.py`, add fields to the OddsData dataclass after line 25:

```python
    # Phase 1 new fields
    event_id: str = ""
    team_total_home: dict = field(default_factory=dict)
    team_total_away: dict = field(default_factory=dict)
    f5_spread: dict = field(default_factory=dict)
    f1_total: dict = field(default_factory=dict)
    f1_spread: dict = field(default_factory=dict)
    f3_moneyline: dict = field(default_factory=dict)
    f3_total: dict = field(default_factory=dict)
    f3_spread: dict = field(default_factory=dict)
```

Add the parsing function after `_team_abbrev`:

```python
ADDITIONAL_MARKETS = (
    "team_totals,spreads_1st_5_innings,totals_1st_1_innings,"
    "spreads_1st_1_innings,h2h_1st_3_innings,totals_1st_3_innings,"
    "spreads_1st_3_innings"
)


def _parse_additional_markets(od: OddsData, markets: dict) -> None:
    """Parse additional market data into OddsData fields."""
    home = od.home
    away = od.away

    # Team totals
    if "team_totals" in markets:
        for outcome in markets["team_totals"].get("outcomes", []):
            team_abbrev = _team_abbrev(outcome.get("description", ""))
            if outcome["name"] == "Over":
                if team_abbrev == home:
                    od.team_total_home["line"] = outcome.get("point", 0)
                    od.team_total_home["over_odds"] = outcome["price"]
                elif team_abbrev == away:
                    od.team_total_away["line"] = outcome.get("point", 0)
                    od.team_total_away["over_odds"] = outcome["price"]
            elif outcome["name"] == "Under":
                if team_abbrev == home:
                    od.team_total_home["under_odds"] = outcome["price"]
                elif team_abbrev == away:
                    od.team_total_away["under_odds"] = outcome["price"]

    # Spread markets (F5, F1, F3) — same pattern
    spread_map = {
        "spreads_1st_5_innings": "f5_spread",
        "spreads_1st_1_innings": "f1_spread",
        "spreads_1st_3_innings": "f3_spread",
    }
    for market_key, field_name in spread_map.items():
        if market_key in markets:
            target = getattr(od, field_name)
            for outcome in markets[market_key].get("outcomes", []):
                if _team_abbrev(outcome["name"]) == home:
                    target["home"] = outcome.get("point", -0.5)
                    target["home_odds"] = outcome["price"]
                else:
                    target["away"] = outcome.get("point", 0.5)
                    target["away_odds"] = outcome["price"]

    # Totals markets (F1, F3)
    total_map = {
        "totals_1st_1_innings": "f1_total",
        "totals_1st_3_innings": "f3_total",
    }
    for market_key, field_name in total_map.items():
        if market_key in markets:
            target = getattr(od, field_name)
            for outcome in markets[market_key].get("outcomes", []):
                if outcome["name"] == "Over":
                    target["line"] = outcome.get("point", 0)
                    target["over_odds"] = outcome["price"]
                else:
                    target["under_odds"] = outcome["price"]

    # F3 moneyline
    if "h2h_1st_3_innings" in markets:
        for outcome in markets["h2h_1st_3_innings"].get("outcomes", []):
            if _team_abbrev(outcome["name"]) == home:
                od.f3_moneyline["home"] = outcome["price"]
            else:
                od.f3_moneyline["away"] = outcome["price"]


def get_additional_odds(event_id: str, api_requests_remaining: int = 999) -> dict:
    """Fetch additional markets via per-event endpoint.

    Returns raw markets dict or empty dict on failure.
    """
    if api_requests_remaining < 100:
        print("[odds] Skipping per-event fetch — API budget low")
        return {}

    url = f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": ADDITIONAL_MARKETS,
        "oddsFormat": "american",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        # Parse first bookmaker with data
        for bk in data.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}
            if markets:
                return markets
    except Exception as e:
        print(f"[odds] Per-event fetch failed for {event_id}: {e}")
    return {}
```

Also update `get_mlb_odds()` to store event_id. After line 80 (`commence_time=event["commence_time"],`), add:

```python
            event_id=event.get("id", ""),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_odds_phase1.py tests/test_odds.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/odds.py tests/test_odds_phase1.py
git commit -m "feat: extend OddsData with 8 new fields and per-event parsing"
```

---

### Task 3: Simulation Prompt + Averaging — New Prediction Sections

**Files:**
- Modify: `simulate.py:11-67` (system prompt), `simulate.py:170-197` (averaging)
- Test: `tests/test_simulate.py`

- [ ] **Step 1: Expand the system prompt**

In `simulate.py`, replace the JSON section of `MLB_SYSTEM_PROMPT` (lines 28-66) to add `first_inning`, `first_3`, and new fields in `total` and `first_5`:

```python
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
      "home_total_value": "over|under|none",
      "away_total_value": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_inning": {
      "nrfi_prob": 0.XX,
      "f1_home_lead_prob": 0.XX,
      "f1_away_lead_prob": 0.XX,
      "f1_tie_prob": 0.XX,
      "nrfi_value": "nrfi|yrfi|none",
      "f1_rl_value": "home|away|none",
      "confidence": "low|medium|high"
    },
    "first_3": {
      "f3_home_win_prob": 0.XX,
      "f3_away_win_prob": 0.XX,
      "f3_projected_total": X.X,
      "f3_home_lead_prob": 0.XX,
      "f3_away_lead_prob": 0.XX,
      "f3_tie_prob": 0.XX,
      "f3_ml_value": "home|away|none",
      "f3_total_value": "over|under|none",
      "f3_rl_value": "home|away|none",
      "confidence": "low|medium|high"
    },
    "first_5": {
      "f5_home_win_prob": 0.XX,
      "f5_away_win_prob": 0.XX,
      "f5_projected_total": X.X,
      "f5_home_lead_prob": 0.XX,
      "f5_away_lead_prob": 0.XX,
      "f5_tie_prob": 0.XX,
      "f5_ml_value": "home|away|none",
      "f5_total_value": "over|under|none",
      "f5_rl_value": "home|away|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": X, "home": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

- [ ] **Step 2: Update _average_results to handle new sections**

In `simulate.py`, update the `prob_fields` dict in `_average_results` (line 176):

```python
    prob_fields = {
        "moneyline": ["home_win_prob", "away_win_prob", "edge"],
        "run_line": ["favorite_cover_prob", "edge"],
        "total": ["projected_total", "over_prob", "under_prob", "edge"],
        "first_inning": ["nrfi_prob", "f1_home_lead_prob", "f1_away_lead_prob", "f1_tie_prob"],
        "first_3": ["f3_home_win_prob", "f3_away_win_prob", "f3_projected_total",
                     "f3_home_lead_prob", "f3_away_lead_prob", "f3_tie_prob"],
        "first_5": ["f5_home_win_prob", "f5_away_win_prob", "f5_projected_total",
                     "f5_home_lead_prob", "f5_away_lead_prob", "f5_tie_prob"],
    }
```

- [ ] **Step 3: Update the prediction task section in briefing.py**

In `briefing.py`, update lines 96-111 to add new prediction tasks:

```python
    prediction_task = f"""== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions
for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. RUN LINE (-1.5): Probability the favorite wins by 2+ runs.
3. TOTAL (O/U {total_line}): Projected total runs.
4. TEAM TOTALS: Projected runs for EACH team individually. Over or under on each team total?
5. FIRST INNING: What is the probability of NO runs scoring in the first inning (NRFI)?
   Who leads after 1 inning? What is the probability the game is TIED after 1 inning?
6. FIRST 3 INNINGS: Based on first pass through the batting order, who leads after 3?
   Projected F3 total? Probability of tie after 3 innings?
7. FIRST 5 INNINGS: Based on starting pitchers only, who leads after 5?
   Projected F5 total? Probability of tie after 5 innings?

For each bet type, provide probability estimates, value assessment, and confidence.
"""
```

Also add new odds lines to the BETTING LINES section if available. After the existing F5 lines (after line 66), add conditional display of new markets when the `odds` dict contains them.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_simulate.py tests/test_briefing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add simulate.py briefing.py
git commit -m "feat: expand system prompt and briefing for F1/F3/F5 and team total predictions"
```

---

### Task 4: Consensus + Orchestrator — New Slot Mappings

**Files:**
- Modify: `ensemble/consensus.py:4-10`
- Modify: `ensemble/orchestrator.py:34-58, 423-468`
- Test: `tests/test_ensemble_consensus.py`, `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Add new BET_SLOT_FIELDS in consensus.py**

Replace lines 4-10 of `ensemble/consensus.py`:

```python
BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "run_line": ("run_line", "value_side"),
    "total": ("total", "value_side"),
    "first_5_ml": ("first_5", "f5_ml_value"),
    "first_5_total": ("first_5", "f5_total_value"),
    # Phase 1 new
    "team_total_home": ("total", "home_total_value"),
    "team_total_away": ("total", "away_total_value"),
    "first_5_rl": ("first_5", "f5_rl_value"),
    "nrfi": ("first_inning", "nrfi_value"),
    "first_1_rl": ("first_inning", "f1_rl_value"),
    "first_3_ml": ("first_3", "f3_ml_value"),
    "first_3_total": ("first_3", "f3_total_value"),
    "first_3_rl": ("first_3", "f3_rl_value"),
}
```

- [ ] **Step 2: Add new entries to orchestrator mappings**

In `ensemble/orchestrator.py`, replace PROB_FIELDS (lines 34-40), SLOT_SECTION (lines 43-49), and PRIMARY_PROB_FIELD (lines 52-58):

```python
PROB_FIELDS = {
    "moneyline": ["home_win_prob", "away_win_prob"],
    "run_line": ["favorite_cover_prob"],
    "total": ["over_prob", "under_prob", "projected_total"],
    "first_5_ml": ["f5_home_win_prob", "f5_away_win_prob"],
    "first_5_total": ["f5_projected_total"],
    "team_total_home": ["predicted_score_home"],  # special-cased in averaging
    "team_total_away": ["predicted_score_away"],
    "first_5_rl": ["f5_home_lead_prob", "f5_tie_prob"],
    "nrfi": ["nrfi_prob"],
    "first_1_rl": ["f1_home_lead_prob", "f1_tie_prob"],
    "first_3_ml": ["f3_home_win_prob", "f3_away_win_prob"],
    "first_3_total": ["f3_projected_total"],
    "first_3_rl": ["f3_home_lead_prob", "f3_tie_prob"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "run_line": "run_line",
    "total": "total",
    "first_5_ml": "first_5",
    "first_5_total": "first_5",
    "team_total_home": "predicted_score",
    "team_total_away": "predicted_score",
    "first_5_rl": "first_5",
    "nrfi": "first_inning",
    "first_1_rl": "first_inning",
    "first_3_ml": "first_3",
    "first_3_total": "first_3",
    "first_3_rl": "first_3",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "home_win_prob",
    "run_line": "favorite_cover_prob",
    "total": "over_prob",
    "first_5_ml": "f5_home_win_prob",
    "first_5_total": "f5_projected_total",
    "team_total_home": "home",   # from predicted_score section
    "team_total_away": "away",   # from predicted_score section
    "first_5_rl": "f5_home_lead_prob",
    "nrfi": "nrfi_prob",
    "first_1_rl": "f1_home_lead_prob",
    "first_3_ml": "f3_home_win_prob",
    "first_3_total": "f3_projected_total",
    "first_3_rl": "f3_home_lead_prob",
}
```

- [ ] **Step 3: Update kill logic in build_ensemble_result**

In `ensemble/orchestrator.py`, replace the kill logic block (lines 429-467) with a generalized version:

```python
    # Kill slots from challenger
    section_sub_slots = {
        "first_5": {"first_5_ml", "first_5_total", "first_5_rl"},
        "first_inning": {"nrfi", "first_1_rl"},
        "first_3": {"first_3_ml", "first_3_total", "first_3_rl"},
    }
    killed_sub = set()

    for slot in killed_by_challenger:
        section_key = SLOT_SECTION.get(slot)
        if not section_key:
            continue
        # Top-level sections (moneyline, run_line, total) — remove entire section
        if section_key == slot:
            predictions.pop(section_key, None)
        else:
            # Sub-slot — track for potential section removal
            killed_sub.add(slot)

    # Remove entire section if ALL its sub-slots are killed
    for section_key, sub_slots in section_sub_slots.items():
        if sub_slots <= killed_sub:  # all killed
            predictions.pop(section_key, None)

    # Also remove slots with no consensus
    # For sub-slots, remove their specific fields rather than the whole section
    SUB_SLOT_FIELDS = {
        "first_5_ml": ["f5_home_win_prob", "f5_away_win_prob", "f5_ml_value"],
        "first_5_total": ["f5_projected_total", "f5_total_value"],
        "first_5_rl": ["f5_home_lead_prob", "f5_away_lead_prob", "f5_tie_prob", "f5_rl_value"],
        "nrfi": ["nrfi_prob", "nrfi_value"],
        "first_1_rl": ["f1_home_lead_prob", "f1_away_lead_prob", "f1_tie_prob", "f1_rl_value"],
        "first_3_ml": ["f3_home_win_prob", "f3_away_win_prob", "f3_ml_value"],
        "first_3_total": ["f3_projected_total", "f3_total_value"],
        "first_3_rl": ["f3_home_lead_prob", "f3_away_lead_prob", "f3_tie_prob", "f3_rl_value"],
    }
    for slot, info in classification.items():
        if info["level"] == "none":
            section_key = SLOT_SECTION.get(slot)
            if not section_key:
                continue
            if section_key == slot:
                # Top-level: remove entire section
                predictions.pop(section_key, None)
            elif slot in SUB_SLOT_FIELDS:
                # Sub-slot: remove only this slot's fields
                section = predictions.get(section_key, {})
                for field in SUB_SLOT_FIELDS[slot]:
                    section.pop(field, None)
```

- [ ] **Step 4: Update confidence setting to include new sections**

In `ensemble/orchestrator.py`, update the confidence loop (line 423) to include new sections:

```python
        for section_key in ["moneyline", "run_line", "total", "first_5", "first_inning", "first_3"]:
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_ensemble_consensus.py tests/test_ensemble_orchestrator.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ensemble/consensus.py ensemble/orchestrator.py
git commit -m "feat: add consensus and orchestrator mappings for 8 new bet slots"
```

---

### Task 5: Edge Detection — 7 New Market Checkers

**Files:**
- Modify: `edge.py`
- Create: `tests/test_edge_phase1.py`

- [ ] **Step 1: Write tests for new edge checkers**

Create `tests/test_edge_phase1.py`:

```python
"""Tests for Phase 1 edge detection: team totals, F5 RL, NRFI, F1 RL, F3 ML/total/RL."""
from edge import (
    check_team_total_edge, check_f5_rl_edge, check_nrfi_edge,
    check_f1_rl_edge, check_f3_ml_edge, check_f3_total_edge,
    check_f3_rl_edge, _poisson_over_prob, analyze_all_edges,
)
from scrapers.odds import OddsData


def test_poisson_over_prob_high_predicted():
    """If predicted=6.0 and line=4.5, over probability should be high."""
    prob = _poisson_over_prob(6.0, 4.5)
    assert prob > 0.70


def test_poisson_over_prob_low_predicted():
    """If predicted=3.0 and line=4.5, over probability should be low."""
    prob = _poisson_over_prob(3.0, 4.5)
    assert prob < 0.30


def test_team_total_edge_found():
    sim = {"predictions": {"predicted_score": {"home": 6, "away": 3}}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        team_total_home={"line": 4.5, "over_odds": -110, "under_odds": -110},
    )
    result = check_team_total_edge(sim, odds, "home")
    assert result is not None
    assert result["bet_type"] == "team_total_home"
    assert result["edge"] > 0


def test_team_total_edge_no_edge():
    sim = {"predictions": {"predicted_score": {"home": 4.5, "away": 3}}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        team_total_home={"line": 4.5, "over_odds": -110, "under_odds": -110},
    )
    result = check_team_total_edge(sim, odds, "home")
    assert result is None  # no edge when predicted == line


def test_nrfi_edge_found():
    sim = {"predictions": {"first_inning": {"nrfi_prob": 0.75, "confidence": "high"}}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        f1_total={"line": 0.5, "over_odds": 100, "under_odds": -120},
    )
    result = check_nrfi_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "nrfi"
    assert result["side"] == "NRFI"


def test_f5_rl_edge_uses_tie_prob():
    """F5 RL should use lead_prob, not win_prob. Tie goes to +0.5 side."""
    sim = {"predictions": {"first_5": {
        "f5_home_lead_prob": 0.40,
        "f5_away_lead_prob": 0.25,
        "f5_tie_prob": 0.35,
        "confidence": "medium",
    }}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        f5_spread={"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
    )
    result = check_f5_rl_edge(sim, odds)
    # away +0.5 = 0.25 + 0.35 = 0.60, implied ~0.5 → edge ~0.10
    assert result is not None
    assert "away" in result["side"].lower() or "+0.5" in result["side"]


def test_f3_ml_edge_found():
    sim = {"predictions": {"first_3": {
        "f3_home_win_prob": 0.62,
        "f3_away_win_prob": 0.38,
        "confidence": "medium",
    }}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        f3_moneyline={"home": -120, "away": 100},
    )
    result = check_f3_ml_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "first_3_ml"


def test_analyze_all_edges_includes_new_checkers():
    """analyze_all_edges should run all 12 checkers."""
    sim = {"predictions": {
        "moneyline": {"home_win_prob": 0.5, "away_win_prob": 0.5, "confidence": "low"},
        "predicted_score": {"home": 4, "away": 4},
    }}
    odds = OddsData(home="NYY", away="BOS", commence_time="",
                     moneyline={"home": -110, "away": -110},
                     implied_probs={"ml_home": 0.5, "ml_away": 0.5})
    bets = analyze_all_edges(sim, odds)
    # No edges expected, but it should not crash
    assert isinstance(bets, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_edge_phase1.py -v`
Expected: FAIL (new functions don't exist yet)

- [ ] **Step 3: Implement the 7 new edge checkers + Poisson helper**

In `edge.py`, add at the top (after imports):

```python
from math import exp, factorial
```

Add the Poisson helper and new edge checkers before `analyze_all_edges`:

```python
def _poisson_over_prob(predicted: float, line: float) -> float:
    """Calculate P(over line) using Poisson CDF."""
    if predicted <= 0:
        return 0.01
    k_max = int(line)
    cdf = sum(
        (predicted ** k) * exp(-predicted) / factorial(k)
        for k in range(k_max + 1)
    )
    return max(0.01, min(0.99, 1 - cdf))


def check_team_total_edge(sim: dict, odds: OddsData, side: str) -> dict | None:
    """Check team total edge for home or away."""
    predicted = sim.get("predictions", {}).get("predicted_score", {}).get(side)
    tt = odds.team_total_home if side == "home" else odds.team_total_away
    if not predicted or not tt or "line" not in tt:
        return None

    bet_type = f"team_total_{side}"
    threshold = EDGE_THRESHOLDS.get(bet_type, 0.05)
    line = tt["line"]

    over_prob = _poisson_over_prob(float(predicted), line)
    under_prob = 1 - over_prob

    over_odds = tt.get("over_odds", -110)
    under_odds = tt.get("under_odds", -110)
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total_impl = over_implied + under_implied
    over_implied /= total_impl
    under_implied /= total_impl

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": bet_type,
            "side": f"{side} over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": "medium",
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": bet_type,
            "side": f"{side} under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": "medium",
        }
    return None


def _check_innings_spread_edge(sim: dict, odds: OddsData, period: str,
                                bet_type: str, spread_field: str,
                                lead_home_key: str, lead_away_key: str,
                                tie_key: str) -> dict | None:
    """Generic innings spread checker. Ties go to +0.5 side."""
    pred = sim.get("predictions", {}).get(period, {})
    spread = getattr(odds, spread_field, {})
    if not pred or not spread:
        return None

    threshold = EDGE_THRESHOLDS.get(bet_type, 0.05)

    home_lead = pred.get(lead_home_key, 0)
    away_lead = pred.get(lead_away_key, 0)
    tie_prob = pred.get(tie_key, 0)

    # -0.5 side: must be leading (tie = loss)
    # +0.5 side: leading OR tied (tie = win)
    home_minus_prob = home_lead
    away_plus_prob = away_lead + tie_prob
    away_minus_prob = away_lead
    home_plus_prob = home_lead + tie_prob

    home_odds_val = spread.get("home_odds", -110)
    away_odds_val = spread.get("away_odds", -110)
    h_implied = american_to_implied_prob(home_odds_val)
    a_implied = american_to_implied_prob(away_odds_val)
    total = h_implied + a_implied
    h_implied /= total
    a_implied /= total

    # Determine which side has the -0.5 (favorite)
    home_point = spread.get("home", -0.5)
    if home_point < 0:
        # Home is -0.5 favorite
        home_edge = home_minus_prob - h_implied
        away_edge = away_plus_prob - a_implied
        home_label = f"home {home_point}"
        away_label = f"away +{abs(spread.get('away', 0.5))}"
        home_prob = home_minus_prob
        away_prob = away_plus_prob
    else:
        # Away is -0.5 favorite
        home_edge = home_plus_prob - h_implied
        away_edge = away_minus_prob - a_implied
        home_label = f"home +{home_point}"
        away_label = f"away {spread.get('away', -0.5)}"
        home_prob = home_plus_prob
        away_prob = away_minus_prob

    if home_edge >= threshold and home_edge >= away_edge:
        dec = american_to_decimal(home_odds_val)
        return {
            "bet_type": bet_type,
            "side": home_label,
            "odds": home_odds_val,
            "sim_prob": round(home_prob, 4),
            "market_prob": round(h_implied, 4),
            "edge": round(home_edge, 4),
            "kelly_pct": round(kelly_criterion(home_prob, dec) * KELLY_FRACTION, 4),
            "confidence": pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        dec = american_to_decimal(away_odds_val)
        return {
            "bet_type": bet_type,
            "side": away_label,
            "odds": away_odds_val,
            "sim_prob": round(away_prob, 4),
            "market_prob": round(a_implied, 4),
            "edge": round(away_edge, 4),
            "kelly_pct": round(kelly_criterion(away_prob, dec) * KELLY_FRACTION, 4),
            "confidence": pred.get("confidence", "medium"),
        }
    return None


def check_f5_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    return _check_innings_spread_edge(
        sim, odds, "first_5", "first_5_rl", "f5_spread",
        "f5_home_lead_prob", "f5_away_lead_prob", "f5_tie_prob")


def check_nrfi_edge(sim: dict, odds: OddsData) -> dict | None:
    """NRFI: under 0.5 runs in first inning."""
    pred = sim.get("predictions", {}).get("first_inning", {})
    f1_total = odds.f1_total
    if not pred or not f1_total:
        return None

    threshold = EDGE_THRESHOLDS.get("nrfi", 0.06)
    nrfi_prob = pred.get("nrfi_prob", 0)
    yrfi_prob = 1 - nrfi_prob

    under_odds = f1_total.get("under_odds", -110)  # NRFI
    over_odds = f1_total.get("over_odds", -110)      # YRFI
    nrfi_implied = american_to_implied_prob(under_odds)
    yrfi_implied = american_to_implied_prob(over_odds)
    total_impl = nrfi_implied + yrfi_implied
    nrfi_implied /= total_impl
    yrfi_implied /= total_impl

    nrfi_edge = nrfi_prob - nrfi_implied
    yrfi_edge = yrfi_prob - yrfi_implied

    if nrfi_edge >= threshold and nrfi_edge >= yrfi_edge:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "nrfi",
            "side": "NRFI",
            "odds": under_odds,
            "sim_prob": round(nrfi_prob, 4),
            "market_prob": round(nrfi_implied, 4),
            "edge": round(nrfi_edge, 4),
            "kelly_pct": round(kelly_criterion(nrfi_prob, dec) * KELLY_FRACTION, 4),
            "confidence": pred.get("confidence", "medium"),
        }
    elif yrfi_edge >= threshold:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "nrfi",
            "side": "YRFI",
            "odds": over_odds,
            "sim_prob": round(yrfi_prob, 4),
            "market_prob": round(yrfi_implied, 4),
            "edge": round(yrfi_edge, 4),
            "kelly_pct": round(kelly_criterion(yrfi_prob, dec) * KELLY_FRACTION, 4),
            "confidence": pred.get("confidence", "medium"),
        }
    return None


def check_f1_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    return _check_innings_spread_edge(
        sim, odds, "first_inning", "first_1_rl", "f1_spread",
        "f1_home_lead_prob", "f1_away_lead_prob", "f1_tie_prob")


def check_f3_ml_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 moneyline — same pattern as F5 ML."""
    f3_pred = sim.get("predictions", {}).get("first_3", {})
    f3_ml = odds.f3_moneyline
    if not f3_pred or not f3_ml:
        return None

    threshold = EDGE_THRESHOLDS.get("first_3_ml", 0.05)
    home_odds = f3_ml.get("home", -110)
    away_odds = f3_ml.get("away", -110)
    h_implied = american_to_implied_prob(home_odds)
    a_implied = american_to_implied_prob(away_odds)
    total = h_implied + a_implied
    h_implied /= total
    a_implied /= total

    h_prob = f3_pred.get("f3_home_win_prob", 0)
    a_prob = f3_pred.get("f3_away_win_prob", 0)
    h_edge = h_prob - h_implied
    a_edge = a_prob - a_implied

    if h_edge >= threshold and h_edge >= a_edge:
        dec = american_to_decimal(home_odds)
        return {
            "bet_type": "first_3_ml",
            "side": "home F3 ML",
            "odds": home_odds,
            "sim_prob": h_prob,
            "market_prob": round(h_implied, 4),
            "edge": round(h_edge, 4),
            "kelly_pct": round(kelly_criterion(h_prob, dec) * KELLY_FRACTION, 4),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    elif a_edge >= threshold:
        dec = american_to_decimal(away_odds)
        return {
            "bet_type": "first_3_ml",
            "side": "away F3 ML",
            "odds": away_odds,
            "sim_prob": a_prob,
            "market_prob": round(a_implied, 4),
            "edge": round(a_edge, 4),
            "kelly_pct": round(kelly_criterion(a_prob, dec) * KELLY_FRACTION, 4),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    return None


def check_f3_total_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 total — same pattern as F5 total with Poisson."""
    f3_pred = sim.get("predictions", {}).get("first_3", {})
    f3_total = odds.f3_total
    if not f3_pred or not f3_total:
        return None

    projected = f3_pred.get("f3_projected_total")
    if projected is None:
        return None
    line = f3_total.get("line")
    if line is None:
        return None

    threshold = EDGE_THRESHOLDS.get("first_3_total", 0.05)
    over_prob = _poisson_over_prob(float(projected), line)
    under_prob = 1 - over_prob

    over_odds = f3_total.get("over_odds", -110)
    under_odds = f3_total.get("under_odds", -110)
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total_impl = over_implied + under_implied
    over_implied /= total_impl
    under_implied /= total_impl

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "first_3_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "first_3_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    return None


def check_f3_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    return _check_innings_spread_edge(
        sim, odds, "first_3", "first_3_rl", "f3_spread",
        "f3_home_lead_prob", "f3_away_lead_prob", "f3_tie_prob")
```

- [ ] **Step 4: Update analyze_all_edges to accept OddsData and run all 12 checkers**

Replace `analyze_all_edges` (lines 311-335):

```python
def analyze_all_edges(sim: dict, odds) -> list[dict]:
    """Run all edge checks for a single game.

    Args:
        odds: OddsData instance or plain dict (backwards compatible).
    """
    from scrapers.odds import OddsData

    bets = []

    # If odds is a plain dict (legacy), wrap key fields for backwards compat
    if isinstance(odds, dict):
        # Legacy path: existing 5 checkers with dict access
        legacy_checkers = [
            ("moneyline", check_moneyline_edge),
            ("run_line", check_run_line_edge),
            ("total", check_total_edge),
            ("first_5_ml", check_f5_ml_edge),
            ("first_5_total", check_f5_total_edge),
        ]
        for name, checker in legacy_checkers:
            result = checker(sim, odds)
            if result:
                bets.append(result)
                logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])
        return bets

    # New path: OddsData instance — run all 12 checkers
    # Existing 5 (convert OddsData to dict for backwards compat)
    odds_dict = {
        "moneyline": odds.moneyline,
        "run_line": odds.run_line,
        "total": odds.total,
        "f5_moneyline": odds.f5_moneyline,
        "f5_total": odds.f5_total,
        "implied_probs": odds.implied_probs,
    }
    legacy_checkers = [
        ("moneyline", check_moneyline_edge),
        ("run_line", check_run_line_edge),
        ("total", check_total_edge),
        ("first_5_ml", check_f5_ml_edge),
        ("first_5_total", check_f5_total_edge),
    ]
    for name, checker in legacy_checkers:
        result = checker(sim, odds_dict)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])

    # Phase 1 new checkers (use OddsData directly)
    new_checkers = [
        ("team_total_home", lambda s, o: check_team_total_edge(s, o, "home")),
        ("team_total_away", lambda s, o: check_team_total_edge(s, o, "away")),
        ("first_5_rl", check_f5_rl_edge),
        ("nrfi", check_nrfi_edge),
        ("first_1_rl", check_f1_rl_edge),
        ("first_3_ml", check_f3_ml_edge),
        ("first_3_total", check_f3_total_edge),
        ("first_3_rl", check_f3_rl_edge),
    ]
    for name, checker in new_checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])

    logger.info("Edge analysis: %d bet types have value", len(bets))
    return bets
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_edge_phase1.py tests/test_edge.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add edge.py tests/test_edge_phase1.py
git commit -m "feat: add 7 new edge checkers (team totals, NRFI, F1/F3/F5 RL, F3 ML/total)"
```

---

### Task 6: Pipeline Integration — Pass OddsData + Fetch Additional Markets

**Files:**
- Modify: `main.py:144-168, 231-252`

- [ ] **Step 1: Update main.py to pass OddsData directly and fetch additional markets**

In `main.py`, update the game_data construction (lines 144-168) to pass the OddsData object directly instead of a dict:

Replace `game_data["odds"]` construction and usage:
- Store the OddsData instance directly: `game_data["odds"] = odds`
- After the bulk odds fetch, add per-event fetching for additional markets
- In the screening pass, `analyze_all_edges(screen, odds)` now accepts OddsData
- In the full sim pass, `analyze_all_edges(result, odds)` likewise

Key changes to the daily pipeline:

After step 2 (odds fetch), add per-event enrichment:

```python
    # Enrich with additional markets (per-event endpoint)
    api_remaining = int(resp.headers.get("x-requests-remaining", "999"))
    if api_remaining >= 100:
        click.echo(f"  Fetching additional markets for {len(odds_list)} games...")
        from scrapers.odds import get_additional_odds, _parse_additional_markets
        for o in odds_list:
            if o.event_id:
                additional = get_additional_odds(o.event_id, api_remaining)
                if additional:
                    _parse_additional_markets(o, additional)
    else:
        click.echo(f"  Skipping additional markets (API budget low: {api_remaining})")
```

Update game_data to store BOTH the OddsData instance and a dict. The dict is needed because `extract_vote` in consensus.py uses `odds.get("run_line", {})` (dict access) — passing OddsData to the ensemble would crash. The OddsData instance is needed by the new edge checkers.

```python
            game_data = {
                ...
                "odds_obj": odds,  # OddsData instance for edge detection
                "odds": {  # dict for ensemble/consensus + briefing (backwards compat)
                    "moneyline": odds.moneyline,
                    "run_line": odds.run_line,
                    "total": odds.total,
                    "f5_moneyline": odds.f5_moneyline,
                    "f5_total": odds.f5_total,
                    "implied_probs": odds.implied_probs,
                    "f3_moneyline": odds.f3_moneyline,
                    "f3_total": odds.f3_total,
                    "f1_total": odds.f1_total,
                    "team_total_home": odds.team_total_home,
                    "team_total_away": odds.team_total_away,
                },
                ...
            }
```

Update briefing.py to use `game_data["odds"]` (the dict) for template rendering.

Update edge calls to pass OddsData: `analyze_all_edges(screen, game_data["odds_obj"])` and `analyze_all_edges(result, game_data["odds_obj"])`.

Keep ensemble calls using the dict: `run_mirofish(brief, runs=3, odds=game_data["odds"])` — this preserves backwards compatibility with `extract_vote` in consensus.py which uses dict-style access.

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/ -v --timeout=30`
Expected: PASS (all existing + new tests)

- [ ] **Step 3: Commit**

```bash
git add main.py briefing.py
git commit -m "feat: pipeline integration — pass OddsData directly, fetch additional markets"
```

---

## Phase 2: Monte Carlo PA Simulation Engine

### Task 7: PA Engine — Odds-Ratio Outcome Sampling

**Files:**
- Create: `simulation/__init__.py`
- Create: `simulation/pa_engine.py`
- Create: `tests/test_pa_engine.py`

- [ ] **Step 1: Write tests for PA engine**

Create `tests/test_pa_engine.py`:

```python
"""Tests for plate appearance outcome sampling."""
from simulation.pa_engine import matchup_probability, sample_pa, OUTCOMES, normalize_probs


def test_matchup_probability_neutral():
    """When batter and pitcher are league average, result should be league average."""
    league = 0.20
    prob = matchup_probability(league, league, league)
    assert abs(prob - league) < 0.01


def test_matchup_probability_strong_batter():
    """Strong batter + average pitcher should exceed league average."""
    prob = matchup_probability(batter_rate=0.30, pitcher_rate=0.20, league_rate=0.20)
    assert prob > 0.20


def test_normalize_probs_sums_to_one():
    raw = {"K": 0.3, "BB": 0.1, "1B": 0.2, "2B": 0.05, "3B": 0.01, "HR": 0.04, "OUT": 0.5}
    normed = normalize_probs(raw)
    assert abs(sum(normed.values()) - 1.0) < 0.001


def test_sample_pa_returns_valid_outcome():
    batter = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03,
              "single_pct": 0.15, "double_pct": 0.04, "triple_pct": 0.004, "out_pct": 0.46}
    pitcher = {"k_pct": 0.25, "bb_pct": 0.07, "hr_pct": 0.025,
               "single_pct": 0.14, "double_pct": 0.04, "triple_pct": 0.003, "out_pct": 0.46}
    result = sample_pa(batter, pitcher)
    assert result in OUTCOMES


def test_sample_pa_distribution_reasonable():
    """Over 10000 samples, K rate should be roughly in expected range."""
    import random
    random.seed(42)
    batter = {"k_pct": 0.25, "bb_pct": 0.08, "hr_pct": 0.03,
              "single_pct": 0.15, "double_pct": 0.04, "triple_pct": 0.004, "out_pct": 0.44}
    pitcher = {"k_pct": 0.25, "bb_pct": 0.08, "hr_pct": 0.03,
               "single_pct": 0.15, "double_pct": 0.04, "triple_pct": 0.004, "out_pct": 0.44}
    results = [sample_pa(batter, pitcher) for _ in range(10000)]
    k_rate = results.count("K") / len(results)
    assert 0.20 < k_rate < 0.35  # roughly around 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pa_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PA engine**

Create `simulation/__init__.py`:
```python
"""Monte Carlo baseball simulation engine for player prop predictions."""
```

Create `simulation/pa_engine.py`:
```python
"""Plate appearance outcome sampling using the odds-ratio method."""
import random

OUTCOMES = ["K", "BB", "1B", "2B", "3B", "HR", "OUT"]

LEAGUE_AVERAGES = {
    "k_pct": 0.224,
    "bb_pct": 0.084,
    "hr_pct": 0.033,
    "single_pct": 0.152,
    "double_pct": 0.044,
    "triple_pct": 0.004,
    "out_pct": 0.459,
}


def matchup_probability(batter_rate: float, pitcher_rate: float, league_rate: float) -> float:
    """Combine batter and pitcher rates using odds-ratio method."""
    if league_rate <= 0:
        return batter_rate
    return (batter_rate * pitcher_rate) / league_rate


def normalize_probs(raw: dict) -> dict:
    """Normalize probability dict to sum to 1.0."""
    total = sum(raw.values())
    if total <= 0:
        n = len(raw)
        return {k: 1.0 / n for k in raw}
    return {k: v / total for k, v in raw.items()}


def _build_matchup_probs(batter: dict, pitcher: dict) -> dict:
    """Build normalized outcome probabilities for a batter-pitcher matchup."""
    raw = {}
    outcome_keys = [
        ("K", "k_pct"),
        ("BB", "bb_pct"),
        ("HR", "hr_pct"),
        ("1B", "single_pct"),
        ("2B", "double_pct"),
        ("3B", "triple_pct"),
        ("OUT", "out_pct"),
    ]
    for outcome, key in outcome_keys:
        b_rate = batter.get(key, LEAGUE_AVERAGES[key])
        p_rate = pitcher.get(key, LEAGUE_AVERAGES[key])
        l_rate = LEAGUE_AVERAGES[key]
        raw[outcome] = matchup_probability(b_rate, p_rate, l_rate)
    return normalize_probs(raw)


def sample_pa(batter: dict, pitcher: dict) -> str:
    """Sample a single plate appearance outcome."""
    probs = _build_matchup_probs(batter, pitcher)
    r = random.random()
    cumulative = 0.0
    for outcome in OUTCOMES:
        cumulative += probs[outcome]
        if r < cumulative:
            return outcome
    return OUTCOMES[-1]  # fallback to OUT
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pa_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add simulation/__init__.py simulation/pa_engine.py tests/test_pa_engine.py
git commit -m "feat: PA outcome sampling engine with odds-ratio method"
```

---

### Task 8: Game Simulation — Full 9-Inning State Tracking

**Files:**
- Create: `simulation/game_sim.py`
- Create: `tests/test_game_sim.py`

- [ ] **Step 1: Write tests**

Create `tests/test_game_sim.py`:

```python
"""Tests for full game simulation."""
from simulation.game_sim import simulate_game, advance_runners, GameState

# League-average batter and pitcher for testing
AVG_BATTER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
              "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459}
AVG_PITCHER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
               "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459,
               "avg_pitch_count": 90}


def test_advance_runners_single_empty():
    bases, rbi = advance_runners([0, 0, 0], "1B", 0)
    assert bases[0] == 1  # batter on first
    assert rbi == 0


def test_advance_runners_hr_clears_bases():
    bases, rbi = advance_runners([1, 1, 1], "HR", 0)
    assert bases == [0, 0, 0]
    assert rbi == 4  # 3 runners + batter


def test_advance_runners_single_scores_from_third():
    bases, rbi = advance_runners([0, 0, 1], "1B", 0)
    assert rbi >= 1  # runner on 3B scores


def test_simulate_game_completes():
    import random
    random.seed(42)
    lineup = [AVG_BATTER.copy() for _ in range(9)]
    for i, b in enumerate(lineup):
        b["player_id"] = i + 1

    state = simulate_game(
        home_lineup=lineup,
        away_lineup=lineup,
        home_pitcher=AVG_PITCHER.copy(),
        away_pitcher=AVG_PITCHER.copy(),
    )
    assert state.inning >= 9
    assert state.score["home"] >= 0
    assert state.score["away"] >= 0
    # Should have some stats tracked
    assert len(state.batter_stats) > 0
    assert len(state.pitcher_stats) > 0


def test_simulate_game_reasonable_scores():
    """Average of many sims should be ~4-5 runs per team."""
    import random
    random.seed(123)
    lineup = [AVG_BATTER.copy() for _ in range(9)]
    for i, b in enumerate(lineup):
        b["player_id"] = i + 1
    pitcher = AVG_PITCHER.copy()
    pitcher["player_id"] = 100

    scores = []
    for _ in range(200):
        state = simulate_game(
            home_lineup=lineup, away_lineup=lineup,
            home_pitcher=pitcher.copy(), away_pitcher=pitcher.copy(),
        )
        scores.append(state.score["home"] + state.score["away"])

    avg = sum(scores) / len(scores)
    assert 6 < avg < 12  # league average ~8-10 total runs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_game_sim.py -v`
Expected: FAIL

- [ ] **Step 3: Implement game simulation**

Create `simulation/game_sim.py`. This is the largest new file — implements full 9-inning game with runner advancement, scoring, pitcher stats, batter stats, pitch count tracking. See spec for detailed `GameState` dataclass and `simulate_game()` function.

Key elements:
- `GameState` dataclass with score, bases, outs, inning, half, score_by_inning, pitcher_stats, batter_stats
- `advance_runners(bases, hit_type, outs)` → (new_bases, runs_scored)
- `simulate_game(home_lineup, away_lineup, home_pitcher, away_pitcher, park_factor_runs, park_factor_hr)` → GameState
- Pitch count per outcome: K=4.8, BB=5.6, HR=3.5, singles/outs=~3.3-3.4
- Pitcher exits when estimated_pitches > avg_pitch_count * 1.1 (uses league-average reliever stats after)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_game_sim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add simulation/game_sim.py tests/test_game_sim.py
git commit -m "feat: full 9-inning game simulation with state tracking"
```

---

### Task 9: Monte Carlo Aggregation — Distribution Builder

**Files:**
- Create: `simulation/monte_carlo.py`
- Create: `tests/test_monte_carlo.py`

- [ ] **Step 1: Write tests**

Create `tests/test_monte_carlo.py`:

```python
"""Tests for Monte Carlo distribution aggregation."""
from simulation.monte_carlo import run_monte_carlo

AVG_BATTER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
              "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459}
AVG_PITCHER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
               "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459,
               "avg_pitch_count": 90}


def test_monte_carlo_returns_distributions():
    import random
    random.seed(42)
    lineup = [AVG_BATTER.copy() for _ in range(9)]
    for i, b in enumerate(lineup):
        b["player_id"] = i + 1
    pitcher = AVG_PITCHER.copy()
    pitcher["player_id"] = 100

    result = run_monte_carlo(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher=pitcher.copy(), away_pitcher=pitcher.copy(),
        n_sims=100,  # small for speed
    )

    assert result["n_sims"] == 100
    assert "pitcher_distributions" in result
    assert "batter_distributions" in result
    assert "game_results" in result

    # Check pitcher K distribution exists
    assert 100 in result["pitcher_distributions"]
    assert "k" in result["pitcher_distributions"][100]

    # Check batter hit distribution exists
    assert 1 in result["batter_distributions"]
    assert "h" in result["batter_distributions"][1]

    # Check tie rates
    gr = result["game_results"]
    assert 0 <= gr["tied_after_1"] <= 1
    assert 0 <= gr["tied_after_5"] <= 1


def test_monte_carlo_distributions_sum_to_one():
    import random
    random.seed(42)
    lineup = [AVG_BATTER.copy() for _ in range(9)]
    for i, b in enumerate(lineup):
        b["player_id"] = i + 1
    pitcher = AVG_PITCHER.copy()
    pitcher["player_id"] = 100

    result = run_monte_carlo(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher=pitcher.copy(), away_pitcher=pitcher.copy(),
        n_sims=100,
    )

    k_dist = result["pitcher_distributions"][100]["k"]
    assert abs(sum(k_dist) - 1.0) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_monte_carlo.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Monte Carlo aggregation**

Create `simulation/monte_carlo.py`:
- `run_monte_carlo(home_lineup, away_lineup, home_pitcher, away_pitcher, park_factor_runs, park_factor_hr, n_sims)` → dict
- Runs `simulate_game()` n_sims times
- Aggregates per-player stat counts into probability distributions
- Tracks score-by-inning for tied_after_1/3/5 calculations
- Returns pitcher_distributions, batter_distributions, game_results

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_monte_carlo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add simulation/monte_carlo.py tests/test_monte_carlo.py
git commit -m "feat: Monte Carlo aggregation with per-player stat distributions"
```

---

### Task 10: Player Stats Scraper

**Files:**
- Create: `scrapers/player_stats.py`
- Create: `tests/test_player_stats.py`

- [ ] **Step 1: Write tests**

Create `tests/test_player_stats.py` with tests for stat parsing and name resolution. Mock the MLB Stats API responses.

- [ ] **Step 2: Implement player stats scraper**

Create `scrapers/player_stats.py`:
- `get_batter_stats(player_id, season)` → dict with k_pct, bb_pct, hr_pct, etc.
- `get_pitcher_stats(player_id, season)` → dict with same rate fields
- `get_lineup(game_pk)` → {"home": [ids], "away": [ids], "home_pitcher": id, "away_pitcher": id}
- `resolve_player(name, team)` → player_id or None (6-step fallback chain)
- Caching in `data/player_stats/` per day
- Uses MLB Stats API: `https://statsapi.mlb.com/api/v1/`

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_player_stats.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scrapers/player_stats.py tests/test_player_stats.py
git commit -m "feat: player stats scraper with MLB Stats API and name resolution"
```

---

### Task 11: Props Edge Detection + Odds Fetching

**Files:**
- Create: `simulation/props_edge.py`
- Create: `tests/test_props_edge.py`

- [ ] **Step 1: Write tests**

Create `tests/test_props_edge.py`:

```python
"""Tests for prop edge detection."""
from simulation.props_edge import distribution_to_over_prob, check_prop_edge


def test_distribution_to_over_prob_high():
    # Distribution heavily above line
    dist = [0.0, 0.0, 0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.10, 0.05, 0.05]
    prob = distribution_to_over_prob(dist, 4.5)
    assert prob > 0.75


def test_distribution_to_over_prob_low():
    # Distribution heavily below line
    dist = [0.10, 0.20, 0.25, 0.20, 0.15, 0.05, 0.03, 0.02]
    prob = distribution_to_over_prob(dist, 4.5)
    assert prob < 0.15


def test_check_prop_edge_found():
    dist = [0.0, 0.0, 0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.10, 0.05, 0.05]
    result = check_prop_edge(
        distribution=dist, line=4.5,
        over_odds=-110, under_odds=-110,
        threshold=0.05, bet_type="pitcher_strikeouts",
        player_name="Test Pitcher",
    )
    assert result is not None
    assert result["bet_type"] == "pitcher_strikeouts"
    assert result["edge"] > 0.05
```

- [ ] **Step 2: Implement props edge detection**

Create `simulation/props_edge.py`:
- `distribution_to_over_prob(distribution, line)` → float
- `check_prop_edge(distribution, line, over_odds, under_odds, threshold, bet_type, player_name)` → dict | None
- `get_prop_odds(event_id)` → dict (fetches from Odds API per-event endpoint)
- `analyze_all_props(mc_results, prop_odds)` → list[dict]
- Player name matching: uses `resolve_player()` from player_stats, logs unmatched to `data/unmatched_players.log`

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_props_edge.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add simulation/props_edge.py tests/test_props_edge.py
git commit -m "feat: prop edge detection with distribution-to-probability conversion"
```

---

### Task 12: Pipeline Integration — MC Engine in Daily Pipeline

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add MC engine to the full simulation step**

In `main.py`, after the existing `run_mirofish` call in step 6, add:

```python
            # Run Monte Carlo prop simulation if lineups confirmed
            try:
                from simulation.monte_carlo import run_monte_carlo
                from simulation.props_edge import get_prop_odds, analyze_all_props
                from scrapers.player_stats import get_lineup, get_batter_stats, get_pitcher_stats

                game_pk = game.get("game_pk")
                if game_pk:
                    lineup_data = get_lineup(game_pk)
                    if lineup_data and lineup_data.get("home") and lineup_data.get("away"):
                        season = int(game_date[:4])
                        home_lineup = [get_batter_stats(pid, season) for pid in lineup_data["home"]]
                        away_lineup = [get_batter_stats(pid, season) for pid in lineup_data["away"]]
                        hp_stats = get_pitcher_stats(lineup_data["home_pitcher"], season)
                        ap_stats = get_pitcher_stats(lineup_data["away_pitcher"], season)

                        park = PARK_FACTORS.get(home, {})
                        mc_results = run_monte_carlo(
                            home_lineup=home_lineup, away_lineup=away_lineup,
                            home_pitcher=hp_stats, away_pitcher=ap_stats,
                            park_factor_runs=park.get("runs", 1.0),
                            park_factor_hr=park.get("hr", 1.0),
                            n_sims=5000,
                        )

                        if odds.event_id:
                            prop_odds = get_prop_odds(odds.event_id)
                            prop_bets = analyze_all_props(mc_results, prop_odds)
                            for bet in prop_bets:
                                bet["date"] = game_date
                                bet["game"] = game_key
                                click.echo(
                                    f"    PROP: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                                    f"Edge: {bet['edge']:.1%}"
                                )
                                log_bet(bet)
                                total_bets += 1
                    else:
                        logger.info("  %s: lineup not confirmed, skipping MC props", game_key)
            except Exception as e:
                logger.error("  %s: MC prop simulation failed: %s", game_key, e)
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v --timeout=60`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: integrate Monte Carlo prop engine into daily pipeline"
```

---

### Task 13: Final Integration Test

**Files:**
- All modified/created files

- [ ] **Step 1: Run complete test suite**

Run: `pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 2: Verify no import errors**

Run: `python -c "from simulation.monte_carlo import run_monte_carlo; from simulation.props_edge import analyze_all_props; from scrapers.player_stats import get_batter_stats; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 3: Verify edge.py handles both dict and OddsData**

Run: `python -c "from edge import analyze_all_edges; print(analyze_all_edges({}, {}))"`
Expected: `[]` (empty list, no crash)

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete market expansion — 17 new markets (7 game-level + 10 props)"
```
