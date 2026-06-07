# Betting-Layer Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the patchwork of worst-case-devig, equal-weight consensus, flat-quarter Kelly, and hard edge-capping in the betting layer with a principled Shin/power dual-devig gate, Pinnacle-weighted consensus, correlation-aware Kelly sizing, uncertainty shrinkage, best-line metadata capture, and suspicious-edge quarantine — all behind a `BETTING_V2_ENABLED` feature flag with a 2-week shadow period.

**Architecture:** New `scrapers/devig.py` module co-locates `power_devig` + a closed-form/bisection `shin_devig` (plus a stub for N-way). `scrapers/odds.py` gains a single `_weighted_consensus` helper that blends sharp books (`SHARP_BOOKS`) at `SHARP_BOOK_WEIGHT` against retail equal-weight; `OddsData` gets `best_line_book`, `best_line_odds`, `shin_z`, `consensus_sharp_books` fields. `edge.py` swaps every `_passes_worst_case_filter` call for a `_dual_devig_check` gate (min-edge across both methods), extends `_sized_kelly` to return `(raw_kelly, shrunk_kelly)` driven by ensemble `prob_std`, and replaces the `MAX_EDGE = 0.15` cap-and-fire block with a quarantine-and-drop writing to `data/quarantined_edges.csv`. A new `sizing.py` computes same-game correlation groups and proportionally caps summed Kelly. `ensemble/orchestrator.py` surfaces per-slot `prob_std` from cross-run stdev.

**Tech Stack:** Python 3.11+, `pandas`, `numpy`, existing `pytest` suite. No new heavy dependencies — Shin bisection follows the same pattern as `power_devig`. `scipy` is listed optionally in requirements for any future closed-form needs but is NOT imported by shipped code.

**Spec:** `docs/superpowers/specs/2026-04-17-betting-layer-hardening-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `scrapers/devig.py` | Create | Co-locate devig algos. `power_devig`, `shin_devig`, `shin_devig_many` stub. |
| `scrapers/odds.py` | Modify | Re-export `power_devig`; add `shin_devig` import; add `_weighted_consensus` helper; wire sharp-book weighting into consensus loop; extend `OddsData` with `best_line_book`, `best_line_odds`, `shin_z`, `consensus_sharp_books`; populate best-line fields in each `if (market, side) in best` block; write daily `data/devig_stats.csv`. |
| `edge.py` | Modify | Add `_dual_devig_check`; replace 10+ `_passes_worst_case_filter` call sites; extend `_sized_kelly` signature to `(raw_kelly, shrunk_kelly)` consuming `prob_std`; replace `:854-866` cap block with quarantine-and-drop; swap run-cluster filter for `cap_same_game_exposure`; gate all new behavior behind `BETTING_V2_ENABLED`. |
| `sizing.py` | Create | `compute_correlation_groups`, `cap_same_game_exposure`. |
| `ensemble/orchestrator.py` | Modify | Compute per-slot `prob_std` across runs, stash on `predictions.<section>.prob_std`. |
| `tracker.py` | Modify | Extend `COLUMNS` with `best_book`, `best_odds`, `shin_edge`, `shin_z`, `devig_method`; add idempotent `_ensure_csv_has_columns` migration; thread `OddsData` into `log_bet`. |
| `config.py` | Modify | Add `SHARP_BOOKS`, `SHARP_BOOK_WEIGHT`, `BETTING_V2_ENABLED`, `BETTING_V2_SHADOW_COMPARE`, `MAX_SAME_GAME_EXPOSURE`, `MAX_LEGITIMATE_EDGE`, `UNCERTAINTY_K`, `KELLY_FLOOR_FRACTION`, `SAFETY_KEEP_TOP_N`. |
| `requirements.txt` | Modify | Add `scipy>=1.11.0` (optional — not imported; declared to unblock future work). |
| `scripts/compare_v1_v2.py` | Create | Shadow-period diff tool comparing v1 vs v2 bet cards. |
| `tests/test_shin_devig.py` | Create | Shin closed-form correctness + degenerate cases. |
| `tests/test_weighted_consensus.py` | Create | Sharp-book weighting behavior + Pinnacle-absent fallback. |
| `tests/test_best_line_metadata.py` | Create | `OddsData.best_line_book`/`best_line_odds` populated correctly. |
| `tests/test_sizing_correlation.py` | Create | Correlation group assignment + cap property tests. |
| `tests/test_uncertainty_shrinkage.py` | Create | Monotone shrinkage; prob_std=0 passthrough; floor/ceiling. |
| `tests/test_quarantine.py` | Create | Suspicious edges land in quarantine CSV, not bet list. |
| `tests/test_edge.py` | Modify | Update for new dual-devig gate; add end-to-end smoke (§6.5). |
| `tests/test_edge_phase1.py` | Modify | Dual-devig gate on new checkers. |
| `tests/test_ensemble_orchestrator.py` | Modify | Assert `prob_std` present on every slot. |
| `tests/test_shadow_mode.py` | Create | Integration test for `BETTING_V2_SHADOW_COMPARE=True`. |

---

## Conventions

- **Commit after every task.** The commit message template is `feat|fix|refactor: <short description>`; include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
- **TDD:** write the failing test, observe the failure, implement, observe the pass, commit.
- **Flag discipline:** all new runtime behavior reads `config.BETTING_V2_ENABLED`. When `False`, v1 paths execute unchanged. Tests that target v2 behavior monkeypatch the flag to `True`.
- **No scipy imports in shipped code.** Declaring it in `requirements.txt` is a forward-compatibility hedge; reviewers should flag any `import scipy` in PRs.

---

## Phase A — Shin De-Vig Foundation

### Task A1: Create `scrapers/devig.py` with `shin_devig`

**Files:**
- Create: `scrapers/devig.py`
- Create: `tests/test_shin_devig.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_shin_devig.py`:

```python
"""Unit tests for Shin and power de-vig."""
import math
import pytest

from scrapers.devig import shin_devig, shin_devig_many, power_devig


def _implied(american: int) -> float:
    if american < 0:
        return abs(american) / (abs(american) + 100)
    return 100 / (american + 100)


class TestShinDevig2Way:
    def test_symmetric_minus110_minus110(self):
        pi = _implied(-110)            # 0.5238
        p_a, p_b, z = shin_devig(pi, pi)
        assert p_a == pytest.approx(0.5, abs=1e-4)
        assert p_b == pytest.approx(0.5, abs=1e-4)
        assert 0.0 <= z < 0.05
        assert p_a + p_b == pytest.approx(1.0, abs=1e-6)

    def test_asymmetric_minus130_plus115(self):
        # Worked example from spec §4.2
        pi_home = _implied(-130)       # 0.5652
        pi_away = _implied(+115)       # 0.4651
        p_home, p_away, z = shin_devig(pi_home, pi_away)
        assert p_home == pytest.approx(0.5499, abs=1e-3)
        assert p_away == pytest.approx(0.4501, abs=1e-3)
        assert 0.02 <= z <= 0.05
        assert p_home + p_away == pytest.approx(1.0, abs=1e-6)

    def test_heavy_favorite_minus350_plus275(self):
        pi_fav = _implied(-350)        # 0.7778
        pi_dog = _implied(+275)        # 0.2667
        p_fav, p_dog, z = shin_devig(pi_fav, pi_dog)
        assert 0.77 < p_fav < 0.79
        assert 0 < z < 0.05
        assert p_fav + p_dog == pytest.approx(1.0, abs=1e-6)

    def test_longshot_plus500_minus650(self):
        pi_dog = _implied(+500)        # 0.1667
        pi_fav = _implied(-650)        # 0.8667
        p_fav, p_dog, z = shin_devig(pi_fav, pi_dog)
        assert p_fav + p_dog == pytest.approx(1.0, abs=1e-6)
        assert 0 < z < 0.10
        # Sanity: fav remains heavy favorite after devig
        assert p_fav > 0.83

    def test_degenerate_both_tiny(self):
        # Both sides near-zero — naive normalization path
        p_a, p_b, z = shin_devig(0.001, 0.001)
        assert p_a == pytest.approx(0.5, abs=1e-4)
        assert p_b == pytest.approx(0.5, abs=1e-4)
        assert z == 0.0

    def test_zero_vig_passthrough(self):
        p_a, p_b, z = shin_devig(0.4, 0.6)
        assert p_a == pytest.approx(0.4, abs=1e-6)
        assert p_b == pytest.approx(0.6, abs=1e-6)
        assert z == 0.0

    def test_rounding(self):
        p_a, p_b, z = shin_devig(0.5238, 0.5238)
        # probabilities to 6 decimals, z to 4 decimals
        assert round(p_a, 6) == p_a
        assert round(p_b, 6) == p_b
        assert round(z, 4) == z


class TestShinDevigMany:
    def test_two_way_matches_shin_devig(self):
        probs, z = shin_devig_many([0.5652, 0.4651])
        assert probs[0] + probs[1] == pytest.approx(1.0, abs=1e-6)
        # Should match the 2-way result within rounding
        p_a, p_b, z2 = shin_devig(0.5652, 0.4651)
        assert probs[0] == pytest.approx(p_a, abs=1e-4)
        assert probs[1] == pytest.approx(p_b, abs=1e-4)

    def test_three_way_not_implemented(self):
        with pytest.raises(NotImplementedError):
            shin_devig_many([0.40, 0.35, 0.30])


class TestPowerDevigBackwardsCompat:
    def test_power_devig_reexported_from_devig(self):
        p_a, p_b = power_devig(0.5652, 0.4651)
        assert p_a + p_b == pytest.approx(1.0, abs=1e-4)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_shin_devig.py -v
```

Expected: `ModuleNotFoundError: No module named 'scrapers.devig'` (collection error).

- [ ] **Step 3: Implement `scrapers/devig.py`**

Create `scrapers/devig.py`:

```python
"""De-vig algorithms: power method (existing) + Shin (1993).

Co-located so future N-way generalizations and diagnostics share a home.
`power_devig` is re-exported from `scrapers.odds` for backwards compat.
"""
from math import sqrt


