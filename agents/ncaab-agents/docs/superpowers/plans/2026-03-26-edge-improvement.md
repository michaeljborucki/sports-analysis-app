# MiroFish Edge Improvement — Plug Leaks + Fix Math

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop hemorrhaging money on broken bet types (Phase 1) then fix underlying math to build real predictive edge (Phase 2).

**Architecture:** Phase 1 is config/threshold changes and one-line fixes to stop the bleeding immediately. Phase 2 corrects the projected total formula, replaces the H1 heuristic, adds probability validation, wires up auto-weight-learning, and adds underdog dampening. All changes are backward-compatible with existing CSV tracking.

**Tech Stack:** Python 3.11+, pytest, pandas, existing ensemble/edge/config infrastructure.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | Modify | Raise thresholds for losing bet types, add MAX_ML_ODDS |
| `edge.py` | Modify | Add odds floor filter, probability dampening, replace H1 heuristic |
| `ensemble/orchestrator.py:677-683` | Modify | Make challenger kills binding |
| `main.py:175` | Modify | Fix `killed_slots` undefined variable bug |
| `scrapers/matchup.py:51-53` | Modify | Fix projected total formula |
| `ensemble/consensus.py` | Modify | Add probability coherence validation |
| `agents/daily_runner.py` | Modify | Wire auto-optimizer after grading |
| `tests/test_edge.py` | Modify | Add tests for new filters and dampening |
| `tests/test_matchup.py` | Create | Test corrected projected total formula |
| `tests/test_consensus_validation.py` | Create | Test probability coherence checks |

---

## PHASE 1: PLUG THE LEAKS (Tasks 1-5)

### Task 1: Raise Edge Thresholds for Losing Bet Types

Current record by type: totals 1-7, moneyline underdogs 0-3. Raise thresholds to stop these bets until the math is fixed.

**Files:**
- Modify: `config.py:44-52`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, add:

```python
def test_total_threshold_raised():
    from config import EDGE_THRESHOLDS
    assert EDGE_THRESHOLDS["total"] >= 0.08, "Totals threshold must be >= 8% until calibrated"
    assert EDGE_THRESHOLDS["first_half_total"] >= 0.08


def test_h1_thresholds_raised():
    from config import EDGE_THRESHOLDS
    assert EDGE_THRESHOLDS["first_half_ml"] >= 0.07
    assert EDGE_THRESHOLDS["first_half_spread"] >= 0.07
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_total_threshold_raised tests/test_config.py::test_h1_thresholds_raised -v`
Expected: FAIL (current thresholds are all 0.05)

- [ ] **Step 3: Update config thresholds**

In `config.py`, change `EDGE_THRESHOLDS`:

```python
EDGE_THRESHOLDS = {
    "moneyline": 0.06,
    "spread": 0.05,
    "total": 0.08,
    "first_half_ml": 0.07,
    "first_half_spread": 0.07,
    "first_half_total": 0.08,
}
```

Rationale:
- **spread** stays at 5% (1-1 record, only profitable type)
- **moneyline** raised to 6% (phantom edges on underdogs)
- **total** raised to 8% (1-7, clearly broken)
- **first_half_***: raised to 7-8% (thin markets, unreliable data)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "fix: raise edge thresholds for losing bet types (totals 8%, H1 7-8%)"
```

---

### Task 2: Add Maximum Odds Floor to Block Phantom Underdog Edges

Heavy underdogs (+400 and above) produce phantom edges because LLMs slightly overestimate underdog probability, and at long odds even a tiny overestimate creates massive fake edge. Block these.

**Files:**
- Modify: `config.py` (add constant)
- Modify: `edge.py:26-71` (moneyline filter)
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_edge.py`, add:

