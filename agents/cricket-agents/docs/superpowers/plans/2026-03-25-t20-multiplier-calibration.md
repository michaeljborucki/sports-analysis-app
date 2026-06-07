# T20 Multiplier Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the odds-implied-probability edge detection with a projected-value-vs-line framework using three calibrated engines (linear, exponential, Poisson) across 15 T20 cricket bet types.

**Architecture:** Three probability engines — linear for normal-ish stats, exponential CDF for right-skewed stats (player runs), Poisson CDF for discrete low-mean counts (wickets, sixes) — all producing identical `(side, projected, probability, edge)` output. Edge detection is decoupled from odds; Kelly sizing remains as an optional post-edge step when odds are available.

**Tech Stack:** Python 3.11+, scipy (new dependency), pytest, pandas

**Spec:** `docs/superpowers/specs/2026-03-25-t20-multiplier-calibration-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | Modify | Add `BET_TYPES` dict, `ACTIVE_TIERS`, `PREDICTION_KEY_MAP`. Replace `EDGE_THRESHOLDS` and `BET_SLOTS` |
| `edge.py` | Rewrite | Three engines + dispatcher. Keep `american_to_decimal()` and `kelly_criterion()` |
| `simulate.py` | Modify | Expand `SYSTEM_PROMPT` for 15 bet types. Update `_average_results()` |
| `tracker.py` | Modify | Add `projected` and `tier` columns to CSV schema |
| `tests/test_edge.py` | Rewrite | Full test coverage for three engines + dispatcher |
| `tests/test_config_validation.py` | Create | Config consistency checks |
| `tests/test_config.py` | Modify | Update BET_SLOTS assertion for 15 types |
| `tests/test_simulate.py` | Modify | Update assertions for new prediction keys |
| `tests/ensemble_fixtures.py` | Modify | Expand mock prediction to include all 15 bet types |
| `requirements.txt` | Modify | Add `scipy>=1.11.0` |

### Key Design Decision: `total_runs` Naming

The LLM system prompt and ensemble layer continue to use `total_runs` as the
prediction key. The new `BET_TYPES` config uses the canonical name `match_total_runs`.
A `PREDICTION_KEY_MAP` in `config.py` maps from prediction keys to BET_TYPES keys:

```python
PREDICTION_KEY_MAP = {"total_runs": "match_total_runs"}
```

This avoids cascading changes through `ensemble/*.py`, `main.py`, `briefing.py`,
and `agents/results_grader.py`. The `analyze_all_edges` function in `edge.py`
applies this mapping when looking up predictions.

---

### Task 1: Add scipy dependency and BET_TYPES config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py:41-48`
- Create: `tests/test_config_validation.py`

- [ ] **Step 1: Add scipy to requirements.txt**

Add `scipy>=1.11.0` to `requirements.txt` after the `pandas` line.

- [ ] **Step 2: Install the updated dependencies**

Run: `pip install -r requirements.txt`
Expected: scipy installs successfully

- [ ] **Step 3: Write config validation test**

Create `tests/test_config_validation.py`:

```python
from config import BET_TYPES, ACTIVE_TIERS


def test_bet_types_has_15_entries():
    assert len(BET_TYPES) == 15


def test_all_linear_multipliers_match_std_dev():
    for key, cfg in BET_TYPES.items():
        if cfg["engine"] == "linear":
            expected = round(1 / (2 * cfg["std_dev"]), 3)
            assert abs(cfg["multiplier"] - expected) < 0.001, (
                f"{key}: multiplier {cfg['multiplier']} != 1/(2*{cfg['std_dev']}) = {expected}"
            )


def test_all_bet_types_have_required_fields():
    for key, cfg in BET_TYPES.items():
        assert "engine" in cfg, f"{key} missing engine"
        assert "threshold" in cfg, f"{key} missing threshold"
        assert "tier" in cfg, f"{key} missing tier"
        if cfg["engine"] == "linear":
            assert "std_dev" in cfg, f"{key} (linear) missing std_dev"
            assert "multiplier" in cfg, f"{key} (linear) missing multiplier"


def test_active_tiers_valid():
    assert all(t in [1, 2, 3, 4] for t in ACTIVE_TIERS)


def test_tier_thresholds():
    """Tier 1 = 0.06, Tier 2 = 0.05, Tier 3 = 0.04, Tier 4 = 0.05."""
    tier_thresholds = {1: 0.06, 2: 0.05, 3: 0.04, 4: 0.05}
    for key, cfg in BET_TYPES.items():
        expected = tier_thresholds[cfg["tier"]]
        assert cfg["threshold"] == expected, (
            f"{key}: threshold {cfg['threshold']} != expected {expected} for tier {cfg['tier']}"
        )
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_config_validation.py -v`
Expected: FAIL — `BET_TYPES` not yet defined in config.py

- [ ] **Step 5: Add BET_TYPES and ACTIVE_TIERS to config.py**

Replace the existing `EDGE_THRESHOLDS` and `BET_SLOTS` block (lines 41-48 in `config.py`) with:

```python
# Bet type configuration — engines, multipliers, thresholds
BET_TYPES = {
    # Tier 1 — Core Markets (6% threshold)
    "moneyline": {
        "engine": "direct",
        "threshold": 0.06,
        "tier": 1,
    },
    "match_total_runs": {
        "engine": "linear",
        "std_dev": 60,
        "multiplier": 0.008,
        "threshold": 0.06,
        "tier": 1,
    },
    "team_total_runs": {
        "engine": "linear",
        "std_dev": 30,
        "multiplier": 0.017,
        "threshold": 0.06,
        "tier": 1,
    },
    "spread": {
        "engine": "linear",
        "std_dev": 20,
        "multiplier": 0.025,
        "threshold": 0.06,
        "tier": 1,
    },
    # Tier 2 — Player Props (5% threshold)
    "player_runs": {
        "engine": "exponential",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_wickets": {
        "engine": "poisson",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_boundaries": {
        "engine": "poisson",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_sixes": {
        "engine": "poisson",
        "threshold": 0.05,
        "tier": 2,
    },
    # Tier 3 — Phase & Specialty (4% threshold)
    "powerplay_runs": {
        "engine": "linear",
        "std_dev": 16,
        "multiplier": 0.031,
        "threshold": 0.04,
        "tier": 3,
    },
    "match_total_sixes": {
        "engine": "linear",
        "std_dev": 6,
        "multiplier": 0.083,
        "threshold": 0.04,
        "tier": 3,
    },
    "match_total_fours": {
        "engine": "linear",
        "std_dev": 6,
        "multiplier": 0.083,
        "threshold": 0.04,
        "tier": 3,
    },
    "first_over_runs": {
        "engine": "linear",
        "std_dev": 4,
        "multiplier": 0.125,
        "threshold": 0.04,
        "tier": 3,
    },
    "fall_of_first_wicket": {
        "engine": "exponential",
        "threshold": 0.04,
        "tier": 3,
    },
    # Tier 4 — Bowling Props (5% threshold)
    "runs_conceded": {
        "engine": "linear",
        "std_dev": 11,
        "multiplier": 0.045,
        "threshold": 0.05,
        "tier": 4,
    },
    "dot_balls": {
        "engine": "linear",
        "std_dev": 3.5,
        "multiplier": 0.143,
        "threshold": 0.05,
        "tier": 4,
    },
}

ACTIVE_TIERS = [1, 2, 3, 4]

# Maps LLM prediction keys to BET_TYPES keys (where they differ)
PREDICTION_KEY_MAP = {"total_runs": "match_total_runs"}

# Legacy aliases for backward compatibility during migration
EDGE_THRESHOLDS = {k: v["threshold"] for k, v in BET_TYPES.items()}
BET_SLOTS = list(BET_TYPES.keys())
```

- [ ] **Step 6: Run config validation tests**

Run: `python -m pytest tests/test_config_validation.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Run existing tests to check nothing breaks**

Run: `python -m pytest tests/ -v --timeout=10`
Expected: All existing tests still pass (EDGE_THRESHOLDS and BET_SLOTS aliases preserve compatibility)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt config.py tests/test_config_validation.py
git commit -m "feat: add BET_TYPES config with 15 bet types and scipy dependency"
```

---

### Task 2: Implement three edge detection engines (TDD)

**Files:**
- Rewrite: `edge.py`
- Rewrite: `tests/test_edge.py`

- [ ] **Step 1: Write failing tests for the linear engine**

Replace the contents of `tests/test_edge.py` with:

```python
import math
import pytest
from edge import (
    calculate_linear_edge,
    calculate_exponential_edge,
    calculate_poisson_edge,
    american_to_decimal,
    kelly_criterion,
    analyze_all_edges,
)


# === Linear Engine Tests ===

def test_linear_over_edge():
    """Projected above line → over side."""
    side, proj, prob, edge = calculate_linear_edge(
        projected=350, line=340, multiplier=0.008
    )
    assert side == "over"
    assert proj == 350
    assert prob == pytest.approx(0.58, abs=0.01)
    assert edge == pytest.approx(0.08, abs=0.01)


def test_linear_under_edge():
    """Projected below line → under side."""
    side, proj, prob, edge = calculate_linear_edge(
        projected=330, line=340, multiplier=0.008
    )
    assert side == "under"
    assert prob == pytest.approx(0.58, abs=0.01)
    assert edge == pytest.approx(0.08, abs=0.01)


def test_linear_no_edge():
    """Projected equals line → edge is 0."""
    side, proj, prob, edge = calculate_linear_edge(
        projected=340, line=340, multiplier=0.008
    )
    assert edge == pytest.approx(0.0, abs=0.001)
    assert prob == pytest.approx(0.50, abs=0.01)


def test_linear_clamps_high():
    """Extreme delta clamps probability at 0.99."""
    side, proj, prob, edge = calculate_linear_edge(
        projected=500, line=340, multiplier=0.008
    )
    assert prob == 0.99
    assert edge == pytest.approx(0.49, abs=0.01)


def test_linear_clamps_low():
    """Extreme negative delta still picks under with clamped prob."""
    side, proj, prob, edge = calculate_linear_edge(
        projected=200, line=340, multiplier=0.008
    )
    assert side == "under"
    assert prob == 0.99
    assert edge == pytest.approx(0.49, abs=0.01)


def test_linear_edge_always_non_negative():
    """Property: edge is always >= 0."""
    for delta in range(-100, 101, 5):
        _, _, _, edge = calculate_linear_edge(
            projected=340 + delta, line=340, multiplier=0.008
        )
        assert edge >= 0


def test_linear_prob_in_range():
    """Property: probability always in [0.01, 0.99]."""
    for delta in range(-200, 201, 10):
        _, _, prob, _ = calculate_linear_edge(
            projected=340 + delta, line=340, multiplier=0.008
        )
        assert 0.01 <= prob <= 0.99


# === Exponential Engine Tests ===

def test_exponential_under_when_projected_above_line():
    """Key behavior: projected=30, line=25 → under is favorable (median < mean)."""
    side, proj, prob, edge = calculate_exponential_edge(
        projected_mean=30, line=25
    )
    assert side == "under"
    assert prob == pytest.approx(0.566, abs=0.01)
    assert edge == pytest.approx(0.066, abs=0.01)


def test_exponential_over_when_line_very_low():
    """Line well below median → over is favorable."""
    side, proj, prob, edge = calculate_exponential_edge(
        projected_mean=30, line=10
    )
    assert side == "over"
    prob_over = math.exp(-10 / 30)
    assert prob == pytest.approx(prob_over, abs=0.01)


def test_exponential_under_when_line_high():
    """Line above mean → under is favorable."""
    side, proj, prob, edge = calculate_exponential_edge(
        projected_mean=25, line=35
    )
    assert side == "under"
    prob_under = 1 - math.exp(-35 / 25)
    assert prob == pytest.approx(prob_under, abs=0.01)


def test_exponential_at_median():
    """At the median (mean * ln2), prob_over = 0.50 exactly."""
    mean = 30
    median = mean * math.log(2)
    side, _, prob, edge = calculate_exponential_edge(
        projected_mean=mean, line=median
    )
    assert prob == pytest.approx(0.50, abs=0.001)
    assert edge == pytest.approx(0.0, abs=0.001)


def test_exponential_edge_always_non_negative():
    for line in range(5, 60, 5):
        _, _, _, edge = calculate_exponential_edge(projected_mean=30, line=line)
        assert edge >= 0


# === Poisson Engine Tests ===

def test_poisson_over_wickets():
    """Projected mean 1.8, line 1.5 → over side."""
    side, proj, prob, edge = calculate_poisson_edge(
        projected_mean=1.8, line=1.5
    )
    assert side == "over"
    # P(X >= 2 | mu=1.8) = 1 - P(X <= 1) = 1 - poisson.cdf(1, 1.8)
    assert prob > 0.50
    assert edge > 0


def test_poisson_under_wickets():
    """Projected mean 0.8, line 1.5 → under side."""
    side, proj, prob, edge = calculate_poisson_edge(
        projected_mean=0.8, line=1.5
    )
    assert side == "under"
    assert prob > 0.50


def test_poisson_sanity_check_wickets():
    """P(over 0.5 | mean=1.1) should be ~0.667."""
    side, _, prob, edge = calculate_poisson_edge(
        projected_mean=1.1, line=0.5
    )
    assert side == "over"
    assert prob == pytest.approx(0.667, abs=0.01)
    assert edge == pytest.approx(0.167, abs=0.01)


def test_poisson_edge_always_non_negative():
    for mu in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
        for line in [0.5, 1.5, 2.5, 3.5]:
            _, _, _, edge = calculate_poisson_edge(projected_mean=mu, line=line)
            assert edge >= 0


# === Kelly & Conversion (preserved) ===

def test_kelly_criterion_positive_edge():
    kelly = kelly_criterion(0.55, 2.0)
    assert 0.05 < kelly < 0.15


def test_kelly_criterion_no_edge():
    kelly = kelly_criterion(0.50, 2.0)
    assert kelly == 0


def test_kelly_criterion_negative_edge():
    kelly = kelly_criterion(0.40, 2.0)
    assert kelly == 0


def test_american_to_decimal():
    assert american_to_decimal(-150) == round(100 / 150 + 1, 4)
    assert american_to_decimal(130) == round(130 / 100 + 1, 4)
    assert american_to_decimal(100) == 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_edge.py -v`
Expected: ImportError — `calculate_linear_edge` etc. not found

- [ ] **Step 3: Implement the three engines in edge.py**

Rewrite `edge.py`:

```python
"""Edge detection engines and Kelly criterion sizing for T20 cricket."""
import logging
import math
from scipy.stats import poisson as poisson_dist
from config import BET_TYPES, ACTIVE_TIERS, KELLY_FRACTION, PREDICTION_KEY_MAP

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


def calculate_linear_edge(
    projected: float, line: float, multiplier: float
) -> tuple[str, float, float, float]:
    """Linear multiplier engine for near-normal distributions.

    Returns (side, projected, probability, edge).
    """
    delta = projected - line
    prob_over = max(0.01, min(0.99, 0.50 + delta * multiplier))
    prob_under = 1.0 - prob_over
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(prob - 0.50, 4)
    return side, projected, round(prob, 4), edge


def calculate_exponential_edge(
    projected_mean: float, line: float
) -> tuple[str, float, float, float]:
    """Exponential CDF engine for right-skewed stats (mean ~ std_dev).

    Returns (side, projected_mean, probability, edge).
    """
    if projected_mean <= 0:
        return "under", projected_mean, 0.99, 0.49
    prob_over = math.exp(-line / projected_mean)
    prob_under = 1.0 - prob_over
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(prob - 0.50, 4)
    return side, projected_mean, round(prob, 4), edge


def calculate_poisson_edge(
    projected_mean: float, line: float
) -> tuple[str, float, float, float]:
    """Poisson CDF engine for discrete count stats (mean < 5).

    Returns (side, projected_mean, probability, edge).
    """
    if projected_mean <= 0:
        return "under", projected_mean, 0.99, 0.49
    k = math.floor(line)
    prob_over = 1.0 - poisson_dist.cdf(k, mu=projected_mean)
    prob_under = poisson_dist.cdf(k, mu=projected_mean)
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(prob - 0.50, 4)
    return side, projected_mean, round(prob, 4), edge


def detect_edge(
    bet_type: str, projected: float, line: float, odds: int | None = None
) -> dict | None:
    """Detect edge for a single bet type.

    Args:
        bet_type: Key from BET_TYPES config.
        projected: Ensemble's projected value for this stat.
        line: The betting line to compare against.
        odds: American odds (optional, for Kelly sizing).

    Returns dict with bet details if edge exceeds threshold, else None.
    """
    cfg = BET_TYPES.get(bet_type)
    if not cfg:
        return None
    if cfg["tier"] not in ACTIVE_TIERS:
        return None

    engine = cfg["engine"]
    threshold = cfg["threshold"]

    if engine == "linear":
        side, proj, prob, edge = calculate_linear_edge(
            projected, line, cfg["multiplier"]
        )
    elif engine == "exponential":
        side, proj, prob, edge = calculate_exponential_edge(projected, line)
    elif engine == "poisson":
        side, proj, prob, edge = calculate_poisson_edge(projected, line)
    else:
        return None

    if edge < threshold:
        return None

    result = {
        "bet_type": bet_type,
        "side": f"{side} {line}",
        "projected": proj,
        "probability": prob,
        "edge": edge,
        "tier": cfg["tier"],
    }

    if odds is not None:
        dec = american_to_decimal(odds)
        result["odds"] = odds
        result["kelly_pct"] = round(
            kelly_criterion(prob, dec) * KELLY_FRACTION, 4
        )

    return result


def check_moneyline_edge(
    team_a_prob: float, team_b_prob: float,
    team_a_odds: int | None = None, team_b_odds: int | None = None
) -> dict | None:
    """Check moneyline edge for both teams. Returns best side if any."""
    threshold = BET_TYPES["moneyline"]["threshold"]

    best = None
    for team, prob, odds in [
        ("team_a", team_a_prob, team_a_odds),
        ("team_b", team_b_prob, team_b_odds),
    ]:
        edge = round(prob - 0.50, 4)
        if edge >= threshold:
            result = {
                "bet_type": "moneyline",
                "side": team,
                "projected": prob,
                "probability": prob,
                "edge": edge,
                "tier": 1,
            }
            if odds is not None:
                dec = american_to_decimal(odds)
                result["odds"] = odds
                result["kelly_pct"] = round(
                    kelly_criterion(prob, dec) * KELLY_FRACTION, 4
                )
            if best is None or edge > best["edge"]:
                best = result

    return best


def analyze_all_edges(predictions: dict, odds: dict) -> list[dict]:
    """Run edge detection across all available bet types.

    Args:
        predictions: Ensemble output with projected values per bet type.
        odds: Market odds/lines per bet type.

    Returns list of bets that exceed their thresholds.
    """
    edges = []
    preds = predictions.get("predictions", {})

    # Moneyline
    ml = preds.get("moneyline", {})
    if ml:
        ml_odds = odds.get("moneyline", {})
        result = check_moneyline_edge(
            ml.get("team_a_win_prob", 0),
            ml.get("team_b_win_prob", 0),
            ml_odds.get("team_a"),
            ml_odds.get("team_b"),
        )
        if result:
            edges.append(result)

    # Build reverse map: prediction key -> bet_type key
    reverse_map = {v: k for k, v in PREDICTION_KEY_MAP.items()}

    # All other bet types — need a projected value and a line
    for bet_type, cfg in BET_TYPES.items():
        if bet_type == "moneyline":
            continue
        # Check both the canonical key and any legacy prediction key
        pred_key = reverse_map.get(bet_type, bet_type)
        pred = preds.get(bet_type, {}) or preds.get(pred_key, {})
        odds_data = odds.get(bet_type, {}) or odds.get(pred_key, {})
        projected = pred.get("projected")
        line = odds_data.get("line")
        if projected is None or line is None:
            continue
        bet_odds = odds_data.get("odds")
        result = detect_edge(bet_type, projected, line, bet_odds)
        if result:
            edges.append(result)

    return edges
```

- [ ] **Step 4: Run edge engine tests**

Run: `python -m pytest tests/test_edge.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run all tests to check compatibility**

Run: `python -m pytest tests/ -v --timeout=10`
Expected: Most tests pass. Some existing tests that import old functions from `edge.py` may need attention — check and note failures.

- [ ] **Step 6: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: implement three edge detection engines (linear, exponential, Poisson)"
```

---

### Task 3: Add dispatcher and integration tests

**Files:**
- Modify: `tests/test_edge.py` (append)

- [ ] **Step 1: Add detect_edge and analyze_all_edges tests**

Append to `tests/test_edge.py`:

```python
# === detect_edge dispatcher ===

def test_detect_edge_linear_above_threshold():
    result = detect_edge("match_total_runs", projected=360, line=340)
    assert result is not None
    assert result["bet_type"] == "match_total_runs"
    assert result["side"].startswith("over")
    assert result["edge"] >= 0.06


def test_detect_edge_linear_below_threshold():
    result = detect_edge("match_total_runs", projected=342, line=340)
    assert result is None  # edge ~0.016, below 0.06


def test_detect_edge_exponential():
    # projected=30, line=15 → over is strong
    result = detect_edge("player_runs", projected=30, line=15)
    assert result is not None
    assert result["bet_type"] == "player_runs"


def test_detect_edge_poisson():
    result = detect_edge("player_wickets", projected=2.0, line=1.5)
    assert result is not None
    assert result["side"].startswith("over")


def test_detect_edge_with_odds():
    result = detect_edge("match_total_runs", projected=360, line=340, odds=-110)
    assert result is not None
    assert "kelly_pct" in result
    assert result["kelly_pct"] > 0


def test_detect_edge_without_odds():
    result = detect_edge("match_total_runs", projected=360, line=340)
    assert result is not None
    assert "kelly_pct" not in result


def test_detect_edge_unknown_type():
    result = detect_edge("nonexistent_type", projected=100, line=90)
    assert result is None


# === check_moneyline_edge ===

def test_moneyline_edge_team_a():
    result = check_moneyline_edge(0.68, 0.32, team_a_odds=-130)
    assert result is not None
    assert result["side"] == "team_a"
    assert result["edge"] >= 0.06


def test_moneyline_edge_no_edge():
    result = check_moneyline_edge(0.53, 0.47)
    assert result is None  # 3% edge, below 6% threshold


def test_moneyline_edge_with_kelly():
    result = check_moneyline_edge(0.68, 0.32, team_a_odds=-130)
    assert result is not None
    assert "kelly_pct" in result


# === analyze_all_edges ===

def test_analyze_all_edges_basic():
    predictions = {
        "predictions": {
            "moneyline": {
                "team_a_win_prob": 0.68,
                "team_b_win_prob": 0.32,
            },
            "total_runs": {"projected": 360},  # LLM uses "total_runs" key
        }
    }
    odds = {
        "moneyline": {"team_a": -130, "team_b": 110},
        "total_runs": {"line": 340, "odds": -110},  # mapped to match_total_runs
    }
    bets = analyze_all_edges(predictions, odds)
    assert isinstance(bets, list)
    assert len(bets) >= 1
    types = [b["bet_type"] for b in bets]
    assert "moneyline" in types


def test_analyze_all_edges_empty():
    bets = analyze_all_edges({"predictions": {}}, {})
    assert bets == []
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_edge.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_edge.py
git commit -m "test: add dispatcher and integration tests for edge detection"
```

---

### Task 4: Update tracker.py for new schema

**Files:**
- Modify: `tracker.py:6-9`
- Modify: `tests/test_tracker.py` (if exists, verify compatibility)

- [ ] **Step 1: Read current tracker tests**

Run: `python -m pytest tests/test_tracker.py -v 2>/dev/null || echo "no tracker tests"`
Check what tests exist for tracker.

- [ ] **Step 2: Update COLUMNS in tracker.py**

Change the `COLUMNS` list in `tracker.py` line 6-9 from:

```python
COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "edge", "kelly_pct", "result", "profit",
]
```

To:

```python
COLUMNS = [
    "date", "game", "bet_type", "side", "projected", "odds",
    "sim_prob", "edge", "kelly_pct", "tier", "result", "profit",
]
```

- [ ] **Step 3: Run tracker tests**

Run: `python -m pytest tests/test_tracker.py -v`
Expected: PASS (log_bet uses `bet.get(col, "")` so missing keys default to empty)

- [ ] **Step 4: Commit**

```bash
git add tracker.py
git commit -m "feat: add projected and tier columns to tracker CSV schema"
```

---

### Task 5: Update simulate.py system prompt and averaging

**Files:**
- Modify: `simulate.py:11-65` (SYSTEM_PROMPT)
- Modify: `simulate.py:168-193` (_average_results)

- [ ] **Step 1: Update SYSTEM_PROMPT to request all bet type projections**

Replace the JSON schema portion of `SYSTEM_PROMPT` in `simulate.py` (lines 28-64) — the part starting with `"Respond in valid JSON only"` — with:

```python
SYSTEM_PROMPT = """You are an elite T20 cricket prediction system analyzing a match.
Simulate a panel of 6 expert analysts:

1. PITCH & CONDITIONS ANALYST (MOST IMPORTANT): Evaluates pitch type (batting/bowling/neutral),
   surface hardness, expected bounce and turn, dew factor (especially for night matches),
   weather impact, and how conditions will shift between innings.
2. BATTING ANALYST: Evaluates team batting depth, powerplay form, middle-over acceleration,
   death-overs hitting, strike rates, and match-up advantages vs the opposing attack.
3. BOWLING ANALYST: Evaluates bowling attack quality, powerplay wicket-taking ability,
   spin effectiveness in conditions, death-over specialists, and economy rates.
4. TOSS & CHASE ANALYST: Evaluates historical bat-first vs chase win rates at this venue,
   dew impact on second-innings chasing, and likely toss decision advantage.
5. MARKET ANALYST: Evaluates the betting lines for value. Where is public money flowing?
   Where might the market be inefficient given team form or conditions?
6. CONTRARIAN: Challenges the consensus. What obvious narrative might be wrong?
   Where is the value on the unpopular side?

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
      "projected": XXX.X,
      "confidence": "low|medium|high"
    },
    "team_total_runs": {
      "projected": XXX.X,
      "confidence": "low|medium|high"
    },
    "spread": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "player_runs": [
      {"player": "Name", "projected": XX.X}
    ],
    "player_wickets": [
      {"player": "Name", "projected": X.X}
    ],
    "player_boundaries": [
      {"player": "Name", "projected": X.X}
    ],
    "player_sixes": [
      {"player": "Name", "projected": X.X}
    ],
    "powerplay_runs": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "match_total_sixes": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "match_total_fours": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "first_over_runs": {
      "projected": X.X,
      "confidence": "low|medium|high"
    },
    "fall_of_first_wicket": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "runs_conceded": [
      {"player": "Name", "projected": XX.X}
    ],
    "dot_balls": [
      {"player": "Name", "projected": X.X}
    ],
    "predicted_result": {
      "winner": "TEAM",
      "winning_margin": "X wickets|X runs",
      "projected_scores": {
        "batting_first": XXX,
        "chasing": XXX
      }
    },
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""
```

- [ ] **Step 2: Update _average_results to handle all bet types**

Replace the `_average_results` function in `simulate.py` with:

```python
def _average_results(results: list[dict]) -> dict:
    """Average projected values across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)
    preds = base.get("predictions", {})

    # Scalar bet types — average the "projected" field
    # Note: uses "total_runs" (LLM output key), not "match_total_runs" (BET_TYPES key)
    scalar_types = [
        "total_runs", "team_total_runs", "spread",
        "powerplay_runs", "match_total_sixes", "match_total_fours",
        "first_over_runs", "fall_of_first_wicket",
    ]
    for bet_type in scalar_types:
        values = []
        for r in results:
            val = r.get("predictions", {}).get(bet_type, {}).get("projected")
            if val is not None:
                values.append(float(val))
        if values and bet_type in preds:
            preds[bet_type]["projected"] = round(sum(values) / len(values), 1)

    # Moneyline — average probabilities
    ml_fields = ["team_a_win_prob", "team_b_win_prob", "edge"]
    for field in ml_fields:
        values = []
        for r in results:
            val = r.get("predictions", {}).get("moneyline", {}).get(field)
            if val is not None:
                values.append(float(val))
        if values and "moneyline" in preds:
            preds["moneyline"][field] = round(sum(values) / len(values), 4)

    # List bet types (player props) — average per player name
    list_types = [
        "player_runs", "player_wickets", "player_boundaries",
        "player_sixes", "runs_conceded", "dot_balls",
    ]
    for bet_type in list_types:
        player_values = {}
        for r in results:
            entries = r.get("predictions", {}).get(bet_type, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                name = entry.get("player", "")
                val = entry.get("projected")
                if name and val is not None:
                    player_values.setdefault(name, []).append(float(val))
        if player_values and bet_type in preds:
            preds[bet_type] = [
                {"player": name, "projected": round(sum(vals) / len(vals), 1)}
                for name, vals in player_values.items()
            ]

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
```

- [ ] **Step 3: Run simulate tests**

Run: `python -m pytest tests/test_simulate.py -v`
Expected: PASS (tests check for SYSTEM_PROMPT content and JSON parsing)

- [ ] **Step 4: Commit**

```bash
git add simulate.py
git commit -m "feat: expand system prompt and averaging for 15 bet types"
```

---

### Task 6: Update ensemble fixtures and run full test suite

**Files:**
- Modify: `tests/ensemble_fixtures.py`

- [ ] **Step 1: Update MOCK_PREDICTION with new bet types**

Update `tests/ensemble_fixtures.py` to include the expanded prediction schema:

```python
"""Shared mock data for ensemble tests."""
import json
import copy

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "pitch_conditions", "pick": "MI", "reasoning": "Batting pitch favours MI"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.58,
            "team_b_win_prob": 0.42,
            "value_side": "team_a",
            "edge": 0.06,
            "confidence": "medium",
        },
        "total_runs": {
            "projected": 340.5,
            "confidence": "medium",
        },
        "team_total_runs": {
            "projected": 172.0,
            "confidence": "medium",
        },
        "spread": {
            "projected": 12.5,
            "confidence": "medium",
        },
        "player_runs": [
            {"player": "Rohit Sharma", "projected": 32.5},
        ],
        "player_wickets": [
            {"player": "Jasprit Bumrah", "projected": 1.4},
        ],
        "player_boundaries": [
            {"player": "Rohit Sharma", "projected": 4.2},
        ],
        "player_sixes": [
            {"player": "Rohit Sharma", "projected": 1.8},
        ],
        "powerplay_runs": {
            "projected": 52.0,
            "confidence": "medium",
        },
        "match_total_sixes": {
            "projected": 14.5,
            "confidence": "medium",
        },
        "match_total_fours": {
            "projected": 27.0,
            "confidence": "medium",
        },
        "first_over_runs": {
            "projected": 6.5,
            "confidence": "medium",
        },
        "fall_of_first_wicket": {
            "projected": 28.0,
            "confidence": "medium",
        },
        "runs_conceded": [
            {"player": "Jasprit Bumrah", "projected": 28.0},
        ],
        "dot_balls": [
            {"player": "Jasprit Bumrah", "projected": 10.5},
        ],
        "predicted_result": {
            "winner": "MI",
            "winning_margin": "5 wickets",
            "projected_scores": {
                "batting_first": 178,
                "chasing": 179,
            },
        },
        "key_factors": ["batting pitch", "dew factor", "MI powerplay dominance"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"team_a": -130, "team_b": 110},
    "total_runs": {"line": 340.5, "odds": -110},
    "team_total_runs": {"line": 170.5, "odds": -110},
    "spread": {"line": 10.5, "odds": -110},
    "player_runs": [{"player": "Rohit Sharma", "line": 29.5, "odds": -115}],
    "player_wickets": [{"player": "Jasprit Bumrah", "line": 1.5, "odds": -110}],
    "player_boundaries": [{"player": "Rohit Sharma", "line": 3.5, "odds": -110}],
    "player_sixes": [{"player": "Rohit Sharma", "line": 1.5, "odds": +110}],
    "powerplay_runs": {"line": 50.5, "odds": -110},
    "match_total_sixes": {"line": 13.5, "odds": -110},
    "match_total_fours": {"line": 26.5, "odds": -110},
    "first_over_runs": {"line": 6.5, "odds": -110},
    "fall_of_first_wicket": {"line": 25.5, "odds": -110},
    "runs_conceded": [{"player": "Jasprit Bumrah", "line": 30.5, "odds": -110}],
    "dot_balls": [{"player": "Jasprit Bumrah", "line": 9.5, "odds": -110}],
    "implied_probs": {"team_a": 0.565, "team_b": 0.435},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            if isinstance(pred["predictions"][key], dict):
                pred["predictions"][key].update(val)
            else:
                pred["predictions"][key] = val
    return pred
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS. Note any failures and fix.

- [ ] **Step 3: Commit**

```bash
git add tests/ensemble_fixtures.py
git commit -m "feat: expand mock fixtures for 15 bet types"
```

---

### Task 7: Fix existing tests broken by config changes

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_simulate.py`

- [ ] **Step 1: Run full test suite and identify failures**

Run: `python -m pytest tests/ -v --timeout=30 2>&1 | grep -E "(FAIL|ERROR)"`
Expected: Failures in `test_config.py` (BET_SLOTS assertion) and `test_simulate.py` (total_runs/projected_total assertions)

- [ ] **Step 2: Fix test_config.py**

Update the `BET_SLOTS` assertion in `tests/test_config.py`. Change:

```python
assert BET_SLOTS == ["moneyline", "total_runs"]
```

To:

```python
assert len(BET_SLOTS) == 15
assert "moneyline" in BET_SLOTS
assert "match_total_runs" in BET_SLOTS
```

- [ ] **Step 3: Fix test_simulate.py**

Update assertions that reference `"total_runs"` and `"projected_total"`. The system prompt still uses `"total_runs"` as the prediction key (not `"match_total_runs"`), so assertions checking for `"total_runs" in SYSTEM_PROMPT` should still pass. Update any assertion checking for `"projected_total"` to check for `"projected"` instead.

- [ ] **Step 4: Run test suite to confirm fixes**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_config.py tests/test_simulate.py
git commit -m "test: fix assertions for expanded BET_TYPES config"
```

---

### Task 8: Verify end-to-end and clean up

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite one final time**

Run: `python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Verify config imports work across codebase**

Run: `python -c "from config import BET_TYPES, ACTIVE_TIERS, EDGE_THRESHOLDS, BET_SLOTS; print(f'{len(BET_TYPES)} bet types, {len(BET_SLOTS)} slots, {len(EDGE_THRESHOLDS)} thresholds')"`
Expected: `15 bet types, 15 slots, 15 thresholds`

- [ ] **Step 3: Verify edge module imports**

Run: `python -c "from edge import calculate_linear_edge, calculate_exponential_edge, calculate_poisson_edge, detect_edge, check_moneyline_edge, analyze_all_edges; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 4: Quick smoke test of edge detection**

Run: `python -c "
from edge import detect_edge
r = detect_edge('match_total_runs', 360, 340)
print(f'Linear: {r}')
r = detect_edge('player_runs', 30, 15)
print(f'Exponential: {r}')
r = detect_edge('player_wickets', 2.0, 1.5)
print(f'Poisson: {r}')
"`
Expected: Three non-None results with correct sides and edges

- [ ] **Step 5: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final cleanup for multiplier calibration"
```