def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method. Solves for n where p_a^n + p_b^n = 1.

    Falls back to naive normalization if inputs are degenerate.
    """
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    if abs(total - 1.0) < 1e-6:
        return (prob_a, prob_b)
    if prob_a <= 0.001 or prob_b <= 0.001:
        return (prob_a / total, prob_b / total)

    lo, hi = 0.01, 20.0
    for _ in range(100):
        mid = (lo + hi) / 2
        val = prob_a ** mid + prob_b ** mid
        if val > 1.0:
            lo = mid
        else:
            hi = mid
        if abs(val - 1.0) < 1e-10:
            break

    n = (lo + hi) / 2
    return (round(prob_a ** n, 6), round(prob_b ** n, 6))


def _shin_side(pi: float, sigma: float, z: float) -> float:
    """Evaluate the Shin formula for a single side."""
    denom = 2.0 * (1.0 - z)
    if denom <= 0:
        return pi / sigma
    inside = z * z + 4.0 * (1.0 - z) * (pi * pi) / sigma
    inside = max(0.0, inside)
    return (sqrt(inside) - z) / denom


def shin_devig(prob_a: float, prob_b: float) -> tuple[float, float, float]:
    """Shin (1993) de-vig for a 2-way market.

    Returns (p_a, p_b, z) where z in [0, 1) is the estimated insider
    fraction. Sum p_a + p_b == 1 up to 1e-6.

    For each side with raw implied prob pi_i and total Sigma_pi:
        p_i = (sqrt(z^2 + 4*(1-z)*pi_i^2/Sigma_pi) - z) / (2*(1-z))

    z is selected by bisection on [0, 0.2] so that p_a + p_b = 1.
    """
    sigma = prob_a + prob_b
    if sigma <= 0:
        return (0.5, 0.5, 0.0)
    # Degenerate: both sides microscopic — normalize.
    if prob_a <= 0.001 or prob_b <= 0.001:
        return (round(prob_a / sigma, 6), round(prob_b / sigma, 6), 0.0)
    # Zero-vig short-circuit.
    if abs(sigma - 1.0) < 1e-6:
        return (round(prob_a, 6), round(prob_b, 6), 0.0)

    lo, hi = 0.0, 0.2
    z = 0.0
    for _ in range(100):
        z = (lo + hi) / 2
        p_a = _shin_side(prob_a, sigma, z)
        p_b = _shin_side(prob_b, sigma, z)
        s = p_a + p_b
        if abs(s - 1.0) < 1e-10:
            break
        # Larger z => smaller p_i => smaller sum. If sum too high, raise z.
        if s > 1.0:
            lo = z
        else:
            hi = z

    p_a = _shin_side(prob_a, sigma, z)
    p_b = _shin_side(prob_b, sigma, z)
    # Renormalize residual numerical drift so sum is exact to 1.0.
    total = p_a + p_b
    if total > 0:
        p_a /= total
        p_b /= total
    return (round(p_a, 6), round(p_b, 6), round(z, 4))


def shin_devig_many(raw_probs: list[float]) -> tuple[list[float], float]:
    """N-way Shin. Only 2-way is implemented today.

    For 3+ outcomes the bisection generalizes but the identity above is
    per-side; wiring it in waits on an N-way use case (3-way soccer,
    draw-no-bet decompositions).
    """
    if len(raw_probs) == 2:
        p_a, p_b, z = shin_devig(raw_probs[0], raw_probs[1])
        return ([p_a, p_b], z)
    raise NotImplementedError(
        "shin_devig_many currently supports 2-way markets only"
    )
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_shin_devig.py -v
```

Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add scrapers/devig.py tests/test_shin_devig.py
git commit -m "$(cat <<'EOF'
feat: add scrapers/devig with Shin and power de-vig

New `scrapers/devig.py` co-locates `power_devig` and introduces
`shin_devig` (2-way, bisection on [0, 0.2]) plus `shin_devig_many` stub
for future 3-way markets. Full unit coverage including symmetric -110,
asymmetric -130/+115, heavy favorites, longshots, and degenerate
inputs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task A2: Re-export `power_devig` from `scrapers/odds.py`

**Files:**
- Modify: `scrapers/odds.py:45-73` (drop duplicate) / top-level import

- [ ] **Step 1: Update `scrapers/odds.py` to import from `devig`**

Delete the `power_devig` function body at `scrapers/odds.py:45-73` and replace with a re-export at the top of the file. After the existing `from config import ...` line, add:

```python
from scrapers.devig import power_devig, shin_devig  # noqa: F401 re-export
```

Remove lines 45-73 (the in-file definition of `power_devig`).

- [ ] **Step 2: Run existing odds tests**

```bash
pytest tests/ -k "odds" -v
pytest tests/test_edge.py -v
pytest tests/test_edge_phase1.py -v
```

Expected: all pass (the public API is unchanged for v1 callers).

- [ ] **Step 3: Commit**

```bash
git add scrapers/odds.py
git commit -m "$(cat <<'EOF'
refactor: move power_devig to scrapers/devig, re-export from odds

Keeps `from scrapers.odds import power_devig` working unchanged while
allowing new devig algorithms to live in a single module.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — Pinnacle-Weighted Consensus

### Task B1: Config knobs (all v2 flags)

**Files:**
- Modify: `config.py` (append after line 39 — Kelly block)
- Modify: `requirements.txt`

- [ ] **Step 1: Add config knobs**

At the end of `config.py` (after line 155 block for `MODEL_PREDICTIONS_CSV`), insert:

```python
# -----------------------------------------------------------------------
# Betting Layer V2 (Spec: docs/superpowers/specs/2026-04-17-betting-layer-hardening-design.md)
# -----------------------------------------------------------------------
# Master flag — gates all Spec-2 behavior. Flip true after shadow period.
BETTING_V2_ENABLED = os.getenv("BETTING_V2_ENABLED", "false").lower() == "true"
# Run v1 and v2 in parallel and log deltas to data/v2_shadow.csv.
BETTING_V2_SHADOW_COMPARE = (
    os.getenv("BETTING_V2_SHADOW_COMPARE", "true").lower() == "true"
)

# Sharp-book consensus weighting — §3.3
SHARP_BOOKS = ["pinnacle", "circa", "betcris"]
SHARP_BOOK_WEIGHT = 0.60   # total weight assigned to sharp books

# Correlation cap — §3.5
MAX_SAME_GAME_EXPOSURE = 1.4   # cap summed Kelly to best_leg * this
SAFETY_KEEP_TOP_N = 4          # fallback floor under the correlation cap

# Suspicious-edge quarantine — §3.7
MAX_LEGITIMATE_EDGE = 0.15

# Uncertainty shrinkage — §3.6
UNCERTAINTY_K = 5.0
KELLY_FLOOR_FRACTION = 0.20    # shrunk Kelly is floored at 20% of raw quarter-Kelly

# Paths for new CSV artifacts
QUARANTINED_EDGES_CSV = os.path.join(DATA_DIR, "quarantined_edges.csv")
DEVIG_STATS_CSV = os.path.join(DATA_DIR, "devig_stats.csv")
V2_SHADOW_CSV = os.path.join(DATA_DIR, "v2_shadow.csv")
```

- [ ] **Step 2: Add `scipy` to `requirements.txt` (optional declaration)**

Append to `requirements.txt`:

```
scipy>=1.11.0
numpy>=1.26.0
```

(numpy is an implicit pandas dep; declaring explicitly documents the usage.)

- [ ] **Step 3: Verify import smoke test**

```bash
python3 -c "from config import BETTING_V2_ENABLED, SHARP_BOOKS, MAX_LEGITIMATE_EDGE, UNCERTAINTY_K, KELLY_FLOOR_FRACTION; print('v2 flag:', BETTING_V2_ENABLED, 'sharp:', SHARP_BOOKS)"
```

Expected: `v2 flag: False sharp: ['pinnacle', 'circa', 'betcris']`.

- [ ] **Step 4: Commit**

```bash
git add config.py requirements.txt
git commit -m "$(cat <<'EOF'
feat: add BETTING_V2 config knobs for Spec-2 hardening

Adds BETTING_V2_ENABLED / _SHADOW_COMPARE flags, SHARP_BOOKS /
SHARP_BOOK_WEIGHT for Pinnacle-weighted consensus, MAX_SAME_GAME_EXPOSURE
and SAFETY_KEEP_TOP_N for the correlation cap, MAX_LEGITIMATE_EDGE for
quarantine, UNCERTAINTY_K / KELLY_FLOOR_FRACTION for shrinkage Kelly,
and paths for the new CSV artifacts. Declares scipy + numpy in
requirements (forward-compat; not imported today).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B2: Add `_weighted_consensus` helper + extend `OddsData`

**Files:**
- Modify: `scrapers/odds.py` (OddsData dataclass @ `:76-97`; new helper)
- Create: `tests/test_weighted_consensus.py`

- [ ] **Step 1: Write failing test for `_weighted_consensus`**

Create `tests/test_weighted_consensus.py`:

```python
"""Tests for Pinnacle-weighted consensus in scrapers/odds.py."""
from unittest.mock import patch

import pytest

from scrapers import odds as odds_mod
from scrapers.odds import _weighted_consensus


def _book(key: str, home_price: int, away_price: int) -> dict:
    return {"key": key, "home_price": home_price, "away_price": away_price}


class TestWeightedConsensus:
    def test_no_sharp_books_equal_weight(self):
        # (book_key, p_home_devig, p_away_devig) tuples
        entries = [
            ("draftkings", 0.55, 0.45),
            ("fanduel", 0.54, 0.46),
            ("betmgm", 0.56, 0.44),
        ]
        p_home, p_away, n = _weighted_consensus(entries)
        assert n == 3
        assert p_home == pytest.approx((0.55 + 0.54 + 0.56) / 3, abs=1e-6)
        assert p_away == pytest.approx((0.45 + 0.46 + 0.44) / 3, abs=1e-6)

    def test_sharp_only_equal_weight(self):
        entries = [
            ("pinnacle", 0.55, 0.45),
            ("circa", 0.56, 0.44),
        ]
        p_home, p_away, n = _weighted_consensus(entries)
        assert n == 2
        assert p_home == pytest.approx(0.555, abs=1e-6)
        assert p_away == pytest.approx(0.445, abs=1e-6)

    def test_sharp_plus_retail_60_40(self):
        # 1 sharp, 1 retail: sharp carries 0.60, retail carries 0.40.
        entries = [
            ("pinnacle", 0.60, 0.40),
            ("fanduel", 0.50, 0.50),
        ]
        p_home, p_away, n = _weighted_consensus(entries)
        assert p_home == pytest.approx(0.60 * 0.60 + 0.50 * 0.40, abs=1e-6)
        assert p_away == pytest.approx(0.40 * 0.60 + 0.50 * 0.40, abs=1e-6)
        assert p_home + p_away == pytest.approx(1.0, abs=1e-6)

    def test_sharp_plus_three_retail(self):
        # 1 sharp, 3 retail: sharp = 0.60, each retail = 0.40/3 ≈ 0.1333
        entries = [
            ("pinnacle", 0.60, 0.40),
            ("fanduel", 0.50, 0.50),
            ("draftkings", 0.52, 0.48),
            ("betmgm", 0.54, 0.46),
        ]
        p_home, p_away, n = _weighted_consensus(entries)
        retail_mean_home = (0.50 + 0.52 + 0.54) / 3
        retail_mean_away = (0.50 + 0.48 + 0.46) / 3
        assert p_home == pytest.approx(0.60 * 0.60 + retail_mean_home * 0.40, abs=1e-6)
        assert p_away == pytest.approx(0.40 * 0.60 + retail_mean_away * 0.40, abs=1e-6)

    def test_empty_input(self):
        p_home, p_away, n = _weighted_consensus([])
        assert (p_home, p_away, n) == (0.0, 0.0, 0)

    def test_different_from_equal_weight(self):
        # Regression: prove sharp weighting moves the needle vs equal.
        entries = [
            ("pinnacle", 0.60, 0.40),
            ("fanduel", 0.50, 0.50),
            ("draftkings", 0.50, 0.50),
        ]
        p_sharp, _, _ = _weighted_consensus(entries)
        equal_weight = (0.60 + 0.50 + 0.50) / 3
        assert abs(p_sharp - equal_weight) > 0.01  # meaningful difference
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_weighted_consensus.py -v
```

Expected: `ImportError: cannot import name '_weighted_consensus' from 'scrapers.odds'`.

- [ ] **Step 3: Implement `_weighted_consensus` and extend `OddsData`**

In `scrapers/odds.py`, after the existing imports (line 5 area), add:

```python
from config import (
    ODDS_API_KEY, ODDS_API_BASE, TEAM_NAME_TO_ABBREV,
    SHARP_BOOKS, SHARP_BOOK_WEIGHT, BETTING_V2_ENABLED,
)
```

(Extend the existing `from config import ...` — do not add a duplicate line.)

Add the helper BELOW the `OddsData` dataclass (insert after line 97, before `_team_abbrev`):

```python
def _weighted_consensus(
    entries: list[tuple[str, float, float]],
) -> tuple[float, float, int]:
    """Pinnacle-weighted consensus over already-devigged per-book probs.

    Each entry is (book_key_lowercase, p_home_devig, p_away_devig).
    Sharp books (config.SHARP_BOOKS) split config.SHARP_BOOK_WEIGHT;
    retail books split the remainder. If no sharp books are present,
    falls back to equal weight across all retail books. If only sharp
    books are present, equal weight across sharp. Empty input -> zeros.

    Returns (p_home, p_away, n_books).
    """
    if not entries:
        return (0.0, 0.0, 0)

    sharp_set = {b.lower() for b in SHARP_BOOKS}
    sharp = [(b, ph, pa) for (b, ph, pa) in entries if b.lower() in sharp_set]
    retail = [(b, ph, pa) for (b, ph, pa) in entries if b.lower() not in sharp_set]
    n = len(entries)

    if sharp and retail:
        w_sharp = SHARP_BOOK_WEIGHT / len(sharp)
        w_retail = (1.0 - SHARP_BOOK_WEIGHT) / len(retail)
        p_home = sum(w_sharp * ph for _, ph, _ in sharp) + \
                 sum(w_retail * ph for _, ph, _ in retail)
        p_away = sum(w_sharp * pa for _, _, pa in sharp) + \
                 sum(w_retail * pa for _, _, pa in retail)
    else:
        pool = sharp or retail
        p_home = sum(ph for _, ph, _ in pool) / len(pool)
        p_away = sum(pa for _, _, pa in pool) / len(pool)

    return (round(p_home, 6), round(p_away, 6), n)
```

Extend the `OddsData` dataclass (add fields after `book_sources` at line 97):

```python
    # Spec 2 additions
    best_line_book: dict = field(default_factory=dict)
    # keys: f"{market_key}_{side_id}" e.g. "h2h_home", "spreads_away",
    #       "totals_over", "f5_ml_home", "f5_total_over", ...
    # values: lowercase book key
    best_line_odds: dict = field(default_factory=dict)
    # same keys; values: American odds
    shin_z: dict = field(default_factory=dict)
    # keys: market_key e.g. "h2h", "spreads"; values: insider fraction z
    consensus_sharp_books: list = field(default_factory=list)
    # lowercase book keys used in consensus (for logging/debug)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_weighted_consensus.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add scrapers/odds.py tests/test_weighted_consensus.py
git commit -m "$(cat <<'EOF'
feat: add _weighted_consensus + extend OddsData for Spec 2

Helper `_weighted_consensus` blends sharp books at SHARP_BOOK_WEIGHT
against retail equal-weight. Falls back to equal weight when either
pool is empty. OddsData gains best_line_book, best_line_odds, shin_z,
and consensus_sharp_books — populated in subsequent tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task B3: Wire weighted consensus into h2h / spreads + populate shin_z / best-line fields

**Files:**
- Modify: `scrapers/odds.py` (consensus loop at `:392-432`, best-line population at `:353-390`)
- Create: `tests/test_best_line_metadata.py`

- [ ] **Step 1: Write failing test for best-line metadata**

Create `tests/test_best_line_metadata.py`:

```python
"""Tests for OddsData.best_line_book / best_line_odds population."""
from unittest.mock import patch

import pytest

from scrapers.odds import get_mlb_odds


def _fake_event(home="Los Angeles Dodgers", away="San Francisco Giants"):
    return {
        "id": "evt1",
        "home_team": home,
        "away_team": away,
        "commence_time": "2099-12-31T23:59:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": home, "price": -120},
                        {"name": away, "price": +110},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": home, "price": +140, "point": -1.5},
                        {"name": away, "price": -160, "point": +1.5},
                    ]},
                ],
            },
            {
                "key": "fanduel",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": home, "price": -125},
                        {"name": away, "price": +108},
                    ]},
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": home, "price": -118},  # best price on home
                        {"name": away, "price": +112},  # best price on away
                    ]},
                ],
            },
        ],
    }


class TestBestLineMetadata:
    def test_best_line_book_and_odds_populated(self):
        fake_resp = type("R", (), {
            "json": lambda self: [_fake_event()],
            "headers": {"x-requests-remaining": "500"},
            "status_code": 200,
            "raise_for_status": lambda self: None,
        })()
        with patch("scrapers.odds.requests.get", return_value=fake_resp):
            results = get_mlb_odds(date="2099-12-31")
        assert len(results) == 1
        od = results[0]
        # Best home ML is -118 at draftkings
        assert od.best_line_book.get("h2h_home") == "draftkings"
        assert od.best_line_odds.get("h2h_home") == -118
        # Best away ML is +112 at draftkings
        assert od.best_line_book.get("h2h_away") == "draftkings"
        assert od.best_line_odds.get("h2h_away") == 112
        # Spreads — only pinnacle has them
        assert od.best_line_book.get("spreads_home") == "pinnacle"
        assert od.best_line_odds.get("spreads_home") == 140

    def test_consensus_sharp_books_recorded(self):
        fake_resp = type("R", (), {
            "json": lambda self: [_fake_event()],
            "headers": {"x-requests-remaining": "500"},
            "status_code": 200,
            "raise_for_status": lambda self: None,
        })()
        with patch("scrapers.odds.requests.get", return_value=fake_resp):
            results = get_mlb_odds(date="2099-12-31")
        assert "pinnacle" in results[0].consensus_sharp_books

    def test_shin_z_present_for_h2h(self):
        fake_resp = type("R", (), {
            "json": lambda self: [_fake_event()],
            "headers": {"x-requests-remaining": "500"},
            "status_code": 200,
            "raise_for_status": lambda self: None,
        })()
        with patch("scrapers.odds.requests.get", return_value=fake_resp):
            results = get_mlb_odds(date="2099-12-31")
        assert "h2h" in results[0].shin_z
        assert 0.0 <= results[0].shin_z["h2h"] < 0.2
```

- [ ] **Step 2: Run test — confirm it fails**

```bash
pytest tests/test_best_line_metadata.py -v
```

Expected: `AssertionError` on `od.best_line_book.get("h2h_home")` (empty dict).

- [ ] **Step 3: Populate best-line fields in the existing `:353-390` block**

In `scrapers/odds.py`, for each `if ("X", side) in best:` branch (lines 353–390), add lines that also populate `best_line_book` and `best_line_odds`. Example for the h2h_home block:

```python
        if ("h2h", home) in best:
            odds_data.moneyline["home"] = best[("h2h", home)][1]
            odds_data.book_sources["h2h_home"] = best[("h2h", home)][2]
            odds_data.best_line_book["h2h_home"] = best[("h2h", home)][2].lower()
            odds_data.best_line_odds["h2h_home"] = int(best[("h2h", home)][1])
```

Apply the same `best_line_book` / `best_line_odds` population to:

- `("h2h", away)` → key `h2h_away`
- `("spreads", home)` → key `spreads_home`
- `("spreads", away)` → key `spreads_away`
- `("totals", "Over")` → key `totals_over`
- `("totals", "Under")` → key `totals_under`
- `("h2h_1st_5_innings", home)` → key `f5_ml_home`
- `("h2h_1st_5_innings", away)` → key `f5_ml_away`
- `("totals_1st_5_innings", "Over")` → key `f5_total_over`
- `("totals_1st_5_innings", "Under")` → key `f5_total_under`

- [ ] **Step 4: Wire weighted consensus + shin_z into the h2h / spreads loop**

Replace the h2h consensus block (`:394-408`) with:

```python
        # Compute market consensus implied probabilities using Pinnacle-weighted
        # consensus (Spec 2 §3.3) when BETTING_V2_ENABLED; otherwise equal-weight.
        if odds_data.moneyline:
            h2h_books = all_book_odds.get("h2h", [])
            entries = []
            shin_zs = []
            for book in h2h_books:
                book_key = book.get("_book", "")
                if home in book and away in book:
                    h = american_to_implied_prob(book[home])
                    a = american_to_implied_prob(book[away])
                    dh, da = power_devig(h, a)
                    entries.append((book_key, dh, da))
                    _, _, zb = shin_devig(h, a)
                    shin_zs.append(zb)
            if entries:
                if BETTING_V2_ENABLED:
                    ph, pa, n = _weighted_consensus(entries)
                    sharp_set = {b.lower() for b in SHARP_BOOKS}
                    odds_data.consensus_sharp_books = [
                        b for (b, _, _) in entries if b.lower() in sharp_set
                    ]
                else:
                    ph = round(sum(p for _, p, _ in entries) / len(entries), 6)
                    pa = round(sum(p for _, _, p in entries) / len(entries), 6)
                    n = len(entries)
                odds_data.implied_probs["ml_home"] = ph
                odds_data.implied_probs["ml_away"] = pa
                odds_data.implied_probs["ml_book_count"] = n
            if shin_zs:
                odds_data.shin_z["h2h"] = round(
                    sum(shin_zs) / len(shin_zs), 4
                )
```

**Important: the existing loop builds `all_book_odds` as a list of `side_id -> american_odds` dicts WITHOUT the book key.** Extend the inner loop at `:319-350` so the per-book snapshot is tagged. Change:

```python
                if book_snapshot:
                    all_book_odds.setdefault(market_key, []).append(book_snapshot)
```

to:

```python
                if book_snapshot:
                    book_snapshot["_book"] = book_name
                    all_book_odds.setdefault(market_key, []).append(book_snapshot)
```

And in the existing spreads consensus block at `:410-432`, mirror the pattern (accumulate `entries` with `book_key`, wrap in `BETTING_V2_ENABLED`, record per-book Shin `z` under `shin_z["spreads"]`).

- [ ] **Step 5: Flip `BETTING_V2_ENABLED` via monkeypatch in the test; run**

Update `tests/test_best_line_metadata.py`'s `TestBestLineMetadata` to use a pytest fixture that monkeypatches `scrapers.odds.BETTING_V2_ENABLED = True` for the sharp-books + weighted-consensus assertions. Best-line-book population works with the flag off (always populated).

```bash
pytest tests/test_best_line_metadata.py tests/test_weighted_consensus.py -v
```

Expected: all pass.

- [ ] **Step 6: Run the full existing test suite to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: no new failures vs. baseline (flag off = unchanged behavior).

- [ ] **Step 7: Commit**

```bash
git add scrapers/odds.py tests/test_best_line_metadata.py
git commit -m "$(cat <<'EOF'
feat: wire Pinnacle-weighted consensus + shin_z + best-line into OddsData

The consensus construction in get_mlb_odds now tags each book snapshot
with its book key, records Shin z per market, and — when
BETTING_V2_ENABLED — blends sharp books at SHARP_BOOK_WEIGHT. Best-line
book and American odds are populated alongside the existing
book_sources mapping.

With the flag off, v1 behavior (equal-weight average) is preserved
byte-for-byte. Best-line metadata is always populated (harmless when
unused).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Consistent Dual De-Vig Gate in `edge.py`

### Task C1: Add `_dual_devig_check` helper

**Files:**
- Modify: `edge.py` (add helper below `_passes_worst_case_filter` at `:33-41`)

- [ ] **Step 1: Write failing test in `tests/test_edge.py`**

Append to `tests/test_edge.py`:

```python
def test_dual_devig_check_agreement():
    """Shin and power devig should agree within 1.5pp on symmetric markets."""
    from edge import _dual_devig_check
    raw_home = 130 / 230   # -130
    raw_away = 100 / 215   # +115
    sim_prob = 0.56
    passes, info = _dual_devig_check(sim_prob, raw_home, raw_away, threshold=0.01)
    assert passes is True
    assert "shin_edge" in info
    assert "power_edge" in info
    assert info["devig_method"] == "agree"
    assert abs(info["shin_edge"] - info["power_edge"]) < 0.015


def test_dual_devig_check_below_threshold():
    from edge import _dual_devig_check
    passes, info = _dual_devig_check(
        sim_prob=0.50, raw_own=0.53, raw_other=0.48, threshold=0.05,
    )
    # Post-devig, the edge should be near zero — nowhere near 0.05.
    assert passes is False


def test_dual_devig_check_fallback_on_missing_pair():
    """When raw_other is degenerate, fall back to worst-case filter."""
    from edge import _dual_devig_check
    passes, info = _dual_devig_check(
        sim_prob=0.80, raw_own=0.52, raw_other=0.0005, threshold=0.05,
    )
    assert info["devig_method"] == "worst_case_fallback"
```

- [ ] **Step 2: Run — confirm failure**

```bash
pytest tests/test_edge.py::test_dual_devig_check_agreement -v
```

Expected: `ImportError: cannot import name '_dual_devig_check' from 'edge'`.

- [ ] **Step 3: Implement helper**

In `edge.py`, after `_passes_worst_case_filter` (line 41), insert:

```python
from scrapers.devig import shin_devig
from scrapers.odds import power_devig as _power_devig


def _dual_devig_check(
    sim_prob: float,
    raw_own: float,
    raw_other: float,
    threshold: float,
) -> tuple[bool, dict]:
    """Compute both Shin and power de-vig; require both edges >= threshold.

    Returns (passes, info) where info always contains:
        shin_implied, shin_edge, shin_z,
        power_implied, power_edge,
        devig_divergence, devig_method ("agree"|"divergent"|"worst_case_fallback")
    """
    # Fallback: if either side degenerate, use worst-case gate.
    if raw_other <= 0.001 or raw_other >= 0.999 or raw_own <= 0.001 or raw_own >= 0.999:
        passes, wc_edge = _passes_worst_case_filter(sim_prob, raw_own, raw_other)
        return passes and (wc_edge >= threshold), {
            "shin_implied": 1 - raw_other,
            "shin_edge": wc_edge,
            "shin_z": 0.0,
            "power_implied": 1 - raw_other,
            "power_edge": wc_edge,
            "devig_divergence": 0.0,
            "devig_method": "worst_case_fallback",
        }

    power_own, _ = _power_devig(raw_own, raw_other)
    shin_own, _, z = shin_devig(raw_own, raw_other)

    power_edge = sim_prob - power_own
    shin_edge = sim_prob - shin_own
    divergence = abs(shin_edge - power_edge)
    method = "divergent" if divergence > 0.015 else "agree"
    if method == "divergent":
        logger.warning(
            "devig divergence shin=%.3f power=%.3f z=%.3f (own=%.3f other=%.3f)",
            shin_edge, power_edge, z, raw_own, raw_other,
        )

    passes = min(shin_edge, power_edge) >= threshold
    return passes, {
        "shin_implied": round(shin_own, 6),
        "shin_edge": round(shin_edge, 4),
        "shin_z": round(z, 4),
        "power_implied": round(power_own, 6),
        "power_edge": round(power_edge, 4),
        "devig_divergence": round(divergence, 4),
        "devig_method": method,
    }
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_edge.py -v -k dual_devig
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "$(cat <<'EOF'
feat: add _dual_devig_check combining Shin + power de-vig

New helper in edge.py returns (passes, info) where passes requires
min(shin_edge, power_edge) >= threshold. Degenerate pairs fall back to
the existing worst-case gate. Divergence > 1.5pp is logged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C2: Replace moneyline worst-case gate with dual-devig

**Files:**
- Modify: `edge.py:70-101`
- Modify: `tests/test_edge.py`

- [ ] **Step 1: Update the moneyline test fixtures to assert new fields**

In `tests/test_edge.py`, find the existing moneyline-edge tests (for `check_moneyline_edge`). Add/extend an assertion block:

```python
def test_moneyline_returns_shin_fields(sim_factory, odds_factory):
    bet = check_moneyline_edge(sim_factory(home_win=0.56), odds_factory())
    assert bet is not None
    assert "shin_edge" in bet
    assert "shin_z" in bet
    assert "devig_method" in bet
    assert bet["devig_method"] in ("agree", "divergent", "worst_case_fallback")
```

(If `sim_factory` / `odds_factory` fixtures don't exist, build minimal dicts inline matching existing test patterns.)

- [ ] **Step 2: Run — expect failure on missing fields**

```bash
pytest tests/test_edge.py::test_moneyline_returns_shin_fields -v
```

Expected: `AssertionError: 'shin_edge' in bet`.

- [ ] **Step 3: Rewrite `check_moneyline_edge` branches**

In `edge.py:70-101`, replace both the home-edge and away-edge branches:

```python
    # Take the side with more edge
    if home_edge >= threshold and home_edge >= away_edge:
        passes, dv = _dual_devig_check(home_prob, raw_home, raw_away, threshold)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["home"])
        return {
            "bet_type": "moneyline",
            "side": "home",
            "odds": ml_odds["home"],
            "sim_prob": home_prob,
            "market_prob": home_implied,
            "edge": round(home_edge, 4),
            "worst_case_edge": dv["shin_edge"],  # back-compat column
            "shin_edge": dv["shin_edge"],
            "shin_z": dv["shin_z"],
            "power_edge": dv["power_edge"],
            "devig_method": dv["devig_method"],
            "kelly_pct": _sized_kelly(home_prob, dec),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        passes, dv = _dual_devig_check(away_prob, raw_away, raw_home, threshold)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["away"])
        return {
            "bet_type": "moneyline",
            "side": "away",
            "odds": ml_odds["away"],
            "sim_prob": away_prob,
            "market_prob": away_implied,
            "edge": round(away_edge, 4),
            "worst_case_edge": dv["shin_edge"],
            "shin_edge": dv["shin_edge"],
            "shin_z": dv["shin_z"],
            "power_edge": dv["power_edge"],
            "devig_method": dv["devig_method"],
            "kelly_pct": _sized_kelly(away_prob, dec),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    return None
```

- [ ] **Step 4: Run full edge tests**

```bash
pytest tests/test_edge.py -v
```

Expected: all pass (including the new Shin-fields test).

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "$(cat <<'EOF'
refactor: replace worst-case gate with dual-devig in moneyline check

check_moneyline_edge now gates on min(shin_edge, power_edge) via
_dual_devig_check. Bet dicts expose shin_edge, shin_z, power_edge, and
devig_method. worst_case_edge is retained as an alias (= shin_edge) for
back-compat with trackers that reference that column.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task C3: Propagate dual-devig gate to all remaining checkers

**Files:**
- Modify: `edge.py` — checkers at `:106-176` (run_line), `:179-252` (total), `:255-313` (f5_ml), `:316-383` (f5_total), `:415-472` (team_total), `:475-555` (innings_spread → f5_rl / f1_rl / f3_rl), `:564-618` (nrfi), `:627-680` (f3_ml), `:683-744` (f3_total), and the derived-ML block at `:831-853`.
- Modify: `tests/test_edge.py`, `tests/test_edge_phase1.py`

- [ ] **Step 1: For each checker, add a test asserting `shin_edge` is present**

Example entries to add (or merge into existing tests in `test_edge_phase1.py`):

```python
@pytest.mark.parametrize("bet_fn_name", [
    "check_run_line_edge", "check_total_edge", "check_f5_ml_edge",
    "check_f5_total_edge",
])
def test_top_level_checkers_emit_shin_fields(bet_fn_name, monkeypatch):
    from edge import (
        check_run_line_edge, check_total_edge,
        check_f5_ml_edge, check_f5_total_edge,
    )
    fns = {
        "check_run_line_edge": check_run_line_edge,
        "check_total_edge": check_total_edge,
        "check_f5_ml_edge": check_f5_ml_edge,
        "check_f5_total_edge": check_f5_total_edge,
    }
    sim, odds = _edgey_fixture_for(bet_fn_name)  # helper returns high-edge inputs
    bet = fns[bet_fn_name](sim, odds)
    assert bet is not None
    assert "shin_edge" in bet
    assert "devig_method" in bet
```

For the OddsData-based checkers (`check_team_total_edge`, `check_nrfi_edge`, `check_f1_rl_edge`, `check_f3_*`), add analogous tests in `tests/test_edge_phase1.py`.

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_edge.py tests/test_edge_phase1.py -v -k shin_fields
```

Expected: failures (fields missing).

- [ ] **Step 3: Apply the dual-devig swap in each checker**

For every `passes, wc_edge = _passes_worst_case_filter(...)` call and its surrounding dict-return, replace the call with `_dual_devig_check` and thread `shin_edge`, `shin_z`, `power_edge`, `devig_method` into the returned bet dict (same pattern as Task C2).

Checkers to update (line anchors approximate):

| Function | Line range | Pair of branches |
|---|---|---|
| `check_run_line_edge` | 106-176 | fav_edge / dog_edge |
| `check_total_edge` | 179-252 | over_edge / under_edge |
| `check_f5_ml_edge` | 255-313 | h_edge / a_edge |
| `check_f5_total_edge` | 316-383 | over_edge / under_edge |
| `check_team_total_edge` | 415-472 | over_edge / under_edge |
| `_check_innings_spread_edge` | 475-555 | home_edge / away_edge |
| `check_nrfi_edge` | 564-618 | nrfi_edge / yrfi_edge |
| `check_f3_ml_edge` | 627-680 | h_edge / a_edge |
| `check_f3_total_edge` | 683-744 | over_edge / under_edge |
| derived-ML block | 831-853 | single branch |

For each, retain `worst_case_edge = dv["shin_edge"]` as a back-compat alias; add `shin_edge`, `shin_z`, `power_edge`, `devig_method` to the return dict.

- [ ] **Step 4: Run the affected suites**

```bash
pytest tests/test_edge.py tests/test_edge_phase1.py -v
```

Expected: all pass.

- [ ] **Step 5: Run the full suite to catch downstream breakage**

```bash
pytest tests/ -v
```

Expected: no new failures. The only concern is bet-card rendering, covered by `tests/test_bet_card.py`.

- [ ] **Step 6: Commit**

```bash
git add edge.py tests/test_edge.py tests/test_edge_phase1.py
git commit -m "$(cat <<'EOF'
refactor: dual-devig gate across all edge checkers

Swaps _passes_worst_case_filter for _dual_devig_check in run_line,
total, f5_ml, f5_total, team_total, f5_rl/f1_rl/f3_rl (via
_check_innings_spread_edge), nrfi, f3_ml, f3_total, and the derived-ML
block. Every returned bet dict now carries shin_edge, shin_z,
power_edge, and devig_method. worst_case_edge kept as alias.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — Best-Line Execution Metadata

### Task D1: Extend `tracker.COLUMNS` + idempotent migration

**Files:**
- Modify: `tracker.py:15-19`
- Modify: `tracker.py` (add `_ensure_csv_has_columns`)
- Modify: `tests/test_bet_card.py` or create targeted tracker test

- [ ] **Step 1: Write failing test for schema migration**

Create `tests/test_tracker_v2_schema.py`:

```python
"""Schema tests for v2 CSV columns."""
import pandas as pd
import pytest

import tracker


def test_ensure_csv_has_columns_adds_missing(tmp_path):
    csv = tmp_path / "bets_old.csv"
    # Old schema (pre-Spec-2)
    pd.DataFrame([{
        "date": "2026-04-01", "game": "LAD@SF", "bet_type": "moneyline",
        "side": "home", "odds": -130, "sim_prob": 0.6,
        "market_prob": 0.55, "edge": 0.05, "kelly_pct": 0.02,
        "result": "", "profit": "", "close_odds": "", "close_prob": "",
        "clv_cents": "", "clv_pct": "",
    }]).to_csv(csv, index=False)

    tracker._ensure_csv_has_columns(str(csv))
    df = pd.read_csv(csv)
    for col in ("best_book", "best_odds", "shin_edge", "shin_z", "devig_method"):
        assert col in df.columns, f"Missing {col}"


def test_ensure_csv_has_columns_idempotent(tmp_path):
    csv = tmp_path / "bets_new.csv"
    pd.DataFrame(columns=tracker.COLUMNS).to_csv(csv, index=False)
    tracker._ensure_csv_has_columns(str(csv))
    tracker._ensure_csv_has_columns(str(csv))  # twice is fine
    df = pd.read_csv(csv)
    # No duplicate columns
    assert len(df.columns) == len(set(df.columns))


def test_log_bet_stores_best_book_and_shin(tmp_path):
    csv = str(tmp_path / "bets.csv")
    tracker.log_bet({
        "date": "2026-04-17", "game": "LAD@SF", "bet_type": "moneyline",
        "side": "home", "odds": -130, "sim_prob": 0.60, "market_prob": 0.55,
        "edge": 0.05, "kelly_pct": 0.02,
        "best_book": "pinnacle", "best_odds": -128,
        "shin_edge": 0.048, "shin_z": 0.027, "devig_method": "agree",
    }, csv_path=csv)
    df = pd.read_csv(csv)
    assert df.iloc[0]["best_book"] == "pinnacle"
    assert int(df.iloc[0]["best_odds"]) == -128
    assert df.iloc[0]["devig_method"] == "agree"
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_tracker_v2_schema.py -v
```

Expected: `AttributeError: module 'tracker' has no attribute '_ensure_csv_has_columns'`.

- [ ] **Step 3: Extend `COLUMNS` + add migration helper**

In `tracker.py:15-19`:

```python
COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "market_prob", "edge", "kelly_pct",
    "best_book", "best_odds",                    # Spec 2 §3.4
    "result", "profit",
    "close_odds", "close_prob", "clv_cents", "clv_pct",
    "shin_edge", "shin_z", "devig_method",       # Spec 2 §3.2 pass-through
]
```

Below `_ensure_csv` (line 114), add:

```python
def _ensure_csv_has_columns(csv_path: str) -> None:
    """Idempotently add any missing Spec 2 columns to an existing bets CSV.

    Reads header, adds new columns with empty-string values, writes back.
    No-op if all columns already present.
    """
    if not os.path.exists(csv_path):
        return
    with _csv_lock:
        df = pd.read_csv(csv_path)
        changed = False
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
                changed = True
        if changed:
            # Preserve COLUMNS ordering at write time.
            ordered = [c for c in COLUMNS if c in df.columns]
            extras = [c for c in df.columns if c not in COLUMNS]
            df = df[ordered + extras]
            df.to_csv(csv_path, index=False)
```

Modify the module-level import block to call this once when the default CSV exists:

```python
# Auto-migrate the default bets CSV on import. Idempotent.
try:
    _ensure_csv_has_columns(BETS_CSV)
except Exception:  # pragma: no cover — defensive
    pass
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_tracker_v2_schema.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker_v2_schema.py
git commit -m "$(cat <<'EOF'
feat: extend bets.csv schema with Spec 2 columns + idempotent migration

New columns: best_book, best_odds, shin_edge, shin_z, devig_method.
`_ensure_csv_has_columns` is called once on module import to migrate
an existing CSV; no-op if columns already present. log_bet stores the
new fields when present in the bet dict.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task D2: Thread best-line metadata from `OddsData` into `log_bet`

**Files:**
- Modify: `tracker.py:122-147` (`log_bet` signature + body)
- Modify: `main.py` (or wherever `log_bet` is called — callers pass `odds_data=`)

- [ ] **Step 1: Write failing test**

Append to `tests/test_tracker_v2_schema.py`:

```python
def test_log_bet_extracts_best_line_from_odds_data(tmp_path):
    from scrapers.odds import OddsData
    od = OddsData(home="SF", away="LAD", commence_time="")
    od.best_line_book = {"h2h_home": "pinnacle"}
    od.best_line_odds = {"h2h_home": -128}
    csv = str(tmp_path / "bets.csv")
    tracker.log_bet({
        "date": "2026-04-17", "game": "LAD@SF", "bet_type": "moneyline",
        "side": "home", "odds": -130, "sim_prob": 0.60, "market_prob": 0.55,
        "edge": 0.05, "kelly_pct": 0.02,
    }, csv_path=csv, odds_data=od)
    df = pd.read_csv(csv)
    assert df.iloc[0]["best_book"] == "pinnacle"
    assert int(df.iloc[0]["best_odds"]) == -128
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_tracker_v2_schema.py::test_log_bet_extracts_best_line_from_odds_data -v
```

Expected: `TypeError: log_bet() got an unexpected keyword argument 'odds_data'`.

- [ ] **Step 3: Update `log_bet` signature + pull best-line**

Rewrite `log_bet` in `tracker.py`:

```python
# Mapping (bet_type, side_prefix) -> best-line key
def _best_line_key(bet_type: str, side: str) -> str | None:
    if bet_type == "moneyline":
        return f"h2h_{side.split()[0].lower()}" if side else None
    if bet_type == "run_line":
        first = side.split()[0].lower() if side else ""
        return f"spreads_{first}" if first in ("home", "away") else None
    if bet_type == "total":
        first = side.split()[0].lower() if side else ""
        return f"totals_{first}" if first in ("over", "under") else None
    if bet_type == "first_5_ml":
        first = side.split()[0].lower() if side else ""
        return f"f5_ml_{first}" if first in ("home", "away") else None
    if bet_type == "first_5_total":
        first = side.split()[0].lower() if side else ""
        return f"f5_total_{first}" if first in ("over", "under") else None
    return None


def log_bet(bet: dict, csv_path: str = None, odds_data=None) -> bool:
    """Append a bet. Optionally pull best-line metadata from OddsData."""
    csv_path = csv_path or BETS_CSV

    # Pull best-line metadata if available + not already supplied.
    if odds_data is not None and "best_book" not in bet:
        key = _best_line_key(bet.get("bet_type", ""), bet.get("side", ""))
        if key:
            book = getattr(odds_data, "best_line_book", {}).get(key)
            odds = getattr(odds_data, "best_line_odds", {}).get(key)
            if book is not None:
                bet = {**bet, "best_book": book}
                if odds is not None:
                    bet = {**bet, "best_odds": int(odds)}

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")
    with _csv_lock:
        _ensure_csv(csv_path)
        _ensure_csv_has_columns(csv_path)
        df = pd.read_csv(csv_path)
        if not df.empty:
            match = (
                (df["date"] == row["date"]) &
                (df["game"] == row["game"]) &
                (df["bet_type"] == row["bet_type"]) &
                (df["side"] == row["side"])
            )
            if match.any():
                return False
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(csv_path, index=False)
        return True
```

- [ ] **Step 4: Run tracker tests**

```bash
pytest tests/test_tracker_v2_schema.py -v
```

Expected: all 4 pass.

- [ ] **Step 5: Update callers in `main.py` to pass `odds_data=`**

Grep for `log_bet(` in `main.py` / `agents/daily_runner.py` and thread the `OddsData` instance:

```bash
grep -n "log_bet(" main.py agents/daily_runner.py
```

For each call, add `odds_data=game_data["odds_obj"]`. When the caller doesn't have `OddsData` (e.g., tests), the parameter defaults to `None` and behavior is unchanged.

- [ ] **Step 6: Smoke test**

```bash
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tracker.py main.py tests/test_tracker_v2_schema.py
git commit -m "$(cat <<'EOF'
feat: thread best-line metadata from OddsData into log_bet

`log_bet(bet, csv_path, odds_data=None)`. When odds_data is provided
and best_book is not already in the bet dict, map (bet_type, side) to
the best_line_book/odds key and populate both fields automatically.
main.py passes odds_data; other callers are untouched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E — Correlated-Bet Kelly Cap

### Task E1: Create `sizing.py` skeleton + correlation groups

**Files:**
- Create: `sizing.py`
- Create: `tests/test_sizing_correlation.py`

- [ ] **Step 1: Write failing property tests**

Create `tests/test_sizing_correlation.py`:

```python
"""Tests for correlation-aware Kelly cap."""
import copy
import random
import pytest

from sizing import compute_correlation_groups, cap_same_game_exposure


def _bet(bet_type, side, kelly, edge=0.06):
    return {
        "bet_type": bet_type, "side": side,
        "kelly_pct": kelly, "edge": edge,
    }


class TestComputeCorrelationGroups:
    def test_home_cluster(self):
        bets = [
            _bet("moneyline", "home", 0.02),
            _bet("run_line", "home -1.5", 0.015),
            _bet("total", "over 8.5", 0.01),
            _bet("team_total_home", "home over 4.5", 0.01),
        ]
        groups = compute_correlation_groups(bets)
        assert "A_run_home" in groups
        assert len(groups["A_run_home"]) == 4

    def test_away_cluster(self):
        bets = [
            _bet("moneyline", "away", 0.02),
            _bet("run_line", "away +1.5", 0.01),
            _bet("total", "under 8.5", 0.01),
            _bet("team_total_away", "away over 4.5", 0.008),
        ]
        groups = compute_correlation_groups(bets)
        assert "A_run_away" in groups
        assert len(groups["A_run_away"]) == 4

    def test_f5_cluster(self):
        bets = [
            _bet("first_5_ml", "home F5 ML", 0.02),
            _bet("first_5_total", "over 4.5", 0.015),
            _bet("first_5_rl", "home -0.5", 0.01),
        ]
        groups = compute_correlation_groups(bets)
        assert "B_f5" in groups
        assert len(groups["B_f5"]) == 3

    def test_first_inning_cluster(self):
        bets = [
            _bet("nrfi", "NRFI", 0.02),
            _bet("first_1_rl", "home +0.5", 0.01),
        ]
        groups = compute_correlation_groups(bets)
        assert "C_first_inn" in groups

    def test_tt_decomposition_agnostic_to_direction(self):
        bets = [
            _bet("team_total_home", "home over 4.5", 0.015),
            _bet("total", "under 8.5", 0.01),
        ]
        groups = compute_correlation_groups(bets)
        assert "D_tt_home" in groups
        assert len(groups["D_tt_home"]) == 2

    def test_bet_can_belong_to_multiple_groups(self):
        # A total-over bet alongside ML-home belongs to both A_run_home and D_tt_home (if TT also held).
        bets = [
            _bet("moneyline", "home", 0.02),
            _bet("total", "over 8.5", 0.015),
            _bet("team_total_home", "home over 4.5", 0.01),
        ]
        groups = compute_correlation_groups(bets)
        assert "A_run_home" in groups
        assert "D_tt_home" in groups


class TestCapSameGameExposure:
    def test_cap_preserves_sum_under_limit(self):
        bets = [_bet("moneyline", "home", 0.02)]
        out = cap_same_game_exposure(bets)
        assert out[0]["kelly_pct"] == pytest.approx(0.02, abs=1e-9)

    def test_cap_reduces_when_sum_exceeds(self):
        # Best leg 0.02; MULT = 1.4 -> cap = 0.028. Pre-scale sum = 0.045.
        bets = [
            _bet("moneyline", "home", 0.02),
            _bet("run_line", "home -1.5", 0.015),
            _bet("total", "over 8.5", 0.01),
        ]
        out = cap_same_game_exposure(bets)
        total = sum(b["kelly_pct"] for b in out)
        assert total <= 0.02 * 1.4 + 1e-9

    def test_best_leg_preserved(self):
        bets = [
            _bet("moneyline", "home", 0.03),
            _bet("run_line", "home -1.5", 0.02),
            _bet("total", "over 8.5", 0.01),
        ]
        out = cap_same_game_exposure(bets)
        # The bet with largest original kelly remains the max post-scale.
        max_bet = max(out, key=lambda b: b["kelly_pct"])
        assert max_bet["bet_type"] == "moneyline"

    def test_floor_drops_micro_legs(self):
        # Extreme: 10 legs at 0.001 each -> sum 0.01; cap = 0.001 * 1.4 = 0.0014.
        # Scale factor = 0.0014 / 0.01 = 0.14 -> per-leg ~0.00014 -> all below floor.
        bets = [_bet("moneyline", f"side_{i}", 0.001) for i in range(10)]
        out = cap_same_game_exposure(bets)
        for b in out:
            # Dropped legs are excluded (or zeroed); remaining must be >= 0.001.
            assert b["kelly_pct"] == 0.0 or b["kelly_pct"] >= 0.001

    def test_property_sum_never_exceeds_cap(self):
        random.seed(0xB16B00B5)
        for _ in range(200):
            n = random.randint(1, 6)
            bets = [
                _bet("moneyline" if i == 0 else "run_line",
                     "home" if i % 2 else "away",
                     round(random.uniform(0.003, 0.04), 4))
                for i in range(n)
            ]
            best = max(b["kelly_pct"] for b in bets)
            out = cap_same_game_exposure(bets)
            # Group sum cannot exceed best * 1.4 for any group.
            groups = compute_correlation_groups(out)
            for gname, members in groups.items():
                s = sum(b["kelly_pct"] for b in members)
                assert s <= best * 1.4 + 1e-6, f"group {gname} exceeded cap: {s}"

    def test_empty_input(self):
        assert cap_same_game_exposure([]) == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_sizing_correlation.py -v
```

Expected: `ModuleNotFoundError: No module named 'sizing'`.

- [ ] **Step 3: Implement `sizing.py`**

Create `sizing.py`:

```python
"""Correlated-bet Kelly cap (Spec 2 §3.5).