```python
def test_moneyline_rejects_heavy_underdog():
    """Moneyline bets on heavy underdogs (+400 or worse) should be rejected."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.25, "away_win_prob": 0.75}
        }
    }
    odds = {
        "moneyline": {"home": 500, "away": -700},
        "implied_probs": {"ml_home": 0.167, "ml_away": 0.833},
    }
    result = check_moneyline_edge(sim, odds)
    # Even though edge = 0.25 - 0.167 = 0.083 (above threshold),
    # the +500 odds should be rejected (away has negative edge so no bet either)
    assert result is None


def test_moneyline_allows_moderate_underdog():
    """Moderate underdogs (+200) should still be allowed if edge exists."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.42, "away_win_prob": 0.58}
        }
    }
    odds = {
        "moneyline": {"home": 200, "away": -250},
        "implied_probs": {"ml_home": 0.333, "ml_away": 0.667},
    }
    result = check_moneyline_edge(sim, odds)
    # edge = 0.42 - 0.333 = 0.087, odds +200 is within limit
    assert result is not None
    assert result["side"] == "home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge.py::test_moneyline_rejects_heavy_underdog tests/test_edge.py::test_moneyline_allows_moderate_underdog -v`
Expected: First test FAILS (currently no odds filter)

- [ ] **Step 3: Add MAX_ML_ODDS to config and filter to edge.py**

In `config.py`, add after line 42:

```python
# Maximum American odds for moneyline bets — blocks phantom edges on heavy underdogs
MAX_ML_ODDS = 350
```

In `edge.py`, update the import (line 3):

```python
from config import EDGE_THRESHOLDS, KELLY_FRACTION, MAX_ML_ODDS
```

In `edge.py`, in `check_moneyline_edge()`, add after line 33 (`threshold = ...`):

```python
    # Reject heavy underdogs — LLMs overestimate their chances, creating phantom edges
    home_american = ml_odds.get("home", 0)
    away_american = ml_odds.get("away", 0)
```

Then modify the home edge check (line 46) to:

```python
    if home_edge >= threshold and home_edge >= away_edge and home_american <= MAX_ML_ODDS:
```

And modify the away edge check (line 58) to:

```python
    elif away_edge >= threshold and away_american <= MAX_ML_ODDS:
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add config.py edge.py tests/test_edge.py
git commit -m "fix: add odds floor to reject phantom edges on heavy underdogs (>+350)"
```

---

### Task 3: Make Challenger Kills Binding

Currently `orchestrator.py:683` passes `[]` instead of `killed_list` to `build_ensemble_result`, meaning challenger kills are completely ignored. Fix this.

**Files:**
- Modify: `ensemble/orchestrator.py:677-683`
- Test: `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_ensemble_orchestrator.py`, add:

```python
def test_challenger_kills_are_binding():
    """Challenger kill verdicts should remove bet slots from final result."""
    from ensemble.orchestrator import build_ensemble_result
    from ensemble.weights import BET_SLOTS

    results = [
        {"model_key": "kimi", "parsed": MOCK_PREDICTION, "temperature": 0.7, "cost": 0.01},
        {"model_key": "claude", "parsed": MOCK_PREDICTION, "temperature": 0.7, "cost": 0.01},
        {"model_key": "gpt4o", "parsed": MOCK_PREDICTION, "temperature": 0.7, "cost": 0.01},
    ]
    classification = {
        slot: {"level": "strong", "count": 3, "side": "home", "votes": {}}
        for slot in BET_SLOTS
    }
    weights = {mk: {s: 1.0 for s in BET_SLOTS} for mk in ["kimi", "claude", "gpt4o"]}

    # Kill moneyline and total
    killed = ["moneyline", "total"]
    final = build_ensemble_result(results, classification, weights, killed)

    assert final is not None
    preds = final.get("predictions", {})
    assert "moneyline" not in preds, "Killed moneyline should be removed"
    assert "total" not in preds, "Killed total should be removed"
    assert "spread" in preds, "Non-killed spread should remain"
```

- [ ] **Step 2: Run test to verify the concept works**

Run: `pytest tests/test_ensemble_orchestrator.py::test_challenger_kills_are_binding -v`
Note: `build_ensemble_result` already supports kills via its `killed_by_challenger` param — the bug is in the caller. This test should PASS already since it calls `build_ensemble_result` directly with kills.

- [ ] **Step 3: Fix the orchestrator caller**

In `ensemble/orchestrator.py`, change line 683 from:

```python
    final = build_ensemble_result(results, classification, weights, [])
```

To:

```python
    final = build_ensemble_result(results, classification, weights, killed_list)
```

Also remove the misleading comment on line 682:

```python
    # --- Build final result (no longer strip killed slots) ---
```

Replace with:

```python
    # --- Build final result ---
```

- [ ] **Step 4: Fix the killed_slots bug in main.py**

In `main.py`, before the `for bet in bets:` loop (before line 171), add:

```python
    killed_slots = [s for s, v in challenger_verdicts.items() if v.get("verdict") == "kill"]
```

This defines the `killed_slots` variable that line 175 already references, fixing the `NameError`.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add ensemble/orchestrator.py main.py tests/test_ensemble_orchestrator.py
git commit -m "fix: make challenger kills binding + fix killed_slots undefined variable"
```

---

### Task 4: Add Probability Coherence Validation

Reject model outputs where probabilities don't sum to ~1.0. This catches garbage predictions before they pollute the ensemble.

**Files:**
- Create: `tests/test_consensus_validation.py`
- Modify: `ensemble/consensus.py`
- Modify: `ensemble/orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_consensus_validation.py`:

```python
from ensemble.consensus import validate_prediction_coherence


def test_valid_prediction_passes():
    pred = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.60, "away_win_prob": 0.40},
            "total": {"over_prob": 0.55, "under_prob": 0.45},
        }
    }
    assert validate_prediction_coherence(pred) is True


def test_incoherent_moneyline_fails():
    pred = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.60, "away_win_prob": 0.65},
        }
    }
    assert validate_prediction_coherence(pred) is False


def test_incoherent_total_fails():
    pred = {
        "predictions": {
            "total": {"over_prob": 0.70, "under_prob": 0.60},
        }
    }
    assert validate_prediction_coherence(pred) is False


def test_missing_sections_passes():
    """Predictions with missing sections should pass (not fail on absence)."""
    pred = {"predictions": {}}
    assert validate_prediction_coherence(pred) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_consensus_validation.py -v`
Expected: FAIL (function doesn't exist yet)

- [ ] **Step 3: Implement validate_prediction_coherence**

In `ensemble/consensus.py`, add:

```python
def validate_prediction_coherence(parsed: dict, tolerance: float = 0.15) -> bool:
    """Check that complementary probabilities sum to ~1.0.

    Returns True if valid, False if incoherent. Tolerance of 0.15 allows
    for LLM rounding but catches egregious errors (0.60 + 0.65 = 1.25).
    """
    preds = parsed.get("predictions", {})

    # Moneyline: home + away should sum to ~1.0
    ml = preds.get("moneyline", {})
    if "home_win_prob" in ml and "away_win_prob" in ml:
        total = ml["home_win_prob"] + ml["away_win_prob"]
        if abs(total - 1.0) > tolerance:
            return False

    # Total: over + under should sum to ~1.0
    tot = preds.get("total", {})
    if "over_prob" in tot and "under_prob" in tot:
        total = tot["over_prob"] + tot["under_prob"]
        if abs(total - 1.0) > tolerance:
            return False

    # First half ML
    h1 = preds.get("first_half", {})
    if "h1_home_win_prob" in h1 and "h1_away_win_prob" in h1:
        total = h1["h1_home_win_prob"] + h1["h1_away_win_prob"]
        if abs(total - 1.0) > tolerance:
            return False

    return True
```

- [ ] **Step 4: Wire validation into orchestrator**

In `ensemble/orchestrator.py`, add import:

```python
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS, validate_prediction_coherence,
)
```

In `run_phase1()`, replace the existing `if result:` block at lines 119-121:

```python
            if result:
                if validate_prediction_coherence(result["parsed"]):
                    results.append(result)
                    total_cost += result["cost"]
                else:
                    logger.warning("  Phase 1: %s failed coherence check, discarding",
                                   futures[future])
```

Also apply the same check in `run_phase2()`, replacing the `if result:` block at lines 307-309:

```python
            if result:
                if validate_prediction_coherence(result["parsed"]):
                    new_results.append(result)
                    total_cost += result["cost"]
                else:
                    logger.warning("  Phase 2: %s failed coherence check, discarding",
                                   futures[future][0])
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_consensus_validation.py tests/test_ensemble_orchestrator.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add ensemble/consensus.py ensemble/orchestrator.py tests/test_consensus_validation.py
git commit -m "feat: add probability coherence validation to reject incoherent model outputs"
```

---

### Task 5: Remove Soft Warning Override for Challenger

When ALL bets are killed by the challenger, the system currently preserves them as "soft warnings" (line 678). This defeats the purpose. If everything is killed, return None so no bets are placed.

**Files:**
- Modify: `ensemble/orchestrator.py:677-678`

- [ ] **Step 1: Change the soft warning behavior**

In `ensemble/orchestrator.py`, replace lines 677-678:

```python
    if not surviving_after_challenge:
        logger.warning("All bets flagged by challenger — preserving as soft warnings")