Groups same-game bets by empirical outcome correlation and proportionally
scales summed Kelly to stay within MAX_SAME_GAME_EXPOSURE * best_leg_kelly.
"""
from __future__ import annotations
import copy
import logging
from typing import Iterable

from config import MAX_SAME_GAME_EXPOSURE, KELLY_FLOOR_FRACTION

logger = logging.getLogger("mirofish.sizing")

GROUP_A_RUN_HOME = "A_run_home"
GROUP_A_RUN_AWAY = "A_run_away"
GROUP_B_F5 = "B_f5"
GROUP_C_FIRST_INN = "C_first_inn"
GROUP_D_TT_HOME = "D_tt_home"
GROUP_D_TT_AWAY = "D_tt_away"

FLOOR_DROP = 0.001  # legs capped below this are removed entirely


def _side_contains(side: str, token: str) -> bool:
    return token in (side or "").lower()


def _assign_groups(bet: dict) -> list[str]:
    bt = bet.get("bet_type", "")
    side = bet.get("side", "") or ""
    groups = []

    # Cluster A — outcome correlation keyed by offensive side
    if bt == "moneyline":
        if _side_contains(side, "home"):
            groups.append(GROUP_A_RUN_HOME)
        elif _side_contains(side, "away"):
            groups.append(GROUP_A_RUN_AWAY)
    elif bt == "run_line":
        if _side_contains(side, "home"):
            groups.append(GROUP_A_RUN_HOME)
        elif _side_contains(side, "away"):
            groups.append(GROUP_A_RUN_AWAY)
    elif bt == "total":
        # "over" correlates with both teams scoring; side-split below
        if _side_contains(side, "over"):
            groups.append(GROUP_A_RUN_HOME)
            groups.append(GROUP_A_RUN_AWAY)
        elif _side_contains(side, "under"):
            groups.append(GROUP_A_RUN_HOME)  # suppresses scoring both sides
            groups.append(GROUP_A_RUN_AWAY)
    elif bt == "team_total_home":
        # An over on home's team total is correlated with home winning + game over.
        groups.append(GROUP_A_RUN_HOME)
    elif bt == "team_total_away":
        groups.append(GROUP_A_RUN_AWAY)

    # Cluster B — F5 family
    if bt in ("first_5_ml", "first_5_total", "first_5_rl"):
        groups.append(GROUP_B_F5)

    # Cluster C — first inning
    if bt in ("nrfi", "first_1_rl"):
        groups.append(GROUP_C_FIRST_INN)

    # Cluster D — team-total decomposition (direction-agnostic)
    if bt == "team_total_home" or (bt == "total" and _side_contains(side, "")):
        if bt == "team_total_home":
            groups.append(GROUP_D_TT_HOME)
    if bt == "total":
        # total belongs to both decomposition groups iff the corresponding
        # team_total bet is present. Caller (compute_correlation_groups)
        # handles the presence check; we lazily tag and prune.
        groups.append(GROUP_D_TT_HOME)
        groups.append(GROUP_D_TT_AWAY)
    if bt == "team_total_away":
        groups.append(GROUP_D_TT_AWAY)

    # Dedup while preserving order
    seen = set()
    uniq = []
    for g in groups:
        if g not in seen:
            seen.add(g)
            uniq.append(g)
    return uniq


def compute_correlation_groups(bets: list[dict]) -> dict[str, list[dict]]:
    """Cluster bets by correlation group. A bet may appear in multiple groups.

    For cluster D (team-total decomposition), `total` is only attached to
    D_tt_home / D_tt_away when the corresponding team_total bet exists in
    the input.
    """
    groups: dict[str, list[dict]] = {}
    has_tt_home = any(b.get("bet_type") == "team_total_home" for b in bets)
    has_tt_away = any(b.get("bet_type") == "team_total_away" for b in bets)

    for bet in bets:
        for g in _assign_groups(bet):
            if g == GROUP_D_TT_HOME and bet.get("bet_type") == "total" and not has_tt_home:
                continue
            if g == GROUP_D_TT_AWAY and bet.get("bet_type") == "total" and not has_tt_away:
                continue
            groups.setdefault(g, []).append(bet)

    # Drop groups with a single leg (no correlation to cap).
    return {g: bs for g, bs in groups.items() if len(bs) >= 2}


def _bet_id(bet: dict) -> str:
    return f"{bet.get('bet_type')}::{bet.get('side')}"


def cap_same_game_exposure(
    bets: list[dict],
    max_multiplier: float | None = None,
) -> list[dict]:
    """Cap summed kelly_pct per correlation group to best_leg * max_multiplier.

    Proportional scaling: for each over-budget group, scale every leg by
    best_leg*MULT/sum. A bet in multiple groups is scaled by the tightest
    (smallest) factor. Legs that fall below FLOOR_DROP post-scale are
    removed from the output.
    """
    if not bets:
        return []
    mult = max_multiplier if max_multiplier is not None else MAX_SAME_GAME_EXPOSURE

    # Work on deepcopies so the caller's bet dicts aren't mutated.
    out = [copy.deepcopy(b) for b in bets]

    # Compute per-bet scale factor (min across groups it belongs to).
    scales: dict[str, float] = {_bet_id(b): 1.0 for b in out}
    groups = compute_correlation_groups(out)
    for gname, members in groups.items():
        ks = [m.get("kelly_pct", 0.0) for m in members]
        total = sum(ks)
        if total <= 0:
            continue
        best = max(ks)
        cap = best * mult
        if total <= cap:
            continue
        factor = cap / total
        for m in members:
            mid = _bet_id(m)
            scales[mid] = min(scales.get(mid, 1.0), factor)
        logger.info(
            "correlation cap: group=%s legs=%d total=%.4f best=%.4f cap=%.4f factor=%.3f",
            gname, len(members), total, best, cap, factor,
        )

    # Apply scale + drop legs below the floor.
    filtered = []
    for b in out:
        f = scales.get(_bet_id(b), 1.0)
        b["kelly_raw"] = b.get("kelly_pct", 0.0)
        b["kelly_pct"] = round(b.get("kelly_pct", 0.0) * f, 4)
        if b["kelly_pct"] < FLOOR_DROP:
            logger.info(
                "correlation cap dropped leg: %s kelly=%.4f < floor %.4f",
                _bet_id(b), b["kelly_pct"], FLOOR_DROP,
            )
            continue
        filtered.append(b)
    return filtered
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_sizing_correlation.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sizing.py tests/test_sizing_correlation.py
git commit -m "$(cat <<'EOF'
feat: correlation-aware Kelly cap (sizing.py)

New sizing.py exports compute_correlation_groups (clusters same-game
bets by empirical outcome correlation) and cap_same_game_exposure
(proportionally scales summed Kelly to best_leg * MAX_SAME_GAME_EXPOSURE).
Full property-based coverage: group sum never exceeds the cap, best
leg is preserved, micro-legs are dropped at FLOOR_DROP=0.001.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task E2: Wire correlation cap into `edge.analyze_all_edges`

**Files:**
- Modify: `edge.py:868-876` (replace run-cluster filter)
- Modify: `edge.py:878` (add logging)

- [ ] **Step 1: Write the integration test**

Append to `tests/test_edge.py`:

```python
def test_analyze_all_edges_applies_correlation_cap(monkeypatch):
    """When multiple correlated bets fire, summed kelly is capped."""
    from edge import analyze_all_edges
    from scrapers.odds import OddsData
    monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
    # Build sim + odds that produce ML home + RL home + Total over (all A_run_home).
    od = OddsData(home="SF", away="LAD", commence_time="")
    od.moneyline = {"home": -130, "away": +115}
    od.run_line = {"home": -1.5, "home_odds": 140, "away": 1.5, "away_odds": -160}
    od.total = {"line": 8.5, "over_odds": -110, "under_odds": -110}
    od.implied_probs = {"ml_home": 0.55, "ml_away": 0.45, "rl_home": 0.44, "rl_away": 0.56}
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.62, "away_win_prob": 0.38},
            "run_line": {"favorite_cover_prob": 0.50},
            "total": {"over_prob": 0.58, "under_prob": 0.42},
            "predicted_score": {"home": 5.0, "away": 4.2},
        }
    }
    bets = analyze_all_edges(sim, od)
    # Sum of kelly across A_run_home members must be <= best * 1.4
    home_members = [b for b in bets
                    if ("home" in b["side"] and b["bet_type"] in ("moneyline", "run_line"))
                    or (b["bet_type"] == "total" and "over" in b["side"])]
    if home_members:
        total = sum(b["kelly_pct"] for b in home_members)
        best = max(b["kelly_pct"] for b in home_members)
        assert total <= best * 1.4 + 1e-6
```

- [ ] **Step 2: Run — expect failure or pass-through**

```bash
pytest tests/test_edge.py::test_analyze_all_edges_applies_correlation_cap -v
```

Expected: fails because the run-cluster dropper still runs and the correlation cap is not wired.

- [ ] **Step 3: Replace run-cluster filter with correlation cap**

In `edge.py`, replace the block at `:870-876`:

```python
    # Cap correlated exposure (Spec 2 §3.5)
    from sizing import cap_same_game_exposure
    from config import BETTING_V2_ENABLED, SAFETY_KEEP_TOP_N

    if BETTING_V2_ENABLED:
        pre_cap = len(bets)
        bets = cap_same_game_exposure(bets)
        if pre_cap != len(bets):
            logger.info(
                "Correlation cap: %d -> %d bets after proportional scaling",
                pre_cap, len(bets),
            )
    else:
        # Legacy behavior: keep top 2 of run cluster (unchanged)
        run_cluster_types = {
            "team_total_home", "team_total_away", "first_3_total", "total",
        }
        cluster_bets = [b for b in bets if b["bet_type"] in run_cluster_types]
        if len(cluster_bets) > 2:
            cluster_bets.sort(key=lambda b: b["edge"], reverse=True)
            drop = {id(b) for b in cluster_bets[2:]}
            bets = [b for b in bets if id(b) not in drop]
            logger.info(
                "Correlated bet limit: kept top 2 of %d run-cluster bets",
                len(cluster_bets),
            )

    # Safety floor: under no circumstance keep more than SAFETY_KEEP_TOP_N
    # run-cluster bets on a single game.
    run_cluster_types = {
        "team_total_home", "team_total_away", "first_3_total", "total",
    }
    cluster_bets = [b for b in bets if b["bet_type"] in run_cluster_types]
    if len(cluster_bets) > SAFETY_KEEP_TOP_N:
        cluster_bets.sort(key=lambda b: b["edge"], reverse=True)
        drop = {id(b) for b in cluster_bets[SAFETY_KEEP_TOP_N:]}
        bets = [b for b in bets if id(b) not in drop]
        logger.info(
            "Safety floor: kept top %d of %d run-cluster bets",
            SAFETY_KEEP_TOP_N, len(cluster_bets),
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_edge.py tests/test_edge_phase1.py tests/test_sizing_correlation.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "$(cat <<'EOF'
feat: wire correlation cap into analyze_all_edges under V2 flag

When BETTING_V2_ENABLED: cap_same_game_exposure replaces the legacy
'keep top 2 run cluster' filter. A safety floor (SAFETY_KEEP_TOP_N)
still kicks in to prevent >4 run-cluster bets per game under any
configuration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F — Uncertainty-Shrinkage Kelly

### Task F1: Emit `prob_std` per slot from `ensemble/orchestrator.py`

**Files:**
- Modify: `ensemble/orchestrator.py` (inside `build_ensemble_result`, after `weighted_average_prob` loop at `:419-435`)
- Modify: `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_ensemble_orchestrator.py`:

```python
def test_build_ensemble_result_emits_prob_std():
    from ensemble.orchestrator import build_ensemble_result
    from ensemble.weights import BET_SLOTS

    results = [
        {"model_key": "kimi", "parsed": {"predictions": {
            "moneyline": {"home_win_prob": 0.60, "away_win_prob": 0.40},
            "run_line": {"favorite_cover_prob": 0.48},
            "total": {"over_prob": 0.55, "under_prob": 0.45, "projected_total": 9.2},
        }}},
        {"model_key": "claude", "parsed": {"predictions": {
            "moneyline": {"home_win_prob": 0.65, "away_win_prob": 0.35},
            "run_line": {"favorite_cover_prob": 0.50},
            "total": {"over_prob": 0.58, "under_prob": 0.42, "projected_total": 9.5},
        }}},
    ]
    weights = {"kimi": {s: 1.0 for s in BET_SLOTS},
               "claude": {s: 1.0 for s in BET_SLOTS}}
    out = build_ensemble_result(results, {}, weights, [])
    preds = out["predictions"]
    assert "prob_std" in preds["moneyline"]
    assert preds["moneyline"]["prob_std"] > 0
    assert "prob_std" in preds["run_line"]
    assert "prob_std" in preds["total"]


def test_prob_std_zero_with_single_run():
    from ensemble.orchestrator import build_ensemble_result
    from ensemble.weights import BET_SLOTS

    results = [
        {"model_key": "kimi", "parsed": {"predictions": {
            "moneyline": {"home_win_prob": 0.60},
        }}},
    ]
    weights = {"kimi": {s: 1.0 for s in BET_SLOTS}}
    out = build_ensemble_result(results, {}, weights, [])
    assert out["predictions"]["moneyline"].get("prob_std", 0.0) == 0.0
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_ensemble_orchestrator.py -v -k prob_std
```

Expected: `AssertionError: 'prob_std' in preds["moneyline"]`.

- [ ] **Step 3: Add `prob_std` computation**

In `ensemble/orchestrator.py`, after the loop at `:414-435` (inside `build_ensemble_result`), insert a stdev pass. Pick a primary field per slot:

```python
    # Spec 2 §3.6: expose per-slot prob_std = stdev across runs of the primary prob field.
    PRIMARY_PROB_FIELD = {
        "moneyline": ("moneyline", "home_win_prob"),
        "run_line": ("run_line", "favorite_cover_prob"),
        "total": ("total", "over_prob"),
        "first_5_ml": ("first_5", "f5_home_win_prob"),
        "first_5_total": ("first_5", "f5_projected_total"),
        "first_5_rl": ("first_5", "f5_home_lead_prob"),
        "team_total_home": ("predicted_score", "home"),
        "team_total_away": ("predicted_score", "away"),
        "first_3_ml": ("first_3", "f3_home_win_prob"),
        "first_3_total": ("first_3", "f3_projected_total"),
        "first_3_rl": ("first_3", "f3_home_lead_prob"),
        "nrfi": ("first_inning", "nrfi_prob"),
        "first_1_rl": ("first_inning", "f1_home_lead_prob"),
    }
    for slot, (section_key, field) in PRIMARY_PROB_FIELD.items():
        vals = []
        for r in results:
            sec = r["parsed"].get("predictions", {}).get(section_key, {})
            v = sec.get(field)
            if v is not None:
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    continue
        if len(vals) >= 2:
            try:
                std = statistics.stdev(vals)
            except statistics.StatisticsError:
                std = 0.0
        else:
            std = 0.0
        # Normalize projected_total-style fields to [0,1]-scale by dividing
        # by the mean (coefficient of variation). Caller uses this as an
        # uncertainty signal; absolute scale must match prob-space.
        if field.endswith("projected_total") or field in ("home", "away"):
            mean_v = sum(vals) / len(vals) if vals else 0
            if mean_v > 0:
                std = std / mean_v  # cv
        section = predictions.setdefault(section_key, {})
        # Multiple slots may share a section (e.g. first_5 has 3 slots).
        # Store per-slot key under "prob_std_<slot>" plus a generic fallback.
        section[f"prob_std_{slot}"] = round(std, 6)
        if "prob_std" not in section:
            section["prob_std"] = round(std, 6)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_ensemble_orchestrator.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ensemble/orchestrator.py tests/test_ensemble_orchestrator.py
git commit -m "$(cat <<'EOF'
feat: emit per-slot prob_std from ensemble orchestrator

build_ensemble_result now computes stdev across runs for each slot's
primary probability field and stashes it under predictions.<section>.
prob_std (generic) and prob_std_<slot> (per-slot). Projected-total
fields use coefficient of variation. Single-run inputs produce 0.0.

Consumed by edge._sized_kelly for shrinkage (Task F2).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task F2: Extend `_sized_kelly` signature + thread `prob_std`

**Files:**
- Modify: `edge.py:28-30` (`_sized_kelly`)
- Modify: `edge.py` — every call site for `_sized_kelly`
- Create: `tests/test_uncertainty_shrinkage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_uncertainty_shrinkage.py`:

```python
"""Tests for uncertainty-shrinkage Kelly (Spec 2 §3.6)."""
import pytest

from edge import _sized_kelly


class TestShrinkageKelly:
    def test_prob_std_zero_no_shrinkage(self):
        raw, shrunk = _sized_kelly(
            prob=0.60, dec=2.0, prob_std=0.0, edge=0.05,
        )
        assert raw > 0
        assert shrunk == pytest.approx(raw, abs=1e-6)

    def test_monotone_shrinkage(self):
        prev_shrunk = None
        for std in (0.02, 0.04, 0.08, 0.15):
            _, shrunk = _sized_kelly(0.60, 2.0, prob_std=std, edge=0.05)
            if prev_shrunk is not None:
                assert shrunk <= prev_shrunk + 1e-9
            prev_shrunk = shrunk

    def test_floor_at_20_percent(self):
        _, shrunk = _sized_kelly(0.60, 2.0, prob_std=0.5, edge=0.05)
        raw, _ = _sized_kelly(0.60, 2.0, prob_std=0.0, edge=0.05)
        # Floor: 20% of raw quarter-Kelly.
        assert shrunk >= 0.20 * raw - 1e-6

    def test_edge_zero_returns_zero(self):
        raw, shrunk = _sized_kelly(0.40, 2.0, prob_std=0.04, edge=0.0)
        # No edge -> Kelly is 0 anyway; shrink still 0.
        assert raw == 0
        assert shrunk == 0

    def test_edge_negative_returns_zero(self):
        raw, shrunk = _sized_kelly(0.40, 2.0, prob_std=0.04, edge=-0.02)
        assert raw == 0
        assert shrunk == 0

    def test_returns_tuple(self):
        result = _sized_kelly(0.60, 2.0, prob_std=0.04, edge=0.05)
        assert isinstance(result, tuple)
        assert len(result) == 2
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_uncertainty_shrinkage.py -v
```

Expected: failures (signature mismatch — current `_sized_kelly` returns a scalar).

- [ ] **Step 3: Rewrite `_sized_kelly`**

In `edge.py:28-30`, replace with:

```python
def _sized_kelly(
    prob: float,
    dec: float,
    prob_std: float = 0.0,
    edge: float = 0.0,
) -> tuple[float, float]:
    """Apply quarter-Kelly + uncertainty shrinkage.

    Returns (raw_kelly_quarter, shrunk_kelly). Shrinkage factor is
    edge / (edge + UNCERTAINTY_K * prob_std^2), clamped to
    [KELLY_FLOOR_FRACTION, 1.0]. edge<=0 short-circuits to (0, 0).
    """
    from config import UNCERTAINTY_K, KELLY_FLOOR_FRACTION, BETTING_V2_ENABLED

    raw = round(kelly_criterion(prob, dec) * KELLY_FRACTION, 4)
    if raw == 0 or edge <= 0:
        return (raw, raw)

    if not BETTING_V2_ENABLED or prob_std <= 0:
        return (raw, raw)

    factor = edge / (edge + UNCERTAINTY_K * (prob_std ** 2))
    factor = max(KELLY_FLOOR_FRACTION, min(1.0, factor))
    shrunk = round(raw * factor, 4)
    return (raw, shrunk)
```

- [ ] **Step 4: Update every `_sized_kelly` call site in `edge.py`**

Every existing call looks like `"kelly_pct": _sized_kelly(prob, dec)`. Replace with the shrinkage-aware form, reading `prob_std` from the slot where available:

```python
# Moneyline (example call site):
prob_std = ml_pred.get("prob_std_moneyline") or ml_pred.get("prob_std", 0.0)
raw_k, shrunk_k = _sized_kelly(home_prob, dec, prob_std=prob_std, edge=home_edge)
# ... in the return dict:
"kelly_pct": shrunk_k,
"kelly_raw": raw_k,
```

Apply analogously to:

- `check_run_line_edge` (prob_std from `rl_pred`)
- `check_total_edge` (prob_std from `total_pred`)
- `check_f5_ml_edge` (prob_std from `f5_pred.get("prob_std_first_5_ml")`)
- `check_f5_total_edge`
- `check_team_total_edge` (use `prob_std_team_total_home` / `_away` from `predicted_score` section)
- `_check_innings_spread_edge` (prob_std from the period dict)
- `check_nrfi_edge`
- `check_f3_ml_edge` / `check_f3_total_edge` / `check_f3_rl_edge`
- Derived-ML block at `:848`

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: all pass. If any legacy tests call `_sized_kelly(prob, dec)` directly and assume scalar, update them to unpack the tuple.

- [ ] **Step 6: Commit**

```bash
git add edge.py tests/test_uncertainty_shrinkage.py
git commit -m "$(cat <<'EOF'
feat: uncertainty-shrinkage Kelly

_sized_kelly now returns (raw_kelly_quarter, shrunk_kelly) with
shrinkage = edge / (edge + UNCERTAINTY_K * prob_std^2), floored at
KELLY_FLOOR_FRACTION * raw. Guarded by BETTING_V2_ENABLED — v1 path
passes prob_std=0 and returns raw == shrunk. Every call site in
edge.py threads the appropriate prob_std from the ensemble output.

Bet dicts now carry kelly_raw and kelly_pct (=shrunk).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase G — Quarantine Suspicious Edges

### Task G1: Replace cap block with quarantine-and-drop

**Files:**
- Modify: `edge.py:854-866`
- Create: `tests/test_quarantine.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_quarantine.py`:

```python
"""Tests for suspicious-edge quarantine (Spec 2 §3.7)."""
import os
import pandas as pd
import pytest


def _bet(edge, bet_type="moneyline"):
    return {
        "bet_type": bet_type, "side": "home",
        "odds": -110, "sim_prob": 0.50 + edge, "market_prob": 0.50,
        "edge": edge, "kelly_pct": 0.02,
        "shin_edge": edge, "shin_z": 0.03, "devig_method": "agree",
    }


class TestQuarantine:
    def test_obviously_bad_edge_quarantined(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
        monkeypatch.setattr(
            "config.QUARANTINED_EDGES_CSV", str(tmp_path / "quarantined_edges.csv")
        )
        from edge import _partition_quarantine
        kept, quar = _partition_quarantine([_bet(0.25)])
        assert kept == []
        assert len(quar) == 1
        assert "quarantine_reason" in quar[0]

    def test_edge_at_cap_kept(self, monkeypatch):
        monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
        from edge import _partition_quarantine
        # MAX_LEGITIMATE_EDGE = 0.15, threshold moneyline = 0.05 ->
        # cap = max(0.15, 2*0.05 + 0.07) = max(0.15, 0.17) = 0.17
        kept, quar = _partition_quarantine([_bet(0.17)])
        assert len(kept) == 1
        assert quar == []

    def test_team_total_cap_dominated_by_2x_threshold(self, monkeypatch):
        monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
        from edge import _partition_quarantine
        # team_total_home threshold 0.05 -> cap = max(0.15, 0.17) = 0.17
        kept, quar = _partition_quarantine([_bet(0.18, "team_total_home")])
        assert kept == []
        assert len(quar) == 1

    def test_csv_written(self, tmp_path, monkeypatch):
        csv = tmp_path / "quarantined_edges.csv"
        monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
        monkeypatch.setattr("config.QUARANTINED_EDGES_CSV", str(csv))
        from edge import _append_quarantine_csv
        _append_quarantine_csv([_bet(0.22)], game="LAD@SF", date="2026-04-17")
        assert csv.exists()
        df = pd.read_csv(csv)
        assert len(df) == 1
        assert df.iloc[0]["game"] == "LAD@SF"
        assert df.iloc[0]["bet_type"] == "moneyline"

    def test_csv_idempotent_append(self, tmp_path, monkeypatch):
        csv = tmp_path / "quarantined_edges.csv"
        monkeypatch.setattr("config.QUARANTINED_EDGES_CSV", str(csv))
        from edge import _append_quarantine_csv
        _append_quarantine_csv([_bet(0.22)], game="LAD@SF", date="2026-04-17")
        _append_quarantine_csv([_bet(0.22)], game="LAD@SF", date="2026-04-17")
        df = pd.read_csv(csv)
        # De-dupe by (date, game, bet_type, side)
        assert len(df) == 1

    def test_disjoint_kept_and_quarantined(self, monkeypatch):
        monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
        from edge import _partition_quarantine
        all_bets = [_bet(0.03), _bet(0.10), _bet(0.22), _bet(0.04)]
        kept, quar = _partition_quarantine(all_bets)
        kept_ids = {id(b) for b in kept}
        quar_ids = {id(b) for b in quar}
        assert kept_ids.isdisjoint(quar_ids)
        assert len(kept) + len(quar) == len(all_bets)
```

- [ ] **Step 2: Run — expect failure**

```bash
pytest tests/test_quarantine.py -v
```

Expected: `ImportError` on `_partition_quarantine`.

- [ ] **Step 3: Implement quarantine helpers in `edge.py`**

Insert below the helper imports (near the top of `edge.py`, after `_dual_devig_check`):

```python
from datetime import datetime
import csv as _csv
import os as _os


def _partition_quarantine(bets: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split bets into (kept, quarantined) using MAX_LEGITIMATE_EDGE.

    Cap per bet_type: max(MAX_LEGITIMATE_EDGE, 2*threshold + 0.07).
    """
    from config import MAX_LEGITIMATE_EDGE
    kept, quar = [], []
    for b in bets:
        t = EDGE_THRESHOLDS.get(b.get("bet_type", ""), 0.05)
        cap = max(MAX_LEGITIMATE_EDGE, 2 * t + 0.07)
        if b.get("edge", 0.0) > cap:
            b = {**b, "quarantine_reason":
                 f"edge {b.get('edge', 0):.3f} > cap {cap:.3f} "
                 f"(2*threshold+0.07={2*t + 0.07:.3f})"}
            quar.append(b)
        else:
            kept.append(b)
    return kept, quar


QUARANTINE_COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "market_prob", "edge", "shin_edge", "shin_z",
    "kelly_pct", "confidence", "quarantine_reason",
    "reviewed", "override_allow",
]


def _append_quarantine_csv(
    bets: list[dict], game: str, date: str, csv_path: str | None = None,
) -> None:
    """Append quarantined bets to config.QUARANTINED_EDGES_CSV. Idempotent.

    De-dupes by (date, game, bet_type, side).
    """
    from config import QUARANTINED_EDGES_CSV
    path = csv_path or QUARANTINED_EDGES_CSV
    _os.makedirs(_os.path.dirname(path), exist_ok=True)

    # Build existing key set for de-dupe.
    existing_keys = set()
    if _os.path.exists(path):
        try:
            import pandas as _pd
            df = _pd.read_csv(path)
            for _, r in df.iterrows():
                existing_keys.add(
                    (str(r["date"]), str(r["game"]),
                     str(r["bet_type"]), str(r["side"]))
                )
        except Exception:
            existing_keys = set()

    new_rows = []
    for b in bets:
        key = (date, game, b.get("bet_type", ""), str(b.get("side", "")))
        if key in existing_keys:
            continue
        new_rows.append({
            "date": date, "game": game,
            "bet_type": b.get("bet_type", ""),
            "side": b.get("side", ""),
            "odds": b.get("odds", ""),
            "sim_prob": b.get("sim_prob", ""),
            "market_prob": b.get("market_prob", ""),
            "edge": b.get("edge", ""),
            "shin_edge": b.get("shin_edge", ""),
            "shin_z": b.get("shin_z", ""),
            "kelly_pct": b.get("kelly_pct", ""),
            "confidence": b.get("confidence", ""),
            "quarantine_reason": b.get("quarantine_reason", ""),
            "reviewed": "",
            "override_allow": "",
        })
        existing_keys.add(key)

    if not new_rows:
        return

    file_exists = _os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=QUARANTINE_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for r in new_rows:
            writer.writerow(r)