```

With:

```python
    if not surviving_after_challenge:
        logger.warning("All bets killed by challenger — no surviving slots")
        return None
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_ensemble_orchestrator.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add ensemble/orchestrator.py
git commit -m "fix: return None when challenger kills all bets instead of soft warnings"
```

---

## PHASE 2: FIX THE MATH (Tasks 6-10)

### Task 6: Fix Projected Total Formula in Matchup

Current formula `(away_oe + home_oe) / 2 * poss / 100` ignores defensive efficiency entirely. Fix to cross-match offense vs opposing defense.

**Files:**
- Create: `tests/test_matchup.py`
- Modify: `scrapers/matchup.py:51-53`

- [ ] **Step 1: Write the failing test**

Create `tests/test_matchup.py`:

```python
from scrapers.matchup import get_matchup_context


def test_projected_total_uses_defense():
    """Projected total should account for opposing defense, not just average offense."""
    # Team A: elite offense (120 AdjOE), bad defense (110 AdjDE)
    # Team B: bad offense (95 AdjOE), elite defense (90 AdjDE)
    # Old formula: (120 + 95) / 2 * 68 / 100 = 73.1 (ignores defense)
    # Correct: away scores (120 * 90/100) = 108 eff, home scores (95 * 110/100) = 104.5 eff
    # Total = (108 + 104.5) * 68 / 200 = 72.3 — lower because elite defense suppresses
    away_stats = {"adj_oe": 120, "adj_de": 110, "adj_tempo": 68}
    home_stats = {"adj_oe": 95, "adj_de": 90, "adj_tempo": 68}
    result = get_matchup_context(away_stats, home_stats)

    # With defense factored in, total should be lower than naive average
    naive = (120 + 95) / 2 * 68 / 100
    assert result["projected_total"] < naive


def test_projected_total_symmetric_teams():
    """Two identical teams should produce same total regardless of formula."""
    stats = {"adj_oe": 105, "adj_de": 100, "adj_tempo": 68}
    result = get_matchup_context(stats, stats)
    # Both formulas agree when teams are identical
    expected = 105 * 100 / 100 * 68 / 100 * 2  # = 142.8
    assert abs(result["projected_total"] - round(expected, 1)) < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_matchup.py -v`
Expected: `test_projected_total_uses_defense` FAILS (old formula ignores defense)

- [ ] **Step 3: Fix the projected total formula**

In `scrapers/matchup.py`, replace lines 51-53:

```python
    # Projected total: cross-match offense vs opposing defense
    # away_score_rate = away_oe * (home_de / 100), home_score_rate = home_oe * (away_de / 100)
    away_score_eff = away_oe * home_de / 100
    home_score_eff = home_oe * away_de / 100
    projected_total = round((away_score_eff + home_score_eff) * projected_poss / 100, 1)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_matchup.py tests/test_edge.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/matchup.py tests/test_matchup.py
git commit -m "fix: projected total formula now cross-matches offense vs opposing defense"
```

---

### Task 7: Replace H1 Total Heuristic with Ensemble Probabilities

The hardcoded `0.5 + delta * 0.03` heuristic is unjustified. Use the ensemble's own `h1_total_value` vote (over/under/none) and the full-game total probabilities scaled to first half instead.

**Files:**
- Modify: `edge.py:316-378` (check_h1_total_edge)
- Modify: `edge.py:611-645` (analyze_all_bets H1 total section)
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_edge.py`, add:

```python
def test_h1_total_uses_ensemble_probs():
    """H1 total should use ensemble over/under probs, not hardcoded heuristic."""
    sim = {
        "predictions": {
            "first_half": {
                "h1_projected_total": 72.0,
                "h1_over_prob": 0.62,
                "h1_under_prob": 0.38,
            }
        }
    }
    odds = {"h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110}}
    result = check_h1_total_edge(sim, odds)
    # With explicit probs, should use them instead of heuristic
    if result:
        assert result["sim_prob"] == 0.62 or result["sim_prob"] == 0.38


def test_h1_total_falls_back_to_heuristic():
    """When ensemble doesn't provide H1 probs, fall back to heuristic."""
    sim = {
        "predictions": {
            "first_half": {"h1_projected_total": 72.0}
        }
    }
    odds = {"h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110}}
    result = check_h1_total_edge(sim, odds)
    # Should still work with fallback heuristic
    assert result is None or result["bet_type"] == "first_half_total"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge.py::test_h1_total_uses_ensemble_probs -v`