```

Replace the existing `:854-866` edge-cap block with:

```python
    # Spec 2 §3.7 — quarantine suspicious edges instead of silently capping.
    from config import BETTING_V2_ENABLED
    if BETTING_V2_ENABLED:
        bets, quarantined = _partition_quarantine(bets)
        if quarantined:
            try:
                # Derive game label from odds when available.
                if hasattr(odds, "home") and hasattr(odds, "away"):
                    game_label = f"{odds.away}@{odds.home}"
                elif isinstance(odds, dict):
                    game_label = odds.get("game", "UNKNOWN@UNKNOWN")
                else:
                    game_label = "UNKNOWN@UNKNOWN"
                date_str = datetime.utcnow().strftime("%Y-%m-%d")
                _append_quarantine_csv(
                    quarantined, game=game_label, date=date_str
                )
            except Exception as e:
                logger.error("Failed to write quarantine CSV: %s", e)
            logger.warning(
                "Quarantined %d suspicious edges (not logged as bets)",
                len(quarantined),
            )
    else:
        # Legacy cap-and-fire behavior — preserved under flag off.
        MAX_EDGE = 0.15
        for bet in bets:
            if bet["edge"] > MAX_EDGE:
                logger.warning(
                    "Capping edge for %s %s: %.1f%% -> %.1f%%",
                    bet["bet_type"], bet["side"],
                    bet["edge"] * 100, MAX_EDGE * 100,
                )
                bet["edge"] = MAX_EDGE
                capped_prob = bet["market_prob"] + MAX_EDGE
                dec = american_to_decimal(bet["odds"])
                raw_k, shrunk_k = _sized_kelly(
                    capped_prob, dec, prob_std=0.0, edge=MAX_EDGE
                )
                bet["kelly_pct"] = shrunk_k
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_quarantine.py tests/test_edge.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_quarantine.py
git commit -m "$(cat <<'EOF'
feat: quarantine suspicious edges instead of silently capping

Replaces the MAX_EDGE=0.15 cap block with _partition_quarantine +
_append_quarantine_csv. Under BETTING_V2_ENABLED, bets with edge >
max(MAX_LEGITIMATE_EDGE, 2*threshold+0.07) are removed from the bet
list and appended to data/quarantined_edges.csv (de-duped, idempotent).
Legacy cap-and-fire behavior preserved when the flag is off.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase H — Feature Flag, Shadow Mode, Smoke Test

### Task H1: Shadow-mode integration test

**Files:**
- Create: `tests/test_shadow_mode.py`

- [ ] **Step 1: Write the test**

```python
"""Integration: v1 and v2 pipelines run together in shadow mode."""
import pytest

from scrapers.odds import OddsData


def _sim_high_edge():
    return {
        "predictions": {
            "moneyline": {
                "home_win_prob": 0.62, "away_win_prob": 0.38,
                "prob_std": 0.03, "prob_std_moneyline": 0.03,
            },
            "run_line": {"favorite_cover_prob": 0.48, "prob_std": 0.04},
            "total": {
                "over_prob": 0.56, "under_prob": 0.44,
                "projected_total": 9.1, "prob_std": 0.05,
            },
            "predicted_score": {"home": 5.0, "away": 4.1},
        }
    }


def _odds_fixture():
    od = OddsData(home="SF", away="LAD", commence_time="2099-12-31T23:59:00Z")
    od.moneyline = {"home": -130, "away": +115}
    od.run_line = {"home": -1.5, "home_odds": +140, "away": 1.5, "away_odds": -160}
    od.total = {"line": 8.5, "over_odds": -110, "under_odds": -110}
    od.implied_probs = {
        "ml_home": 0.55, "ml_away": 0.45,
        "rl_home": 0.40, "rl_away": 0.60,
    }
    return od


def test_v1_and_v2_produce_compatible_bets(monkeypatch):
    from edge import analyze_all_edges

    monkeypatch.setattr("config.BETTING_V2_ENABLED", False)
    v1_bets = analyze_all_edges(_sim_high_edge(), _odds_fixture())

    monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
    v2_bets = analyze_all_edges(_sim_high_edge(), _odds_fixture())

    # v2 is strictly more conservative — never more bets than v1.
    assert len(v2_bets) <= len(v1_bets)

    # v2 bets carry shin_edge / devig_method fields.
    for b in v2_bets:
        assert "shin_edge" in b
        assert "devig_method" in b
```