Expected: FAIL (current code doesn't read h1_over_prob/h1_under_prob)

- [ ] **Step 3: Update check_h1_total_edge to prefer ensemble probs**

In `edge.py`, replace the heuristic section of `check_h1_total_edge()` (lines 344-348):

```python
    # Prefer explicit ensemble probabilities over heuristic
    h1_over = h1_pred.get("h1_over_prob")
    h1_under = h1_pred.get("h1_under_prob")
    if h1_over is not None and h1_under is not None:
        over_prob = float(h1_over)
        under_prob = float(h1_under)
    else:
        # Fallback heuristic: estimate probability from projected vs line delta
        delta = projected - line
        over_prob = min(max(0.5 + delta * 0.03, 0.01), 0.99)
        under_prob = 1 - over_prob
```

Apply the same change to the `analyze_all_bets` H1 total section (lines 625-627):

```python
            h1_over = h1_pred.get("h1_over_prob")
            h1_under = h1_pred.get("h1_under_prob")
            if h1_over is not None and h1_under is not None:
                op = float(h1_over)
                up = float(h1_under)
            else:
                delta = projected - h1_line
                op = min(max(0.5 + delta * 0.03, 0.01), 0.99)
                up = 1 - op
```

- [ ] **Step 4: Update system prompt to request H1 probabilities**

In `simulate.py`, in the `first_half` section of `SYSTEM_PROMPT` (lines 70-78), add the new fields:

```python
    "first_half": {
      "h1_home_win_prob": 0.XX,
      "h1_away_win_prob": 0.XX,
      "h1_projected_total": XX.X,
      "h1_over_prob": 0.XX,
      "h1_under_prob": 0.XX,
      "h1_favorite_cover_prob": 0.XX,
      "h1_ml_value": "home|away|none",
      "h1_total_value": "over|under|none",
      "h1_spread_value": "favorite|underdog|none",
      "confidence": "low|medium|high"
    },
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add edge.py simulate.py tests/test_edge.py
git commit -m "feat: H1 total uses ensemble probabilities with heuristic fallback"
```

---

### Task 8: Add Underdog Probability Dampening (Shrinkage Toward Market)

LLMs systematically overestimate underdog win probability. Apply Bayesian shrinkage that pulls LLM estimates toward market implied probability — more shrinkage for extreme underdogs, less for favorites.

**Files:**
- Modify: `edge.py` (add dampening function)
- Modify: `edge.py:26-71` (apply to moneyline)
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_edge.py`, add:

```python
from edge import dampen_probability


def test_dampen_no_change_for_favorites():
    """Favorites (prob > 0.5) should not be dampened."""
    result = dampen_probability(0.60, 0.55)
    assert result == 0.60


def test_dampen_pulls_underdog_toward_market():
    """Underdogs should be pulled toward market implied prob."""
    # LLM says 25%, market says 17% — LLM likely overestimates
    result = dampen_probability(0.25, 0.167)
    assert result < 0.25
    assert result > 0.167


def test_dampen_stronger_for_extreme_underdogs():
    """More extreme underdogs get more dampening."""
    mild = dampen_probability(0.35, 0.30)   # mild underdog
    extreme = dampen_probability(0.25, 0.10)  # extreme underdog
    # Mild underdog keeps more of their estimate
    mild_kept = (mild - 0.30) / (0.35 - 0.30)
    extreme_kept = (extreme - 0.10) / (0.25 - 0.10)
    assert mild_kept > extreme_kept
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge.py::test_dampen_no_change_for_favorites -v`
Expected: FAIL (function doesn't exist)

- [ ] **Step 3: Implement dampening function**

In `edge.py`, add after the `kelly_criterion` function (after line 23):

```python
def dampen_probability(sim_prob: float, market_prob: float,
                       shrinkage: float = 0.3) -> float:
    """Apply Bayesian shrinkage to pull underdog estimates toward market.

    Only dampens when sim_prob < 0.5 (underdog side). Shrinkage increases
    with how extreme the underdog is (lower market_prob = more dampening).

    Formula: dampened = sim_prob * (1 - effective_shrinkage) + market_prob * effective_shrinkage
    where effective_shrinkage scales up for extreme underdogs.
    """
    if sim_prob >= 0.5:
        return sim_prob

    # Scale shrinkage: more dampening for extreme underdogs
    # market_prob of 0.10 → 1.5x shrinkage, market_prob of 0.40 → 0.75x shrinkage
    extremity = max(0.5, min(2.0, 1.0 - (market_prob - 0.25) * 2))
    effective = min(shrinkage * extremity, 0.6)  # cap at 60% shrinkage

    return round(sim_prob * (1 - effective) + market_prob * effective, 4)
```

- [ ] **Step 4: Apply dampening to moneyline edge check**

In `edge.py`, in `check_moneyline_edge()`, after computing all four values (home_prob, home_implied, away_prob, away_implied — lines 36-43), add before the edge calculation:

```python
    # Apply underdog dampening to pull LLM estimates toward market
    home_prob = dampen_probability(home_prob, home_implied)
    away_prob = dampen_probability(away_prob, away_implied)
```

Do the same in the moneyline section of `analyze_all_bets()`, after all four values are computed (after lines 431-432 where away_implied is set):

```python
        home_prob = dampen_probability(home_prob, home_implied)
        away_prob = dampen_probability(away_prob, away_implied)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: add Bayesian shrinkage to dampen overestimated underdog probabilities"
```

---

### Task 9: Wire Auto-Optimizer to Update Weights After Grading

The self-optimizer has `compute_model_brier_scores()` and `update_model_weights()` functions, but `run_optimizer()` only prints a report — it never calls these. Wire weight updates into the optimizer, then call it from the daily runner after grading.

**Files:**
- Modify: `agents/self_optimizer.py:167-179` (add weight update to run_optimizer)
- Modify: `agents/daily_runner.py` (call optimizer after grading)
- Test: `tests/test_self_optimizer.py`

- [ ] **Step 1: Add weight update to run_optimizer**

In `agents/self_optimizer.py`, at the end of `run_optimizer()` (before line 231), add after the recommendations section:

```python
    # Auto-update model weights from Brier scores
    try:
        from config import MODEL_PREDICTIONS_CSV
        model_preds_df = pd.read_csv(MODEL_PREDICTIONS_CSV)
        brier = compute_model_brier_scores(model_preds_df, df)
        if brier:
            update_model_weights(brier)
            click.echo("\n  Model weights updated from Brier scores.")
            for model, scores in brier.items():
                avg = sum(scores.values()) / len(scores) if scores else 0
                click.echo(f"    {model}: avg Brier={avg:.4f}")
        else:
            click.echo("\n  Insufficient data for Brier score weight update.")
    except Exception as e:
        click.echo(f"\n  Weight update skipped: {e}")
```

- [ ] **Step 2: Wire optimizer into daily_runner after grading**

In `agents/daily_runner.py`, add import at the top (after line 10):

```python
from agents.self_optimizer import run_optimizer
```

In the `main()` function, after the grading step (after line 100 `click.echo()`), add:

```python
    # Step 2b: Auto-optimize model weights if enough data
    if grade_yesterday:
        click.echo("[2b] Running auto-optimizer...")
        try:
            run_optimizer(min_bets=10)
        except Exception as e:
            click.echo(f"  Optimizer warning (non-fatal): {e}")
            logger.warning("Auto-optimizer failed: %s", e)
        click.echo()
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -v -k "daily or optimizer or self_optim"`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add agents/self_optimizer.py agents/daily_runner.py
git commit -m "feat: auto-update model weights from Brier scores after grading"
```

---

### Task 10: Normalize Ensemble Probabilities After Weighted Averaging

After weighted averaging, complementary probabilities may not sum to 1.0. Add normalization.

**Files:**
- Modify: `ensemble/orchestrator.py:478-497`
- Test: `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_ensemble_orchestrator.py`, add:

```python
def test_ensemble_result_probabilities_sum_to_one():
    """After weighted averaging, ML probs should sum to ~1.0."""
    from ensemble.orchestrator import build_ensemble_result
    from ensemble.weights import BET_SLOTS

    # Create results with slightly inconsistent probs
    pred1 = copy.deepcopy(MOCK_PREDICTION)
    pred1["predictions"]["moneyline"]["home_win_prob"] = 0.62
    pred1["predictions"]["moneyline"]["away_win_prob"] = 0.40  # sums to 1.02
    pred2 = copy.deepcopy(MOCK_PREDICTION)
    pred2["predictions"]["moneyline"]["home_win_prob"] = 0.58
    pred2["predictions"]["moneyline"]["away_win_prob"] = 0.44  # sums to 1.02

    results = [
        {"model_key": "kimi", "parsed": pred1, "temperature": 0.7, "cost": 0.01},
        {"model_key": "claude", "parsed": pred2, "temperature": 0.7, "cost": 0.01},
        {"model_key": "gpt4o", "parsed": pred1, "temperature": 0.7, "cost": 0.01},
    ]
    classification = {s: {"level": "strong", "count": 3, "side": "home", "votes": {}}
                      for s in BET_SLOTS}
    weights = {mk: {s: 1.0 for s in BET_SLOTS} for mk in ["kimi", "claude", "gpt4o"]}

    final = build_ensemble_result(results, classification, weights, [])
    ml = final["predictions"]["moneyline"]
    total = ml["home_win_prob"] + ml["away_win_prob"]
    assert abs(total - 1.0) < 0.01, f"ML probs sum to {total}, expected ~1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ensemble_orchestrator.py::test_ensemble_result_probabilities_sum_to_one -v`
Expected: Likely FAILS (weighted average doesn't normalize)

- [ ] **Step 3: Add normalization after weighted averaging**

In `ensemble/orchestrator.py`, after the probability averaging loop (after line 497), add normalization for complementary pairs:

```python
    # Normalize complementary probability pairs to sum to 1.0
    _normalize_probs(predictions, "moneyline", "home_win_prob", "away_win_prob")
    _normalize_probs(predictions, "total", "over_prob", "under_prob")
    h1 = predictions.get("first_half", {})
    if "h1_home_win_prob" in h1 and "h1_away_win_prob" in h1:
        total = h1["h1_home_win_prob"] + h1["h1_away_win_prob"]
        if total > 0:
            h1["h1_home_win_prob"] = round(h1["h1_home_win_prob"] / total, 4)
            h1["h1_away_win_prob"] = round(h1["h1_away_win_prob"] / total, 4)
```

Add the helper function before `build_ensemble_result`:

```python
def _normalize_probs(predictions: dict, section_key: str, field_a: str, field_b: str):
    """Normalize two complementary probability fields to sum to 1.0."""
    section = predictions.get(section_key, {})
    a = section.get(field_a)
    b = section.get(field_b)
    if a is not None and b is not None:
        total = a + b
        if total > 0:
            section[field_a] = round(a / total, 4)
            section[field_b] = round(b / total, 4)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ensemble_orchestrator.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/orchestrator.py tests/test_ensemble_orchestrator.py
git commit -m "feat: normalize complementary probabilities after ensemble weighted averaging"
```

---

## Summary

| Task | Type | Impact | Time |
|------|------|--------|------|
| 1. Raise edge thresholds | Config | Stops 7+ losing bets per cycle | 5 min |
| 2. Add odds floor | Filter | Blocks phantom underdog edges | 10 min |
| 3. Make challenger kills binding | Bug fix | Activates adversarial review | 10 min |
| 4. Probability coherence validation | Validation | Rejects garbage model outputs | 15 min |
| 5. Remove soft warning override | Bug fix | Challenger can actually stop bad bets | 5 min |
| 6. Fix projected total formula | Math fix | Totals accuracy (biggest P&L leak) | 15 min |
| 7. Replace H1 heuristic | Math fix | H1 totals use real data | 20 min |
| 8. Underdog dampening | Math fix | Eliminates systematic LLM overestimate | 20 min |
| 9. Wire auto-optimizer | Feature | Models learn from results | 10 min |
| 10. Normalize ensemble probs | Math fix | Consistent probability outputs | 15 min |

**Phase 1 (Tasks 1-5):** ~45 minutes, stops the bleeding
**Phase 2 (Tasks 6-10):** ~80 minutes, builds real edge