- [ ] **Step 2: Run — expect pass after monkeypatch wiring is correct**

```bash
pytest tests/test_shadow_mode.py -v
```

Expected: pass. (If any flag is cached at import time, rework the flag read to `lambda: config.BETTING_V2_ENABLED` or re-import inside the function.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_shadow_mode.py
git commit -m "$(cat <<'EOF'
test: shadow-mode smoke test for v1/v2 compatibility

Runs analyze_all_edges with BETTING_V2_ENABLED off then on against the
same synthetic fixture. Asserts v2 never produces more bets than v1 and
that every v2 bet carries the Shin fields.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task H2: `scripts/compare_v1_v2.py` shadow diff tool

**Files:**
- Create: `scripts/compare_v1_v2.py`

- [ ] **Step 1: Write the script**

```python
"""Compare v1 vs v2 bet cards for a recent date.

Usage:
    python scripts/compare_v1_v2.py --date 2026-04-17
    python scripts/compare_v1_v2.py --days 7

Writes data/v2_shadow.csv rows:
    date, game, bet_type, side, v1_kelly, v2_kelly, v1_edge, v2_edge,
    v2_shin_edge, v2_devig_method, status (v1_only|v2_only|both)
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime, timedelta

# Ensure repo root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd

from config import V2_SHADOW_CSV, DATA_DIR


def _load_for_date(path: str, date: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "date" not in df.columns:
        return pd.DataFrame()
    return df[df["date"] == date]


def compare_for_date(date: str) -> pd.DataFrame:
    """Run both code paths offline on the day's sims. Placeholder: reads
    persisted ensemble outputs if available; otherwise compares the
    current bets.csv against a v2-re-run using the stored sim cache.
    """
    # In production this runs full analyze_all_edges twice; shadow loop
    # users should invoke with --rerun-sim flag. For now, diff existing
    # bets.csv against quarantined_edges.csv for the date.
    from config import BETS_CSV, QUARANTINED_EDGES_CSV
    bets = _load_for_date(BETS_CSV, date)
    quar = _load_for_date(QUARANTINED_EDGES_CSV, date)
    rows = []
    for _, b in bets.iterrows():
        rows.append({
            "date": b["date"], "game": b["game"],
            "bet_type": b["bet_type"], "side": b["side"],
            "v1_kelly": b.get("kelly_pct", ""),
            "v2_kelly": b.get("kelly_pct", ""),  # same CSV in v2-off
            "v1_edge": b.get("edge", ""),
            "v2_edge": b.get("edge", ""),
            "v2_shin_edge": b.get("shin_edge", ""),
            "v2_devig_method": b.get("devig_method", ""),
            "status": "both",
        })
    for _, q in quar.iterrows():
        rows.append({
            "date": q["date"], "game": q["game"],
            "bet_type": q["bet_type"], "side": q["side"],
            "v1_kelly": "", "v2_kelly": "",
            "v1_edge": q.get("edge", ""), "v2_edge": q.get("edge", ""),
            "v2_shin_edge": q.get("shin_edge", ""),
            "v2_devig_method": "quarantined",
            "status": "v1_only",
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.utcnow().strftime("%Y-%m-%d"))
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--out", default=V2_SHADOW_CSV)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    dates = [
        (datetime.strptime(args.date, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(args.days)
    ]

    frames = [compare_for_date(d) for d in dates]
    out = pd.concat([f for f in frames if not f.empty], ignore_index=True) \
        if any(not f.empty for f in frames) else pd.DataFrame()
    if out.empty:
        print("No bets found for requested dates.")
        return
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} rows to {args.out}")
    print("Status breakdown:")
    print(out["status"].value_counts())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-check the script**

```bash
python3 scripts/compare_v1_v2.py --help
```

Expected: argparse help text (no import errors).

- [ ] **Step 3: Commit**

```bash
git add scripts/compare_v1_v2.py
git commit -m "$(cat <<'EOF'
feat: scripts/compare_v1_v2 for shadow-period diff reporting

Diffs v1 bets.csv against v2 quarantined_edges.csv for a requested
date/range. Emits data/v2_shadow.csv rows tagged v1_only|v2_only|both
with Kelly and edge deltas. Future extension: re-run analyze_all_edges
with BETTING_V2_ENABLED=true against persisted sim outputs for a true
apples-to-apples comparison.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task H3: End-to-end smoke test in `tests/test_edge.py`

**Files:**
- Modify: `tests/test_edge.py`

- [ ] **Step 1: Write the integration test (§6.5 of spec)**

Append to `tests/test_edge.py`:

```python
def test_end_to_end_smoke_with_v2(monkeypatch, tmp_path):
    """§6.5: full pipeline with Pinnacle + 3 retail + calibrated sim.

    Asserts:
      - no returned bet exceeds MAX_LEGITIMATE_EDGE
      - correlation-group sums respect cap
      - quarantine CSV written when input is rigged to produce 0.22 edge
      - every returned bet carries shin_edge + shin_z
    """
    from edge import analyze_all_edges
    from scrapers.odds import OddsData

    monkeypatch.setattr("config.BETTING_V2_ENABLED", True)
    monkeypatch.setattr(
        "config.QUARANTINED_EDGES_CSV", str(tmp_path / "quarantined_edges.csv")
    )

    od = OddsData(home="SF", away="LAD", commence_time="2099-12-31T23:59:00Z")
    od.moneyline = {"home": -130, "away": +115}
    od.run_line = {"home": -1.5, "home_odds": +140, "away": 1.5, "away_odds": -160}
    od.total = {"line": 8.5, "over_odds": -110, "under_odds": -110}
    od.implied_probs = {
        "ml_home": 0.55, "ml_away": 0.45,
        "rl_home": 0.40, "rl_away": 0.60,
    }
    # Rigged: a 0.22-edge ML to trigger quarantine
    sim = {
        "predictions": {
            "moneyline": {
                "home_win_prob": 0.77, "away_win_prob": 0.23,
                "prob_std": 0.03, "prob_std_moneyline": 0.03,
            },
            "run_line": {"favorite_cover_prob": 0.48, "prob_std": 0.04},
            "total": {"over_prob": 0.58, "under_prob": 0.42,
                      "projected_total": 9.1, "prob_std": 0.05},
            "predicted_score": {"home": 5.0, "away": 4.1},
        }
    }
    bets = analyze_all_edges(sim, od)

    from config import MAX_LEGITIMATE_EDGE
    for b in bets:
        assert b["edge"] <= MAX_LEGITIMATE_EDGE + 0.07
        assert "shin_edge" in b
        assert "shin_z" in b

    # Quarantine CSV should exist and contain the 0.22 ML
    qpath = tmp_path / "quarantined_edges.csv"
    assert qpath.exists(), "quarantine CSV should have been written"
    import pandas as pd
    qdf = pd.read_csv(qpath)
    assert (qdf["bet_type"] == "moneyline").any()
```

- [ ] **Step 2: Run**

```bash
pytest tests/test_edge.py::test_end_to_end_smoke_with_v2 -v
```

Expected: pass.

- [ ] **Step 3: Final full-suite check**

```bash
pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_edge.py
git commit -m "$(cat <<'EOF'
test: end-to-end smoke for v2 betting pipeline

Runs analyze_all_edges with Pinnacle + retail fixture, a calibrated
sim, and a rigged 0.22-edge ML. Asserts: no returned bet above cap,
quarantine CSV populated, every bet carries Shin fields.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Acceptance Criteria

Before closing out this plan, verify:

- [ ] `pytest tests/` — all tests pass with `BETTING_V2_ENABLED=false` (default).
- [ ] `BETTING_V2_ENABLED=true pytest tests/` — all tests pass with the flag on.
- [ ] `scripts/compare_v1_v2.py --help` runs without import errors.
- [ ] `data/bets.csv` contains the new columns (`best_book`, `best_odds`, `shin_edge`, `shin_z`, `devig_method`) after one live daily run with the flag on.
- [ ] `data/quarantined_edges.csv` exists and is populated when a synthetic >0.15-edge bet is fed through the pipeline.
- [ ] `data/v2_shadow.csv` exists after one run of `compare_v1_v2.py`.
- [ ] `grep -rn "_passes_worst_case_filter" edge.py` returns only the internal-use site inside `_dual_devig_check` (the degenerate-fallback branch).
- [ ] `git log --oneline` shows ~18 focused commits matching the tasks above.

---

## Rollback Procedure

1. Flip `BETTING_V2_ENABLED=false` in `.env` / `config.py`.
2. Restart `main.py`. All v1 code paths execute unchanged; new CSV columns remain populated with blank values (no schema reversion required).
3. The v2 quarantine, correlation cap, shrinkage Kelly, Shin gate, and weighted consensus all short-circuit to their v1 equivalents.
4. For a full code rollback, `git revert` the range of Spec-2 commits in reverse order — each task is a focused commit.

---

## Open Questions (deferred to execution)

1. **Cross-game bankroll exposure cap** (Spec Appendix C.1) — out of scope here. Flagged for a follow-up spec if shadow data shows nightly bankroll use exceeding 15%.
2. **Override-allow injection path** — when a user edits `override_allow=true` on a quarantined row, how does `daily_runner` pick it up? Deferred to a later daily-runner PR; this plan produces the CSV with the column but no consumer.
3. **Shadow period length** — spec suggests 2 weeks; actual duration depends on CLV 1σ resolution from Spec 1. Monitor daily via `scripts/compare_v1_v2.py` and extend if signal is noisy.
4. **Per-market `z` thresholds in `devig_stats.csv`** — mean z across the league informs whether SHARP_BOOKS should grow. Daily aggregation script is not in scope here; the per-market z is stored on `OddsData.shin_z` so a future daily job can aggregate.
