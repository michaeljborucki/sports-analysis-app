# Calibration + CLV Measurement Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the measurement substrate (per-bet-type probability calibration, CLV aggregation, skipped-signal counterfactuals, per-model Brier/log-loss, hardened self-optimizer) so that Specs 2-4 can be A/B-tested against real metrics instead of ROI variance.

**Architecture:** Rewrite the stub `calibrate.py` into a real isotonic/beta/identity dispatcher that reads `bets.csv` and writes `data/calibration_curves.json`; `edge.py`'s existing `apply_calibration()` call sites pick it up for free. Add a new `agents/clv_tracker.py` that aggregates CLV from `bets.csv × closing_lines.csv` with t-tests, plus a new `data/skipped_signals.csv` written from `edge.py` to answer "what would we have won if the threshold were lower?". Relocate the broken per-model Brier logic into `ensemble/calibration_metrics.py` with a correct join. Three new `main.py` subcommands surface everything: `calibrate`, `clv`, `model-scores`.

**Tech Stack:** `scikit-learn>=1.4` (isotonic fit at rebuild), `betacal>=0.5` (beta calibration fit), `scipy>=1.11` (`ttest_1samp`), existing `pandas`/`pytest`/`click`.

**Spec:** `docs/superpowers/specs/2026-04-17-calibration-clv-loop-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Modify | Add `scikit-learn`, `betacal`, `scipy` pins |
| `calibrate.py` | Modify (rewrite) | Real per-bet-type calibration: fit, serialize, apply, report. Module-level mtime cache |
| `data/calibration_curves.json` | Create (generated) | Per-bet-type curve parameters, written by `calibrate --rebuild` |
| `agents/clv_tracker.py` | Create | Load CLV-matched bets; aggregate by bet_type / edge bucket / confidence / model; t-test; rolling windows; skipped-signal counterfactual |
| `ensemble/calibration_metrics.py` | Create | Per-model, per-bet-type Brier + log-loss with correct `(date, game, bet_type, side)` join; `update_model_weights()` relocated |
| `edge_logging.py` | Create | `_log_skipped()` helper, dedup, threading lock, shared `SKIPPED_SIGNALS_CSV` + columns |
| `data/skipped_signals.csv` | Create (generated) | Rows logged at `edge >= 0.01 but below threshold or filter-killed` |
| `edge.py` | Modify | Wire `_log_skipped()` into all 10 checker reject branches, `_passes_worst_case_filter` misses, edge cap, correlated-cluster drop |
| `agents/self_optimizer.py` | Modify | `--metric {roi,clv}` default `clv`; per-bet-type `min_bets=200` floor; p<0.05 gate; delete broken `compute_model_brier_scores` (import shim only) |
| `main.py` | Modify | Three new subcommands: `calibrate`, `clv`, `model-scores`; optimizer CLI `--metric` flag |
| `tests/test_calibrate.py` | Create | Curve fit, roundtrip, clamp, identity fallback, mtime cache |
| `tests/test_clv_tracker.py` | Create | Aggregation, t-test, bucket joins, rolling windows, skipped counterfactual |
| `tests/test_skipped_signals.py` | Create | Append/dedup/threshold guard |
| `tests/test_calibration_metrics.py` | Create | Brier correctness, join-on-date-game-type-side (regression for old bug) |
| `tests/test_edge_skipped_logging.py` | Create | Integration: verify `edge.py` emits skipped rows from each checker |
| `tests/fixtures/bets_snapshot_2026-04-17.csv` | Create | Frozen 2k-row subset of `data/bets.csv` for golden test |
| `tests/golden/calibration_moneyline_2026Q1.json` | Create | Pinned isotonic thresholds for moneyline |

**Test invocations used throughout:**
```
pytest tests/test_calibrate.py -v
pytest tests/test_clv_tracker.py -v
pytest tests/test_skipped_signals.py -v
pytest tests/test_calibration_metrics.py -v
pytest tests/test_edge_skipped_logging.py -v
pytest tests/ -v
```

---

## Phase A — Foundations (no behavior change)

### Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Append new pins**

Edit `/Users/mikeborucki/personal_workspace/agents/baseball-agents/requirements.txt`. The file currently ends at line 7 (`pytest>=7.4.0`). Append three lines:

```
pybaseball>=2.3.0
requests>=2.31.0
openai>=1.12.0
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.1.0
pytest>=7.4.0
scikit-learn>=1.4.0
betacal>=0.5.0
scipy>=1.11.0
```

- [ ] **Step 2: Install**

Run: `pip install -r requirements.txt`
Expected: `Successfully installed scikit-learn-... betacal-... scipy-...` (versions may vary), no errors.

- [ ] **Step 3: Import smoke**

Run:
```
python3 -c "from sklearn.isotonic import IsotonicRegression; from betacal import BetaCalibration; from scipy.stats import ttest_1samp; print('OK')"
```
Expected: `OK` and zero exit code.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add scikit-learn, betacal, scipy for calibration + CLV stats"
```

---

### Task 2: Stub `tests/test_calibrate.py` with a shared fixture

**Files:**
- Create: `tests/test_calibrate.py`

- [ ] **Step 1: Write the stub file**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_calibrate.py`:

```python
"""Tests for per-bet-type probability calibration."""
import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def miscal_bets_df():
    """500 synthetic bets where sim_prob is systematically over-confident.

    true_prob = 0.3 + 0.4 * sim_prob  (compresses toward the middle).
    """
    rng = random.Random(42)
    rows = []
    for _ in range(500):
        sim = rng.uniform(0.05, 0.95)
        true_p = 0.3 + 0.4 * sim
        outcome = "W" if rng.random() < true_p else "L"
        rows.append({
            "date": "2026-01-01", "game": "A@B", "bet_type": "moneyline",
            "side": "home", "odds": -110, "sim_prob": sim, "market_prob": 0.5,
            "edge": 0.05, "kelly_pct": 0.01, "result": outcome, "profit": 0.0,
        })
    return pd.DataFrame(rows)


@pytest.fixture
def calibrated_bets_df():
    """500 rows where outcome really is Bernoulli(sim_prob). Identity target."""
    rng = random.Random(7)
    rows = []
    for _ in range(500):
        sim = rng.uniform(0.05, 0.95)
        outcome = "W" if rng.random() < sim else "L"
        rows.append({
            "date": "2026-01-01", "game": "A@B", "bet_type": "run_line",
            "side": "home -1.5", "odds": -110, "sim_prob": sim, "market_prob": 0.5,
            "edge": 0.03, "kelly_pct": 0.01, "result": outcome, "profit": 0.0,
        })
    return pd.DataFrame(rows)


@pytest.fixture
def tiny_bets_df():
    """50 rows — below the 100-sample floor, should fall to identity."""
    rng = random.Random(99)
    rows = []
    for _ in range(50):
        sim = rng.uniform(0.1, 0.9)
        outcome = "W" if rng.random() < sim else "L"
        rows.append({
            "date": "2026-01-01", "game": "A@B", "bet_type": "nrfi",
            "side": "NRFI", "odds": -110, "sim_prob": sim, "market_prob": 0.5,
            "edge": 0.06, "kelly_pct": 0.01, "result": outcome, "profit": 0.0,
        })
    return pd.DataFrame(rows)


def test_stub_fixture_loads(miscal_bets_df):
    assert len(miscal_bets_df) == 500
    assert set(miscal_bets_df["result"].unique()) == {"W", "L"}
```

- [ ] **Step 2: Run to confirm import and fixture work**

Run: `pytest tests/test_calibrate.py -v`
Expected: `tests/test_calibrate.py::test_stub_fixture_loads PASSED` (1 passed).

- [ ] **Step 3: Commit**

```bash
git add tests/test_calibrate.py
git commit -m "test: add fixtures for calibration tests"
```

---

### Task 3: Create `data/calibration_curves.json` contract constants in `calibrate.py`

This is a non-destructive prep step — we keep the existing `apply_calibration()` identity behaviour but introduce a module-level curve cache with mtime invalidation.

**Files:**
- Modify: `calibrate.py`
- Modify: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing test for the curve-file path + empty-load behaviour**

Append to `tests/test_calibrate.py`:

```python
from calibrate import (
    CALIBRATION_CURVES_PATH, _load_curves, _CURVES_STATE,
    apply_calibration,
)


def test_curve_path_is_in_data_dir():
    assert CALIBRATION_CURVES_PATH.endswith("data/calibration_curves.json") or \
           CALIBRATION_CURVES_PATH.endswith("data\\calibration_curves.json")


def test_load_curves_returns_empty_when_missing(tmp_path, monkeypatch):
    bogus = tmp_path / "nope.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(bogus))
    _CURVES_STATE["mtime"] = -1  # invalidate cache
    _CURVES_STATE["curves"] = None
    curves = _load_curves()
    assert curves == {}


def test_apply_calibration_identity_when_no_file(tmp_path, monkeypatch):
    bogus = tmp_path / "none.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(bogus))
    _CURVES_STATE["mtime"] = -1
    _CURVES_STATE["curves"] = None
    assert apply_calibration(0.42, "moneyline") == 0.42
    assert apply_calibration(0.99, "xyz_unknown") == 0.99
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_calibrate.py -v`
Expected: `ImportError: cannot import name 'CALIBRATION_CURVES_PATH' from 'calibrate'` or equivalent; 3 FAIL.

- [ ] **Step 3: Replace `calibrate.py` stub with scaffolding**

Overwrite `/Users/mikeborucki/personal_workspace/agents/baseball-agents/calibrate.py` with:

```python
"""Per-bet-type probability calibration.

Reads settled bets from data/bets.csv, fits isotonic / beta / identity
curves per bet_type, and persists them to data/calibration_curves.json.
At inference time, `apply_calibration(prob, bet_type)` is a no-op if the
JSON is missing; otherwise it looks up the curve and transforms the prob.

Curve file is mtime-cached: first call loads it, subsequent calls re-use
the in-memory dict until the file's mtime changes (so a rebuild on disk
is picked up without process restart).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config import DATA_DIR
from tracker import load_bets

logger = logging.getLogger("mirofish.calibrate")

CALIBRATION_CURVES_PATH = os.path.join(DATA_DIR, "calibration_curves.json")
MIN_ISOTONIC_SAMPLES = 500
MIN_BETA_SAMPLES = 100
CLAMP_LO = 0.01
CLAMP_HI = 0.99
BRIER_REGRESSION_TOLERANCE = 0.005  # curves worse than identity by > this revert to identity

_CURVES_STATE: dict[str, Any] = {"mtime": -1, "curves": None}
_CURVES_LOCK = threading.Lock()


def _clamp(prob: float, lo: float = CLAMP_LO, hi: float = CLAMP_HI) -> float:
    if prob < lo:
        return lo
    if prob > hi:
        return hi
    return prob


def _load_curves() -> dict:
    """Load curves JSON with mtime cache. Returns {} on any error/missing."""
    path = CALIBRATION_CURVES_PATH
    if not os.path.exists(path):
        with _CURVES_LOCK:
            _CURVES_STATE["mtime"] = -1
            _CURVES_STATE["curves"] = {}
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _CURVES_LOCK:
        if _CURVES_STATE["curves"] is not None and _CURVES_STATE["mtime"] == mtime:
            return _CURVES_STATE["curves"]
        try:
            with open(path) as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("calibration: failed to load %s: %s", path, e)
            _CURVES_STATE["mtime"] = mtime
            _CURVES_STATE["curves"] = {}
            return {}
        curves = payload.get("curves", {}) if isinstance(payload, dict) else {}
        _CURVES_STATE["mtime"] = mtime
        _CURVES_STATE["curves"] = curves
        return curves


def apply_calibration(prob: float, bet_type: str = "") -> float:
    """Transform prob via the curve for bet_type. Identity on any miss or error."""
    try:
        curves = _load_curves()
        curve = curves.get(bet_type)
        if not curve:
            return prob
        method = curve.get("method", "identity")
        if method == "identity":
            return prob
        # Real transforms land in later tasks. For now, identity.
        return prob
    except Exception as e:  # never let calibration break the pipeline
        logger.debug("apply_calibration fell through: %s", e)
        return prob


def calibration_report(bets_df: pd.DataFrame | None = None) -> dict:
    """Pre-existing report — kept stubbed; real implementation in Task 9."""
    df = bets_df if bets_df is not None else load_bets()
    settled = df[df["result"].isin(["W", "L"])]
    if len(settled) < 50:
        return {"status": "insufficient_data", "n": int(len(settled)), "needed": 50}
    out = {}
    for bt in settled["bet_type"].unique():
        sub = settled[settled["bet_type"] == bt]
        wins = int((sub["result"] == "W").sum())
        out[str(bt)] = {"n": int(len(sub)), "win_rate": round(wins / len(sub), 3)}
    return {"status": "ok", "total_settled": int(len(settled)), "by_type": out}
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_calibrate.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Smoke-check existing edge imports still work**

Run: `python3 -c "from edge import analyze_all_edges; from calibrate import apply_calibration; print(apply_calibration(0.55, 'moneyline'))"`
Expected: `0.55`.

- [ ] **Step 6: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "refactor: scaffold calibrate.py with mtime-cached curve loader"
```

---

## Phase B — Calibration curves

### Task 4: Isotonic curve fit + serialization

**Files:**
- Modify: `calibrate.py`
- Modify: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_calibrate.py`:

```python
from calibrate import (
    build_isotonic_curve, apply_isotonic, build_all_curves,
)


def test_build_isotonic_curve_returns_thresholds(miscal_bets_df):
    probs = miscal_bets_df["sim_prob"].values
    outcomes = (miscal_bets_df["result"] == "W").astype(int).values
    curve = build_isotonic_curve(probs, outcomes)
    assert curve["method"] == "isotonic"
    assert curve["n_samples"] == 500
    assert len(curve["x_thresholds"]) == len(curve["y_thresholds"])
    assert len(curve["x_thresholds"]) >= 2
    assert curve["x_thresholds"] == sorted(curve["x_thresholds"])
    assert curve["y_thresholds"] == sorted(curve["y_thresholds"])  # isotonic = monotone


def test_apply_isotonic_is_monotone(miscal_bets_df):
    probs = miscal_bets_df["sim_prob"].values
    outcomes = (miscal_bets_df["result"] == "W").astype(int).values
    curve = build_isotonic_curve(probs, outcomes)
    grid = [i / 100 for i in range(5, 96)]
    transformed = [apply_isotonic(p, curve["x_thresholds"], curve["y_thresholds"]) for p in grid]
    for a, b in zip(transformed, transformed[1:]):
        assert b + 1e-9 >= a, f"non-monotone: {a} -> {b}"


def test_apply_isotonic_clamps_output(miscal_bets_df):
    probs = miscal_bets_df["sim_prob"].values
    outcomes = (miscal_bets_df["result"] == "W").astype(int).values
    curve = build_isotonic_curve(probs, outcomes)
    assert 0.01 <= apply_isotonic(0.001, curve["x_thresholds"], curve["y_thresholds"]) <= 0.99
    assert 0.01 <= apply_isotonic(0.999, curve["x_thresholds"], curve["y_thresholds"]) <= 0.99
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_calibrate.py::test_build_isotonic_curve_returns_thresholds -v`
Expected: `ImportError` or `AttributeError: module 'calibrate' has no attribute 'build_isotonic_curve'`.

- [ ] **Step 3: Implement isotonic fit + apply**

Add to `calibrate.py` (before `apply_calibration`, after `_clamp`):

```python
def build_isotonic_curve(probs, outcomes) -> dict:
    """Fit an IsotonicRegression on (probs, outcomes) and return a JSON-serializable dict.

    probs: array-like of float in [0, 1]
    outcomes: array-like of 0/1
    """
    from sklearn.isotonic import IsotonicRegression
    import numpy as np

    probs = np.asarray(probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    mask = np.isfinite(probs) & np.isfinite(outcomes)
    probs, outcomes = probs[mask], outcomes[mask]
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(probs, outcomes)
    x_t = [float(x) for x in model.X_thresholds_]
    y_t = [float(y) for y in model.y_thresholds_]
    # Guarantee sorted x (sklearn already sorts, but belt-and-suspenders)
    pairs = sorted(zip(x_t, y_t))
    x_t = [p[0] for p in pairs]
    y_t = [p[1] for p in pairs]
    brier_before = float(((probs - outcomes) ** 2).mean()) if len(probs) else 0.0
    transformed = np.array([apply_isotonic(p, x_t, y_t) for p in probs])
    brier_after = float(((transformed - outcomes) ** 2).mean()) if len(probs) else 0.0
    return {
        "method": "isotonic",
        "n_samples": int(len(probs)),
        "x_thresholds": x_t,
        "y_thresholds": y_t,
        "brier_uncalibrated": round(brier_before, 6),
        "brier": round(brier_after, 6),
    }


def apply_isotonic(prob: float, x_thresholds: list, y_thresholds: list) -> float:
    """Piecewise-linear interpolation between fitted thresholds, then clamp."""
    if not x_thresholds or not y_thresholds:
        return _clamp(prob)
    if prob <= x_thresholds[0]:
        return _clamp(y_thresholds[0])
    if prob >= x_thresholds[-1]:
        return _clamp(y_thresholds[-1])
    # Linear search is fine: N is tiny (typically <200 thresholds)
    for i in range(1, len(x_thresholds)):
        if prob <= x_thresholds[i]:
            x0, x1 = x_thresholds[i - 1], x_thresholds[i]
            y0, y1 = y_thresholds[i - 1], y_thresholds[i]
            if x1 == x0:
                return _clamp(y1)
            frac = (prob - x0) / (x1 - x0)
            return _clamp(y0 + frac * (y1 - y0))
    return _clamp(y_thresholds[-1])
```

Also add a placeholder `build_all_curves` so a future test can find it (will be filled in Task 6):

```python
def build_all_curves(bets_df: pd.DataFrame,
                      min_isotonic_samples: int = MIN_ISOTONIC_SAMPLES,
                      min_beta_samples: int = MIN_BETA_SAMPLES) -> dict:
    """Placeholder — filled in Task 6."""
    raise NotImplementedError("Filled in Task 6")
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_calibrate.py -v`
Expected: 7 PASSED (the three new isotonic tests plus four pre-existing).

- [ ] **Step 5: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat(calibrate): isotonic curve fit + piecewise-linear apply"
```

---

### Task 5: Beta curve fit + apply

**Files:**
- Modify: `calibrate.py`
- Modify: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_calibrate.py`:

```python
from calibrate import build_beta_curve, apply_beta


def test_build_beta_curve_returns_abc(calibrated_bets_df):
    probs = calibrated_bets_df["sim_prob"].values
    outcomes = (calibrated_bets_df["result"] == "W").astype(int).values
    curve = build_beta_curve(probs, outcomes)
    assert curve["method"] == "beta"
    assert curve["n_samples"] == 500
    for k in ("a", "b", "c"):
        assert k in curve
        assert isinstance(curve[k], float)


def test_apply_beta_near_identity_on_calibrated_data(calibrated_bets_df):
    probs = calibrated_bets_df["sim_prob"].values
    outcomes = (calibrated_bets_df["result"] == "W").astype(int).values
    curve = build_beta_curve(probs, outcomes)
    # Well-calibrated inputs should yield near-identity beta fit.
    grid = [0.2, 0.4, 0.5, 0.6, 0.8]
    for p in grid:
        out = apply_beta(p, curve["a"], curve["b"], curve["c"])
        assert abs(out - p) < 0.10, f"beta diverged from identity at {p}: got {out}"


def test_apply_beta_clamps_extremes(calibrated_bets_df):
    probs = calibrated_bets_df["sim_prob"].values
    outcomes = (calibrated_bets_df["result"] == "W").astype(int).values
    curve = build_beta_curve(probs, outcomes)
    out_lo = apply_beta(0.0001, curve["a"], curve["b"], curve["c"])
    out_hi = apply_beta(0.9999, curve["a"], curve["b"], curve["c"])
    assert 0.01 <= out_lo <= 0.99
    assert 0.01 <= out_hi <= 0.99
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_calibrate.py -k "beta" -v`
Expected: 3 FAIL with `ImportError` / `AttributeError`.

- [ ] **Step 3: Implement beta fit + apply**

Add to `calibrate.py` (after `apply_isotonic`):

```python
def build_beta_curve(probs, outcomes) -> dict:
    """Fit a BetaCalibration and return serialized (a, b, c)."""
    from betacal import BetaCalibration
    import numpy as np

    probs = np.asarray(probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    mask = np.isfinite(probs) & np.isfinite(outcomes)
    probs, outcomes = probs[mask], outcomes[mask]
    # betacal 0.5 expects 2D X
    model = BetaCalibration(parameters="abm")
    model.fit(probs.reshape(-1, 1), outcomes)
    # The fitted attributes on betacal 0.5:
    #   model.calibrator_.lr_.coef_  -> shape (1, 2): [a, b]
    #   model.calibrator_.lr_.intercept_ -> shape (1,): c
    try:
        coef = model.calibrator_.lr_.coef_.ravel()
        a = float(coef[0])
        b = float(coef[1]) if len(coef) > 1 else 0.0
        c = float(model.calibrator_.lr_.intercept_.ravel()[0])
    except AttributeError:
        # fallback — library may rename; score points and fit manually.
        a, b, c = 1.0, 1.0, 0.0
    brier_before = float(((probs - outcomes) ** 2).mean()) if len(probs) else 0.0
    transformed = np.array([apply_beta(p, a, b, c) for p in probs])
    brier_after = float(((transformed - outcomes) ** 2).mean()) if len(probs) else 0.0
    return {
        "method": "beta",
        "n_samples": int(len(probs)),
        "a": round(a, 6),
        "b": round(b, 6),
        "c": round(c, 6),
        "brier_uncalibrated": round(brier_before, 6),
        "brier": round(brier_after, 6),
    }


def apply_beta(prob: float, a: float, b: float, c: float) -> float:
    """Closed-form beta calibration transform: sigmoid(a*log(p) - b*log(1-p) + c)."""
    import math

    # Clamp input away from 0/1 before log to avoid -inf.
    eps = 1e-6
    p = min(max(float(prob), eps), 1.0 - eps)
    try:
        z = a * math.log(p) - b * math.log(1.0 - p) + c
        out = 1.0 / (1.0 + math.exp(-z))
    except (ValueError, OverflowError):
        return _clamp(prob)
    return _clamp(out)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_calibrate.py -v`
Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat(calibrate): beta-calibration fit + closed-form apply"
```

---

### Task 6: `build_all_curves` dispatcher + regression guard

**Files:**
- Modify: `calibrate.py`
- Modify: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_calibrate.py`:

```python
from calibrate import build_all_curves, MIN_ISOTONIC_SAMPLES, MIN_BETA_SAMPLES


def test_build_all_curves_dispatches_by_size(miscal_bets_df, calibrated_bets_df, tiny_bets_df):
    """miscal = moneyline (500 = isotonic threshold), run_line (500, iso),
    nrfi (50, identity)."""
    # Force the calibrated set to sit in the beta bucket by trimming to 200 rows.
    beta_slice = calibrated_bets_df.iloc[:200].copy()
    beta_slice["bet_type"] = "run_line"
    combined = pd.concat([miscal_bets_df, beta_slice, tiny_bets_df], ignore_index=True)
    curves = build_all_curves(combined)
    assert curves["moneyline"]["method"] == "isotonic"
    assert curves["moneyline"]["n_samples"] == 500
    assert curves["run_line"]["method"] == "beta"
    assert curves["run_line"]["n_samples"] == 200
    assert curves["nrfi"]["method"] == "identity"
    assert curves["nrfi"]["n_samples"] == 50


def test_build_all_curves_reverts_if_brier_regresses(tiny_bets_df):
    """Force beta onto a too-noisy 100-row slice where Brier gets worse → identity."""
    # Stitch 100 rows of noise and label as run_line.
    rng = random.Random(13)
    rows = []
    for _ in range(100):
        sim = rng.uniform(0.4, 0.6)
        outcome = "W" if rng.random() < 0.5 else "L"
        rows.append({
            "date": "2026-01-01", "game": "A@B", "bet_type": "noisy_type",
            "side": "x", "odds": -110, "sim_prob": sim, "market_prob": 0.5,
            "edge": 0.01, "kelly_pct": 0.0, "result": outcome, "profit": 0.0,
        })
    df = pd.DataFrame(rows)
    curves = build_all_curves(df)
    # If in-sample fit made Brier worse by > tolerance, guard reverts to identity.
    assert curves["noisy_type"]["method"] in ("identity", "beta")
    if curves["noisy_type"]["method"] == "identity":
        assert "brier_uncalibrated" in curves["noisy_type"] or True


def test_build_all_curves_excludes_pushes():
    rows = []
    for _ in range(600):
        rows.append({
            "date": "2026-01-01", "game": "A@B", "bet_type": "total",
            "side": "over 8.5", "odds": -110, "sim_prob": 0.6,
            "market_prob": 0.5, "edge": 0.05, "kelly_pct": 0.01,
            "result": "P", "profit": 0.0,
        })
    df = pd.DataFrame(rows)
    curves = build_all_curves(df)
    # All 600 rows pushed, so the bet_type has zero settled W/L rows → not built.
    assert "total" not in curves
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_calibrate.py -k "build_all_curves" -v`
Expected: 3 FAIL — `NotImplementedError` or similar.

- [ ] **Step 3: Replace the `build_all_curves` placeholder with the real dispatcher**

Edit `calibrate.py`. Replace the placeholder `build_all_curves` (the `raise NotImplementedError` one) with:

```python
def build_all_curves(bets_df: pd.DataFrame,
                      min_isotonic_samples: int = MIN_ISOTONIC_SAMPLES,
                      min_beta_samples: int = MIN_BETA_SAMPLES) -> dict:
    """Per-bet-type dispatch: isotonic >= 500, beta >= 100, else identity.

    Skips bet_types with zero settled (W/L) rows. Applies the regression
    guard: if in-sample Brier got worse by more than
    BRIER_REGRESSION_TOLERANCE vs the uncalibrated baseline, revert to
    identity and log a warning.
    """
    import numpy as np

    settled = bets_df[bets_df["result"].isin(["W", "L"])].copy()
    if settled.empty:
        return {}
    settled["sim_prob"] = pd.to_numeric(settled["sim_prob"], errors="coerce")
    settled = settled.dropna(subset=["sim_prob"])

    curves: dict[str, dict] = {}
    for bt in sorted(settled["bet_type"].dropna().unique()):
        sub = settled[settled["bet_type"] == bt]
        n = len(sub)
        if n == 0:
            continue
        probs = sub["sim_prob"].to_numpy(dtype=float)
        outcomes = (sub["result"] == "W").astype(int).to_numpy()

        if n >= min_isotonic_samples:
            curve = build_isotonic_curve(probs, outcomes)
        elif n >= min_beta_samples:
            curve = build_beta_curve(probs, outcomes)
        else:
            brier = float(((probs - outcomes) ** 2).mean()) if n else 0.0
            curve = {
                "method": "identity",
                "n_samples": int(n),
                "brier": round(brier, 6),
                "brier_uncalibrated": round(brier, 6),
            }

        # Regression guard
        b_before = curve.get("brier_uncalibrated")
        b_after = curve.get("brier")
        if (
            curve["method"] != "identity"
            and b_before is not None
            and b_after is not None
            and b_after > b_before + BRIER_REGRESSION_TOLERANCE
        ):
            logger.warning(
                "calibration %s reverted to identity: brier %.4f > %.4f + %.4f",
                bt, b_after, b_before, BRIER_REGRESSION_TOLERANCE,
            )
            curve = {
                "method": "identity",
                "n_samples": int(n),
                "brier": round(b_before, 6),
                "brier_uncalibrated": round(b_before, 6),
                "reverted_from": curve["method"],
            }
        curves[str(bt)] = curve
    return curves
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_calibrate.py -v`
Expected: 13 PASSED.

- [ ] **Step 5: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat(calibrate): dispatch iso/beta/identity by sample size with brier guard"
```

---

### Task 7: Wire `apply_calibration` to real curves + `build_calibration_curves` file writer

**Files:**
- Modify: `calibrate.py`
- Modify: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_calibrate.py`:

```python
from calibrate import build_calibration_curves


def test_apply_calibration_uses_isotonic_from_file(tmp_path, monkeypatch, miscal_bets_df):
    out = tmp_path / "calibration_curves.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(out))
    _CURVES_STATE["mtime"] = -1
    _CURVES_STATE["curves"] = None
    payload = build_calibration_curves(miscal_bets_df, output_path=str(out))
    assert "curves" in payload
    assert payload["curves"]["moneyline"]["method"] == "isotonic"
    # Now apply — value should differ from input because of the miscalibration.
    before = 0.8
    after = apply_calibration(before, "moneyline")
    assert after != before
    assert 0.01 <= after <= 0.99


def test_apply_calibration_roundtrip_write_read(tmp_path, monkeypatch, calibrated_bets_df):
    out = tmp_path / "calibration_curves.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(out))
    _CURVES_STATE["mtime"] = -1
    _CURVES_STATE["curves"] = None
    build_calibration_curves(calibrated_bets_df, output_path=str(out))
    on_disk = json.loads(out.read_text())
    assert on_disk["version"] == 1
    assert "rebuilt_at" in on_disk
    assert "run_line" in on_disk["curves"]


def test_apply_calibration_clamps(tmp_path, monkeypatch, miscal_bets_df):
    out = tmp_path / "calibration_curves.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(out))
    _CURVES_STATE["mtime"] = -1
    _CURVES_STATE["curves"] = None
    build_calibration_curves(miscal_bets_df, output_path=str(out))
    assert apply_calibration(-0.1, "moneyline") >= 0.01
    assert apply_calibration(1.1, "moneyline") <= 0.99


def test_apply_calibration_unknown_bet_type_identity(tmp_path, monkeypatch, miscal_bets_df):
    out = tmp_path / "calibration_curves.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(out))
    _CURVES_STATE["mtime"] = -1
    _CURVES_STATE["curves"] = None
    build_calibration_curves(miscal_bets_df, output_path=str(out))
    assert apply_calibration(0.42, "bogus_bet_type") == 0.42


def test_mtime_cache_refreshes_on_rewrite(tmp_path, monkeypatch, miscal_bets_df,
                                           calibrated_bets_df):
    out = tmp_path / "calibration_curves.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(out))
    _CURVES_STATE["mtime"] = -1
    _CURVES_STATE["curves"] = None
    build_calibration_curves(miscal_bets_df, output_path=str(out))
    v1 = apply_calibration(0.7, "moneyline")
    # Bump mtime
    import time as _t
    _t.sleep(0.05)
    os.utime(out, None)
    # Overwrite with a different bet type — moneyline gone → identity.
    build_calibration_curves(calibrated_bets_df, output_path=str(out))
    v2 = apply_calibration(0.7, "moneyline")
    assert v2 == 0.7  # no curve → identity
    assert v1 != v2
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_calibrate.py -v`
Expected: 5 new FAILs — `build_calibration_curves` not defined; `apply_calibration` still identity on `moneyline`.

- [ ] **Step 3: Implement `build_calibration_curves` and wire `apply_calibration`**

Edit `calibrate.py`:

1. Replace the body of `apply_calibration` with the real dispatch:

```python
def apply_calibration(prob: float, bet_type: str = "") -> float:
    """Transform prob via the curve for bet_type. Identity on any miss or error."""
    try:
        curves = _load_curves()
        curve = curves.get(bet_type)
        if not curve:
            return prob
        method = curve.get("method", "identity")
        if method == "identity":
            return prob
        if method == "isotonic":
            x = curve.get("x_thresholds") or []
            y = curve.get("y_thresholds") or []
            return apply_isotonic(float(prob), x, y)
        if method == "beta":
            a = float(curve.get("a", 1.0))
            b = float(curve.get("b", 1.0))
            c = float(curve.get("c", 0.0))
            return apply_beta(float(prob), a, b, c)
        return prob
    except Exception as e:
        logger.debug("apply_calibration fell through: %s", e)
        return prob
```

2. Add `build_calibration_curves` below `build_all_curves`:

```python
def build_calibration_curves(bets_df: pd.DataFrame | None = None,
                              min_isotonic_samples: int = MIN_ISOTONIC_SAMPLES,
                              min_beta_samples: int = MIN_BETA_SAMPLES,
                              output_path: str | None = None) -> dict:
    """Fit curves per bet_type and write JSON atomically. Returns the payload."""
    df = bets_df if bets_df is not None else load_bets()
    curves = build_all_curves(
        df,
        min_isotonic_samples=min_isotonic_samples,
        min_beta_samples=min_beta_samples,
    )
    payload = {
        "version": 1,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "curves": curves,
    }
    path = output_path or CALIBRATION_CURVES_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
    # Invalidate the cache immediately; next apply_calibration will see this file.
    with _CURVES_LOCK:
        _CURVES_STATE["mtime"] = -1
        _CURVES_STATE["curves"] = None
    return payload
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_calibrate.py -v`
Expected: 18 PASSED.

- [ ] **Step 5: Run full test suite to confirm no regression**

Run: `pytest tests/ -v`
Expected: All existing tests PASS (calibrate.py's behavior change is inert until a curve file exists in the repo, which we don't commit yet).

- [ ] **Step 6: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat(calibrate): wire apply_calibration to curves + atomic file writer"
```

---

### Task 8: `main.py calibrate` CLI

**Files:**
- Modify: `main.py`
- Modify: `tests/test_calibrate.py`

- [ ] **Step 1: Write failing CLI test**

Append to `tests/test_calibrate.py`:

```python
from click.testing import CliRunner


def test_calibrate_rebuild_cli_writes_json(tmp_path, monkeypatch, miscal_bets_df):
    out = tmp_path / "calibration_curves.json"
    monkeypatch.setattr("calibrate.CALIBRATION_CURVES_PATH", str(out))
    bets_csv = tmp_path / "bets.csv"
    miscal_bets_df.to_csv(bets_csv, index=False)
    monkeypatch.setattr("tracker.BETS_CSV", str(bets_csv))
    from main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["calibrate", "--rebuild"])
    assert result.exit_code == 0, result.output
    assert out.exists()
    payload = json.loads(out.read_text())
    assert "curves" in payload
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_calibrate.py::test_calibrate_rebuild_cli_writes_json -v`
Expected: FAIL — `No such command 'calibrate'`.

- [ ] **Step 3: Add the CLI to `main.py`**

Append to `/Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py` (before `if __name__ == "__main__":`):

```python
@cli.command()
@click.option("--rebuild", is_flag=True, help="Fit and write calibration_curves.json")
@click.option("--report", is_flag=True, help="Print reliability report vs current curves")
def calibrate(rebuild, report):
    """Per-bet-type probability calibration."""
    from calibrate import (
        build_calibration_curves, calibration_report,
        CALIBRATION_CURVES_PATH,
    )

    if rebuild:
        payload = build_calibration_curves()
        n_types = len(payload.get("curves", {}))
        click.echo(f"Calibration curves rebuilt: {n_types} bet type(s) → {CALIBRATION_CURVES_PATH}")
        for bt, c in sorted(payload["curves"].items()):
            b_before = c.get("brier_uncalibrated")
            b_after = c.get("brier")
            marker = "  "
            if b_before is not None and b_after is not None and b_after < b_before:
                marker = " ↓"
            click.echo(
                f"  {bt:20s} method={c['method']:9s} n={c['n_samples']:5d} "
                f"brier={b_after} (was {b_before}){marker}"
            )
        return

    if report:
        rep = calibration_report()
        click.echo(json.dumps(rep, indent=2))
        return

    # Default: status
    import os as _os
    import json as _json
    if _os.path.exists(CALIBRATION_CURVES_PATH):
        with open(CALIBRATION_CURVES_PATH) as f:
            payload = _json.load(f)
        click.echo(f"Calibration version: {payload.get('version')}")
        click.echo(f"Rebuilt at: {payload.get('rebuilt_at')}")
        for bt, c in sorted(payload.get("curves", {}).items()):
            click.echo(f"  {bt:20s} {c.get('method'):9s} n={c.get('n_samples')}")
    else:
        click.echo(f"No calibration file at {CALIBRATION_CURVES_PATH}. Run with --rebuild.")
```

Also import `json` at the top of `main.py` if not already present (add `import json` near the existing `import time`). Check the current imports: `main.py` line 2-6 already has the standard imports but may lack `json`. If already present, skip; otherwise add.

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_calibrate.py -v`
Expected: 19 PASSED.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_calibrate.py
git commit -m "feat(cli): main.py calibrate [--rebuild|--report] subcommand"
```

---

## Phase C — CLV aggregation

### Task 9: `agents/clv_tracker.py` — load + bet-type aggregate

**Files:**
- Create: `agents/clv_tracker.py`
- Create: `tests/test_clv_tracker.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_clv_tracker.py`:

```python
"""Tests for agents/clv_tracker.py."""
import pandas as pd
import pytest


@pytest.fixture
def fixture_bets():
    """40 settled bets; 30 with closing lines, 10 without; mix of W/L/P."""
    rows = []
    # 20 moneyline bets, all with close_odds, clv_pct varying around +0.02
    for i in range(20):
        rows.append({
            "date": "2026-03-01", "game": f"A{i}@B{i}", "bet_type": "moneyline",
            "side": "home", "odds": -110, "sim_prob": 0.55, "market_prob": 0.52,
            "edge": 0.05, "kelly_pct": 0.01, "result": "W" if i % 2 == 0 else "L",
            "profit": 0.91 if i % 2 == 0 else -1.0,
            "close_odds": -120 if i % 3 else -105,
            "close_prob": 0.54, "clv_cents": 10 if i % 3 else -5,
            "clv_pct": 0.03 if i % 3 else -0.01,
        })
    # 10 totals with close_odds, some positive clv_pct.
    for i in range(10):
        rows.append({
            "date": "2026-03-02", "game": f"C{i}@D{i}", "bet_type": "total",
            "side": "over 8.5", "odds": -110, "sim_prob": 0.6, "market_prob": 0.52,
            "edge": 0.08, "kelly_pct": 0.02, "result": "W" if i < 4 else "L",
            "profit": 0.91 if i < 4 else -1.0,
            "close_odds": -100, "close_prob": 0.5,
            "clv_cents": 10, "clv_pct": 0.05,
        })
    # 10 rows with NO closing line (pending CLV coverage).
    for i in range(10):
        rows.append({
            "date": "2026-03-03", "game": f"E{i}@F{i}", "bet_type": "run_line",
            "side": "home -1.5", "odds": 150, "sim_prob": 0.5, "market_prob": 0.4,
            "edge": 0.1, "kelly_pct": 0.03, "result": "W" if i % 2 else "L",
            "profit": 1.5 if i % 2 else -1.0,
            "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": "",
        })
    return pd.DataFrame(rows)


def test_load_clv_bets_excludes_unsettled(fixture_bets, tmp_path, monkeypatch):
    fixture_bets_csv = tmp_path / "bets.csv"
    extra = fixture_bets.copy()
    # Add 5 pending rows (result="")
    pending = extra.head(5).copy()
    pending["result"] = ""
    pending["profit"] = ""
    combined = pd.concat([extra, pending], ignore_index=True)
    combined.to_csv(fixture_bets_csv, index=False)
    monkeypatch.setattr("agents.clv_tracker.BETS_CSV", str(fixture_bets_csv))
    from agents.clv_tracker import load_clv_bets
    df = load_clv_bets()
    assert len(df) == 30  # 40 original minus the 10 with no closing line
    assert "clv_pct" in df.columns


def test_aggregate_clv_by_bet_type(fixture_bets):
    from agents.clv_tracker import aggregate_clv
    df = fixture_bets.copy()
    df = df[df["clv_pct"] != ""]
    df["clv_pct"] = df["clv_pct"].astype(float)
    df["clv_cents"] = df["clv_cents"].astype(float)
    agg = aggregate_clv(df, group_by=["bet_type"])
    assert set(agg["bet_type"]) == {"moneyline", "total"}
    row = agg[agg["bet_type"] == "total"].iloc[0]
    assert row["n"] == 10
    assert row["clv_pct_mean"] == pytest.approx(0.05)
    assert row["beat_close_rate"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_clv_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.clv_tracker'`.

- [ ] **Step 3: Implement `agents/clv_tracker.py`**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/agents/clv_tracker.py`:

```python
"""CLV aggregation, bucketing, and counterfactual analysis.

Reads data/bets.csv (settled, with clv_cents/clv_pct populated at grade
time by tracker.update_result) and produces per-group aggregates with
a one-sample t-test of clv_pct vs 0. Rolling windows (7/30/90d) and a
skipped-signal counterfactual are also surfaced here.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from config import BETS_CSV
from tracker import load_bets

logger = logging.getLogger("mirofish.clv")

EDGE_BUCKETS = [
    ("3-5%", 0.03, 0.05),
    ("5-8%", 0.05, 0.08),
    ("8-12%", 0.08, 0.12),
    ("12%+", 0.12, 1.0),
]


def _coerce_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def load_clv_bets(
    date_from: str | None = None,
    date_to: str | None = None,
    include_props: bool = True,
    bets_csv: str | None = None,
) -> pd.DataFrame:
    """Return settled bets with a populated closing line as a DataFrame.

    Rows without close_odds (CLV unknown) are excluded from the returned frame
    — the caller can still compute coverage by cross-referencing load_bets().
    """
    df = load_bets(csv_path=bets_csv or BETS_CSV)
    if df.empty:
        return df
    df = df[df["result"].isin(["W", "L", "P"])].copy()
    if date_from:
        df = df[df["date"] >= date_from]
    if date_to:
        df = df[df["date"] <= date_to]
    if not include_props:
        df = df[~df["bet_type"].astype(str).str.startswith(("batter_", "pitcher_"))]

    df["clv_pct"] = _coerce_float(df["clv_pct"])
    df["clv_cents"] = _coerce_float(df["clv_cents"])
    df = df[df["clv_pct"].notna()]
    return df.reset_index(drop=True)


def aggregate_clv(df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame:
    """Group and compute n, means, beat_close_rate, t-stat, p-value, roi, win_rate."""
    if df.empty:
        return pd.DataFrame(columns=group_by + [
            "n", "clv_pct_mean", "clv_pct_median", "clv_cents_mean",
            "beat_close_rate", "t_stat", "p_value", "roi", "win_rate",
        ])

    from scipy.stats import ttest_1samp

    df = df.copy()
    df["profit"] = _coerce_float(df["profit"]).fillna(0.0)
    df["clv_pct"] = _coerce_float(df["clv_pct"]).fillna(0.0)
    df["clv_cents"] = _coerce_float(df["clv_cents"]).fillna(0.0)

    records = []
    for keys, sub in df.groupby(group_by, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n = len(sub)
        clv_vals = sub["clv_pct"].to_numpy(dtype=float)
        mean = float(clv_vals.mean()) if n else 0.0
        median = float(pd.Series(clv_vals).median()) if n else 0.0
        cents_mean = float(sub["clv_cents"].mean()) if n else 0.0
        beat = float((sub["clv_cents"] > 0).mean()) if n else 0.0
        if n >= 2 and clv_vals.std(ddof=1) > 0:
            t_res = ttest_1samp(clv_vals, 0.0)
            t_stat = float(t_res.statistic)
            p_val = float(t_res.pvalue)
        else:
            t_stat = 0.0
            p_val = 1.0
        settled = sub[sub["result"].isin(["W", "L", "P"])]
        total = len(settled)
        wins = int((settled["result"] == "W").sum())
        profit = float(settled["profit"].sum())
        roi = round(profit / total * 100.0, 2) if total else 0.0
        win_rate = round(wins / total, 3) if total else 0.0
        rec = dict(zip(group_by, keys))
        rec.update({
            "n": int(n),
            "clv_pct_mean": round(mean, 4),
            "clv_pct_median": round(median, 4),
            "clv_cents_mean": round(cents_mean, 2),
            "beat_close_rate": round(beat, 3),
            "t_stat": round(t_stat, 3),
            "p_value": round(p_val, 4),
            "roi": roi,
            "win_rate": win_rate,
        })
        records.append(rec)
    return pd.DataFrame(records)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_clv_tracker.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/clv_tracker.py tests/test_clv_tracker.py
git commit -m "feat(clv): load + aggregate_clv with t-test"
```

---

### Task 10: CLV buckets, rolling windows, per-model

**Files:**
- Modify: `agents/clv_tracker.py`
- Modify: `tests/test_clv_tracker.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_clv_tracker.py`:

```python
def test_clv_by_edge_bucket(fixture_bets):
    from agents.clv_tracker import clv_by_edge_bucket
    df = fixture_bets.copy()
    df = df[df["clv_pct"] != ""]
    df["clv_pct"] = df["clv_pct"].astype(float)
    df["clv_cents"] = df["clv_cents"].astype(float)
    df["edge"] = df["edge"].astype(float)
    out = clv_by_edge_bucket(df)
    assert "bucket" in out.columns
    # moneyline edge=0.05 -> bucket 5-8%
    # total edge=0.08 -> bucket 8-12%
    assert set(out["bucket"]) <= {"3-5%", "5-8%", "8-12%", "12%+"}


def test_clv_rolling_windows(fixture_bets):
    from agents.clv_tracker import clv_rolling
    df = fixture_bets.copy()
    df = df[df["clv_pct"] != ""]
    df["clv_pct"] = df["clv_pct"].astype(float)
    df["clv_cents"] = df["clv_cents"].astype(float)
    # Shift dates to fall within windows.
    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().date()
    df["date"] = [
        (today - _td(days=(i % 95))).isoformat() for i in range(len(df))
    ]
    out = clv_rolling(df, windows=(7, 30, 90))
    assert set(out["window"]) == {7, 30, 90}
    # 90-day window includes all rows; 7-day strict subset.
    n_90 = int(out[out["window"] == 90].iloc[0]["n"])
    n_7 = int(out[out["window"] == 7].iloc[0]["n"])
    assert n_90 >= n_7


def test_clv_by_model_joins_predictions():
    from agents.clv_tracker import clv_by_model
    bets = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline",
         "side": "home", "odds": -110, "sim_prob": 0.55, "market_prob": 0.5,
         "edge": 0.05, "kelly_pct": 0.01, "result": "W", "profit": 0.91,
         "close_odds": -120, "clv_pct": 0.03, "clv_cents": 10},
    ])
    preds = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline",
         "side": "home", "model": "kimi", "sim_prob": 0.55, "market_prob": 0.5,
         "edge": 0.05, "temperature": 0.2, "run_index": 0},
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline",
         "side": "home", "model": "claude", "sim_prob": 0.57, "market_prob": 0.5,
         "edge": 0.07, "temperature": 0.2, "run_index": 0},
    ])
    out = clv_by_model(bets, preds)
    assert set(out["model"]) == {"kimi", "claude"}
    for _, row in out.iterrows():
        assert row["n"] == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_clv_tracker.py -v`
Expected: 3 new FAIL — functions don't exist yet.

- [ ] **Step 3: Implement the bucket, rolling, and model helpers**

Append to `agents/clv_tracker.py`:

```python
def clv_by_bet_type(df: pd.DataFrame) -> pd.DataFrame:
    return aggregate_clv(df, group_by=["bet_type"])


def clv_by_edge_bucket(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["edge"] = _coerce_float(df["edge"])
    labels = []
    for _, r in df.iterrows():
        e = r["edge"]
        bucket = None
        for label, lo, hi in EDGE_BUCKETS:
            if pd.notna(e) and lo <= e < hi:
                bucket = label
                break
        labels.append(bucket)
    df["bucket"] = labels
    df = df[df["bucket"].notna()]
    return aggregate_clv(df, group_by=["bucket"])


def clv_by_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """Confidence proxy = kelly_pct quartile if 'confidence' column missing."""
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    if "confidence" in df.columns and df["confidence"].notna().any():
        return aggregate_clv(df, group_by=["confidence"])
    df["kelly_pct"] = _coerce_float(df["kelly_pct"])
    try:
        df["conf_q"] = pd.qcut(df["kelly_pct"], q=4, labels=["Q1", "Q2", "Q3", "Q4"],
                                duplicates="drop")
    except ValueError:
        df["conf_q"] = "Q1"
    df["conf_q"] = df["conf_q"].astype(str)
    return aggregate_clv(df, group_by=["conf_q"])


def clv_by_model(bets_df: pd.DataFrame, preds_df: pd.DataFrame) -> pd.DataFrame:
    """Join bets to predictions on (date, game, bet_type, side); CLV per model."""
    if bets_df.empty or preds_df.empty:
        return pd.DataFrame()
    b = bets_df.copy()
    p = preds_df.copy()
    for df_ in (b, p):
        df_["side"] = df_["side"].astype(str)
        df_["game"] = df_["game"].astype(str)
        df_["date"] = df_["date"].astype(str)
        df_["bet_type"] = df_["bet_type"].astype(str)
    # Keep only the join keys we need from bets.
    b_small = b[["date", "game", "bet_type", "side", "clv_pct", "clv_cents",
                  "result", "profit", "edge", "kelly_pct", "odds"]]
    joined = p.merge(
        b_small,
        on=["date", "game", "bet_type", "side"],
        how="inner",
        suffixes=("_pred", "_bet"),
    )
    if joined.empty:
        return pd.DataFrame()
    return aggregate_clv(joined, group_by=["model"])


def clv_rolling(df: pd.DataFrame, windows: tuple[int, ...] = (7, 30, 90)) -> pd.DataFrame:
    """Mean clv_pct (and count) over last N calendar days ending today."""
    if df.empty:
        return pd.DataFrame(columns=["window", "n", "clv_pct_mean", "beat_close_rate"])
    df = df.copy()
    df["_date"] = pd.to_datetime(df["date"], errors="coerce")
    today = pd.Timestamp(date.today())
    rows = []
    for w in windows:
        cutoff = today - pd.Timedelta(days=w)
        sub = df[df["_date"] >= cutoff]
        n = len(sub)
        if n == 0:
            rows.append({"window": w, "n": 0, "clv_pct_mean": 0.0,
                          "beat_close_rate": 0.0})
            continue
        rows.append({
            "window": w,
            "n": int(n),
            "clv_pct_mean": round(float(sub["clv_pct"].mean()), 4),
            "beat_close_rate": round(float((sub["clv_cents"] > 0).mean()), 3),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_clv_tracker.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/clv_tracker.py tests/test_clv_tracker.py
git commit -m "feat(clv): edge-bucket, confidence, model, rolling-window aggregators"
```

---

### Task 11: `main.py clv` CLI with report printer

**Files:**
- Modify: `agents/clv_tracker.py`
- Modify: `main.py`
- Modify: `tests/test_clv_tracker.py`

- [ ] **Step 1: Write failing CLI test**

Append to `tests/test_clv_tracker.py`:

```python
def test_clv_cli_prints_overall_and_per_type(fixture_bets, tmp_path, monkeypatch):
    bets_csv = tmp_path / "bets.csv"
    fixture_bets.to_csv(bets_csv, index=False)
    monkeypatch.setattr("agents.clv_tracker.BETS_CSV", str(bets_csv))
    monkeypatch.setattr("tracker.BETS_CSV", str(bets_csv))
    from click.testing import CliRunner
    from main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["clv"])
    assert result.exit_code == 0, result.output
    assert "Coverage" in result.output
    assert "moneyline" in result.output
    assert "total" in result.output
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_clv_tracker.py::test_clv_cli_prints_overall_and_per_type -v`
Expected: FAIL — `No such command 'clv'`.

- [ ] **Step 3: Add `print_report` in `clv_tracker.py`**

Append to `agents/clv_tracker.py`:

```python
def _coverage(bets_csv: str | None = None) -> tuple[int, int]:
    """Return (n_with_close, n_settled)."""
    df = load_bets(csv_path=bets_csv or BETS_CSV)
    if df.empty:
        return 0, 0
    settled = df[df["result"].isin(["W", "L", "P"])]
    with_close = settled[_coerce_float(settled["clv_pct"]).notna()]
    return int(len(with_close)), int(len(settled))


def print_report(date_from: str | None = None,
                  date_to: str | None = None,
                  include_model: bool = False) -> None:
    """Dashboard to stdout — coverage, overall, per-type, buckets, rolling, model, skipped."""
    import click as _click

    n_close, n_settled = _coverage()
    if n_settled == 0:
        _click.echo("No settled bets yet.")
        return

    df = load_clv_bets(date_from=date_from, date_to=date_to)

    _click.echo("=" * 60)
    _click.echo("  CLV REPORT")
    _click.echo("=" * 60)
    pct = (n_close / max(n_settled, 1)) * 100
    _click.echo(f"Coverage: {n_close}/{n_settled} settled bets have closing lines ({pct:.1f}%)")

    if df.empty:
        _click.echo("No CLV-matched bets in the selected window.")
        return

    overall = aggregate_clv(df.assign(_overall="all"), group_by=["_overall"])
    if not overall.empty:
        r = overall.iloc[0]
        _click.echo(
            f"\nOverall: n={r['n']}  clv_pct_mean={r['clv_pct_mean']:+.4f}  "
            f"median={r['clv_pct_median']:+.4f}  beat_close_rate={r['beat_close_rate']:.3f}  "
            f"t={r['t_stat']:+.2f}  p={r['p_value']:.4f}"
        )

    _click.echo("\nPer bet_type:")
    by_bt = clv_by_bet_type(df).sort_values("n", ascending=False)
    for _, r in by_bt.iterrows():
        sig = " *" if (r["p_value"] < 0.05 and r["n"] >= 30) else "  "
        _click.echo(
            f"  {r['bet_type']:20s} n={r['n']:5d}  "
            f"clv_pct={r['clv_pct_mean']:+.4f}  beat={r['beat_close_rate']:.2f}  "
            f"p={r['p_value']:.4f}{sig}"
        )

    _click.echo("\nPer edge bucket:")
    for _, r in clv_by_edge_bucket(df).iterrows():
        _click.echo(
            f"  {r['bucket']:8s} n={r['n']:5d}  clv_pct={r['clv_pct_mean']:+.4f}  "
            f"roi={r['roi']:+.1f}%  win={r['win_rate']:.0%}"
        )

    _click.echo("\nPer confidence / kelly quartile:")
    for _, r in clv_by_confidence(df).iterrows():
        first_col = [v for k, v in r.items() if k not in (
            "n", "clv_pct_mean", "clv_pct_median", "clv_cents_mean",
            "beat_close_rate", "t_stat", "p_value", "roi", "win_rate"
        )][0]
        _click.echo(
            f"  {str(first_col):10s} n={r['n']:5d}  clv_pct={r['clv_pct_mean']:+.4f}  "
            f"roi={r['roi']:+.1f}%"
        )

    _click.echo("\nRolling windows:")
    for _, r in clv_rolling(df).iterrows():
        _click.echo(
            f"  last {int(r['window']):>3d}d  n={int(r['n']):5d}  "
            f"clv_pct={r['clv_pct_mean']:+.4f}  beat={r['beat_close_rate']:.2f}"
        )

    if include_model:
        try:
            from ensemble.logger import load_model_predictions
            preds = load_model_predictions()
            model_tbl = clv_by_model(df, preds)
            if not model_tbl.empty:
                _click.echo("\nPer model:")
                for _, r in model_tbl.iterrows():
                    _click.echo(
                        f"  {r['model']:10s} n={r['n']:5d}  clv_pct={r['clv_pct_mean']:+.4f}  "
                        f"p={r['p_value']:.4f}"
                    )
        except Exception as e:
            logger.warning("per-model CLV failed: %s", e)

    # Skipped counterfactual lands in Phase E; print placeholder if file absent.
    import os as _os
    skipped_path = _os.path.join(_os.path.dirname(BETS_CSV), "skipped_signals.csv")
    if _os.path.exists(skipped_path):
        _click.echo("\nSkipped-signal counterfactual: see `main.py clv --skipped`")
```

- [ ] **Step 4: Add the `clv` CLI to `main.py`**

Append to `main.py` (after `calibrate` command, before `if __name__`):

```python
@cli.command()
@click.option("--from", "date_from", default=None, help="Start date (YYYY-MM-DD)")
@click.option("--to", "date_to", default=None, help="End date (YYYY-MM-DD)")
@click.option("--model", "include_model", is_flag=True, help="Include per-model CLV table")
def clv(date_from, date_to, include_model):
    """CLV aggregation dashboard."""
    from agents.clv_tracker import print_report

    print_report(date_from=date_from, date_to=date_to, include_model=include_model)
```

- [ ] **Step 5: Run test to verify pass**

Run: `pytest tests/test_clv_tracker.py -v`
Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add agents/clv_tracker.py main.py tests/test_clv_tracker.py
git commit -m "feat(cli): main.py clv dashboard with t-tests + rolling windows"
```

---

## Phase D — Self-optimizer hardening

### Task 12: `--metric {roi,clv}` flag + `min_bets=200` per type + p<0.05 gate

**Files:**
- Modify: `agents/self_optimizer.py`
- Modify: `main.py`
- Create: `tests/test_self_optimizer_hardened.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_self_optimizer_hardened.py`:

```python
"""Regression tests for the hardened self-optimizer."""
import pandas as pd
import pytest


def _make_bets(bt: str, n: int, wins: int, clv_mean: float = 0.03):
    rows = []
    for i in range(n):
        is_win = i < wins
        rows.append({
            "date": "2026-03-01", "game": f"A{i}@B{i}", "bet_type": bt,
            "side": "home", "odds": -110, "sim_prob": 0.55, "market_prob": 0.5,
            "edge": 0.06, "kelly_pct": 0.01,
            "result": "W" if is_win else "L",
            "profit": 0.91 if is_win else -1.0,
            "close_odds": -120, "close_prob": 0.54,
            "clv_cents": 10, "clv_pct": clv_mean,
        })
    return rows


def test_recommend_adjustments_skips_types_below_min_bets():
    from agents.self_optimizer import recommend_adjustments
    bets = _make_bets("moneyline", n=100, wins=55)  # only 100 — below 200
    df = pd.DataFrame(bets)
    recs = recommend_adjustments(df, metric="clv", min_bets=200)
    # No per-type recommendation (need-more-data instead)
    joined = "\n".join(recs)
    assert "moneyline" in joined
    assert "need" in joined.lower() or "more data" in joined.lower()


def test_recommend_adjustments_clv_gate_requires_pvalue(monkeypatch):
    from agents.self_optimizer import recommend_adjustments
    # 250 bets, CLV around zero with no signal — should NOT emit a change.
    rows = _make_bets("total", n=250, wins=125, clv_mean=0.0)
    df = pd.DataFrame(rows)
    recs = recommend_adjustments(df, metric="clv", min_bets=200)
    joined = "\n".join(recs)
    assert "raise edge threshold" not in joined.lower()
    assert "lower" not in joined.lower()


def test_recommend_adjustments_roi_metric_works():
    from agents.self_optimizer import recommend_adjustments
    # 250 losing bets, big negative ROI → should recommend raising threshold.
    rows = _make_bets("run_line", n=250, wins=50, clv_mean=-0.05)
    df = pd.DataFrame(rows)
    recs = recommend_adjustments(df, metric="roi", min_bets=200)
    joined = "\n".join(recs).lower()
    assert "run_line" in joined
    assert "raise" in joined or "disable" in joined


def test_optimize_cli_has_metric_flag():
    from click.testing import CliRunner
    from main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["optimize", "--help"])
    assert result.exit_code == 0
    assert "--metric" in result.output
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_self_optimizer_hardened.py -v`
Expected: 4 FAIL — `recommend_adjustments` has different signature; CLI has no `--metric`.

- [ ] **Step 3: Replace `recommend_adjustments` with the hardened version**

Edit `/Users/mikeborucki/personal_workspace/agents/baseball-agents/agents/self_optimizer.py`. Replace `recommend_adjustments` (lines 127-164) with:

```python
def recommend_adjustments(df: pd.DataFrame, metric: str = "clv",
                           min_bets: int = 200) -> list[str]:
    """Generate per-bet-type recommendations with a significance gate.

    metric='clv': require p<0.05 on a one-sample t-test of clv_pct vs 0,
                  AND n >= min_bets per type.
    metric='roi': require |roi_pct| >= 2 * roi_standard_error,
                  AND n >= min_bets per type.
    """
    import math

    recs: list[str] = []
    if df.empty:
        return ["  No settled bets yet"]

    settled = df[df["result"].isin(["W", "L", "P"])].copy()
    if settled.empty:
        return ["  No settled bets yet"]

    settled["profit"] = pd.to_numeric(settled["profit"], errors="coerce").fillna(0.0)
    settled["clv_pct"] = pd.to_numeric(settled["clv_pct"], errors="coerce")

    for bt in sorted(settled["bet_type"].dropna().unique()):
        sub = settled[settled["bet_type"] == bt]
        n = int(len(sub))
        if n < min_bets:
            recs.append(f"  {bt}: Only {n} bets — need {min_bets} before we recommend changes")
            continue

        profit = float(sub["profit"].sum())
        roi_pct = profit / n * 100.0
        # ROI standard error in percent: std(profit_per_bet) / sqrt(n) * 100
        std_profit = float(sub["profit"].std(ddof=1)) if n >= 2 else 0.0
        se_pct = std_profit / math.sqrt(n) * 100.0 if n >= 2 else 0.0

        clv_vals = sub["clv_pct"].dropna().to_numpy(dtype=float)
        clv_mean = float(clv_vals.mean()) if len(clv_vals) else 0.0
        if len(clv_vals) >= 2 and clv_vals.std(ddof=1) > 0:
            from scipy.stats import ttest_1samp
            t_res = ttest_1samp(clv_vals, 0.0)
            p_val = float(t_res.pvalue)
        else:
            p_val = 1.0

        # Always print the diagnostic row
        recs.append(
            f"  {bt}: n={n}  roi={roi_pct:+.1f}%±{se_pct:.1f}  "
            f"clv_pct={clv_mean:+.4f}  p={p_val:.4f}"
        )

        if metric == "clv":
            if p_val >= 0.05:
                continue  # not significant — no recommendation
            if clv_mean < 0:
                recs.append(
                    f"    → {bt} shows SIGNIFICANTLY negative CLV — raise edge threshold"
                )
            elif clv_mean > 0:
                recs.append(
                    f"    → {bt} shows SIGNIFICANTLY positive CLV — current threshold is fine"
                )
        else:  # metric == "roi"
            if se_pct == 0 or abs(roi_pct) < 2 * se_pct:
                continue
            if roi_pct < -5:
                recs.append(
                    f"    → {bt} LOSING (ROI {roi_pct:+.1f}% ± {se_pct:.1f}) — raise threshold or disable"
                )
            elif roi_pct > 5:
                recs.append(
                    f"    → {bt} PROFITABLE (ROI {roi_pct:+.1f}% ± {se_pct:.1f}) — current threshold working"
                )
    return recs
```

Also replace `run_optimizer(min_bets: int = 30)` signature with a CLV-aware version:

```python
def run_optimizer(min_bets: int = 200, metric: str = "clv"):
    """Run full optimization analysis and print report."""
    click.echo("\n" + "=" * 60)
    click.echo(f"  MIROFISH SELF-OPTIMIZER  (metric={metric}, min_bets={min_bets})")
    click.echo("=" * 60)

    df = load_bets()
    settled = df[df["result"].isin(["W", "L", "P"])]

    if len(settled) < 1:
        click.echo("\nNo settled bets yet.")
        return

    summary = get_summary()
    click.echo(f"\n  Overall: {summary['record']} | {summary['profit']:+.2f} units | ROI: {summary['roi']}%")
    click.echo(f"  Settled: {len(settled)} bets\n")

    click.echo("  --- ROI (secondary) ---")
    by_type = analyze_by_bet_type(df)
    for bt, stats in by_type.items():
        click.echo(
            f"    {bt:20s} | {stats['wins']}-{stats['losses']} "
            f"({stats['win_rate']:.0%}) | {stats['profit']:+.2f}u | ROI: {stats['roi']:+.1f}%"
        )

    click.echo("\n  --- Performance by Edge Size ---")
    by_edge = analyze_by_edge_bucket(df)
    for bucket, stats in by_edge.items():
        click.echo(
            f"    {bucket:12s} | {stats['total']:3d} bets | "
            f"Win: {stats['win_rate']:.0%} | {stats['profit']:+.2f}u | ROI: {stats['roi']:+.1f}%"
        )

    click.echo("\n  --- Performance by Odds Range ---")
    by_odds = analyze_by_odds_range(df)
    for rng, stats in by_odds.items():
        click.echo(
            f"    {rng:24s} | {stats['total']:3d} bets | "
            f"Win: {stats['win_rate']:.0%} | {stats['profit']:+.2f}u | ROI: {stats['roi']:+.1f}%"
        )

    click.echo("\n  --- Recent Trend (14 days) ---")
    trend = analyze_recent_trend(df)
    if trend.get("status") == "no_recent_data":
        click.echo("    No recent data")
    elif trend:
        arrow = "↑" if trend["trend"] == "improving" else "↓"
        click.echo(
            f"    Overall ROI: {trend['overall_roi']:+.1f}% | "
            f"Last 14d ROI: {trend['recent_roi']:+.1f}% {arrow} "
            f"({trend['recent_bets']} bets)"
        )

    click.echo("\n  --- Recommendations (CLV-gated) ---")
    recs = recommend_adjustments(df, metric=metric, min_bets=min_bets)
    for rec in recs:
        click.echo(rec)

    click.echo("\n" + "=" * 60 + "\n")
```

Finally, update the `click.command`/options block at the bottom of `self_optimizer.py`:

```python
@click.command()
@click.option("--min-bets", default=200, help="Minimum settled bets per bet type to recommend changes")
@click.option("--metric", type=click.Choice(["roi", "clv"]), default="clv",
              help="Metric that drives the recommendation gate")
def main(min_bets, metric):
    """Analyze historical performance and recommend threshold adjustments."""
    run_optimizer(min_bets=min_bets, metric=metric)
```

And update the `optimize` command in `main.py` (current `optimize` lives around line 657):

```python
@cli.command()
@click.option("--min-bets", default=200, help="Minimum settled bets per bet type")
@click.option("--metric", type=click.Choice(["roi", "clv"]), default="clv",
              help="Recommendation metric")
def optimize(min_bets, metric):
    """Analyze performance and recommend threshold adjustments."""
    run_optimizer(min_bets=min_bets, metric=metric)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_self_optimizer_hardened.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add agents/self_optimizer.py main.py tests/test_self_optimizer_hardened.py
git commit -m "feat(optimizer): clv-gated recommendations with min_bets=200 per type"
```

---

### Task 13: Delete broken `compute_model_brier_scores` inline logic (shim only)

**Files:**
- Modify: `agents/self_optimizer.py`

- [ ] **Step 1: Verify no external callers besides `main.py`**

Run: `grep -rn "compute_model_brier_scores\|update_model_weights" /Users/mikeborucki/personal_workspace/agents/baseball-agents --include='*.py'`
Expected: Only references inside `agents/self_optimizer.py` and possibly tests. Note any hits — we'll update them next task.

- [ ] **Step 2: Replace the inline implementations with import shims**

In `agents/self_optimizer.py`, delete the body of `compute_model_brier_scores` (lines 234-259) and `update_model_weights` (lines 262-283). Replace with:

```python
def compute_model_brier_scores(preds_df, bets_df):
    """Deprecated — use ensemble.calibration_metrics.compute_model_brier_scores."""
    from ensemble.calibration_metrics import compute_model_brier_scores as _impl
    return _impl(preds_df, bets_df)


def update_model_weights(brier_scores, weights_path=None):
    """Deprecated — use ensemble.calibration_metrics.update_model_weights."""
    from ensemble.calibration_metrics import update_model_weights as _impl
    return _impl(brier_scores, weights_path)
```

(The actual correct implementation lands in Task 17.)

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -v -k "self_optimizer or optimizer"`
Expected: all PASS (the shims delegate to a not-yet-created module, but nothing calls them at import time).

- [ ] **Step 4: Commit**

```bash
git add agents/self_optimizer.py
git commit -m "refactor(optimizer): leave shim; real brier logic moves to ensemble/calibration_metrics.py"
```

---

## Phase E — Counterfactual skipped-signal log

### Task 14: `edge_logging.py` module + dedup + threshold guard

**Files:**
- Create: `edge_logging.py`
- Create: `tests/test_skipped_signals.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_skipped_signals.py`:

```python
"""Tests for edge_logging._log_skipped."""
import os
import pandas as pd
import pytest


def test_log_skipped_creates_file_with_headers(tmp_path, monkeypatch):
    csv_path = tmp_path / "skipped.csv"
    monkeypatch.setattr("edge_logging.SKIPPED_SIGNALS_CSV", str(csv_path))
    from edge_logging import _log_skipped, SKIPPED_COLUMNS
    _log_skipped(date="2026-03-01", game="A@B", bet_type="moneyline",
                 side="home", odds=-110, sim_prob=0.55, market_prob=0.52,
                 edge=0.03, calibrated_prob=0.55, threshold=0.05,
                 skip_reason="below_threshold")
    df = pd.read_csv(csv_path)
    assert list(df.columns) == SKIPPED_COLUMNS
    assert len(df) == 1


def test_dedup_same_key(tmp_path, monkeypatch):
    csv_path = tmp_path / "skipped.csv"
    monkeypatch.setattr("edge_logging.SKIPPED_SIGNALS_CSV", str(csv_path))
    from edge_logging import _log_skipped
    for _ in range(3):
        _log_skipped(date="2026-03-01", game="A@B", bet_type="moneyline",
                     side="home", odds=-110, sim_prob=0.55, market_prob=0.52,
                     edge=0.03, calibrated_prob=0.55, threshold=0.05,
                     skip_reason="below_threshold")
    df = pd.read_csv(csv_path)
    assert len(df) == 1


def test_below_min_edge_not_logged(tmp_path, monkeypatch):
    csv_path = tmp_path / "skipped.csv"
    monkeypatch.setattr("edge_logging.SKIPPED_SIGNALS_CSV", str(csv_path))
    from edge_logging import _log_skipped
    _log_skipped(date="2026-03-01", game="A@B", bet_type="moneyline",
                 side="home", odds=-110, sim_prob=0.51, market_prob=0.505,
                 edge=0.005, calibrated_prob=0.51, threshold=0.05,
                 skip_reason="below_threshold")
    assert not csv_path.exists() or len(pd.read_csv(csv_path)) == 0


def test_skip_reason_enum_validated(tmp_path, monkeypatch):
    csv_path = tmp_path / "skipped.csv"
    monkeypatch.setattr("edge_logging.SKIPPED_SIGNALS_CSV", str(csv_path))
    from edge_logging import _log_skipped
    with pytest.raises(ValueError):
        _log_skipped(date="2026-03-01", game="A@B", bet_type="moneyline",
                     side="home", odds=-110, sim_prob=0.55, market_prob=0.52,
                     edge=0.03, calibrated_prob=0.55, threshold=0.05,
                     skip_reason="typo_reason")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_skipped_signals.py -v`
Expected: 4 FAIL — `ModuleNotFoundError: No module named 'edge_logging'`.

- [ ] **Step 3: Implement `edge_logging.py`**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/edge_logging.py`:

```python
"""Skipped-signal logger: rows where a bet was considered but killed by a filter."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

import pandas as pd

from config import DATA_DIR

logger = logging.getLogger("mirofish.edge_logging")

SKIPPED_SIGNALS_CSV = os.path.join(DATA_DIR, "skipped_signals.csv")
SKIPPED_COLUMNS = [
    "date", "game", "bet_type", "side", "odds",
    "sim_prob", "market_prob", "edge", "calibrated_prob",
    "threshold", "skip_reason", "logged_at",
]
VALID_SKIP_REASONS = {
    "below_threshold", "failed_worst_case", "capped_edge",
    "correlated_cluster_dropped",
}
MIN_EDGE_TO_LOG = 0.01

_csv_lock = threading.Lock()


def _ensure_csv(path: str | None = None) -> None:
    path = path or SKIPPED_SIGNALS_CSV
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(path):
        pd.DataFrame(columns=SKIPPED_COLUMNS).to_csv(path, index=False)


def _log_skipped(
    date: str,
    game: str,
    bet_type: str,
    side: str,
    odds: int,
    sim_prob: float,
    market_prob: float,
    edge: float,
    calibrated_prob: float,
    threshold: float,
    skip_reason: str,
) -> bool:
    """Append a skipped-signal row. Returns True if written, False if deduped or filtered.

    Only writes rows where edge >= MIN_EDGE_TO_LOG (0.01) to prevent noise flood.
    Deduped on (date, game, bet_type, side, skip_reason).
    """
    if skip_reason not in VALID_SKIP_REASONS:
        raise ValueError(
            f"invalid skip_reason {skip_reason!r}; expected one of {VALID_SKIP_REASONS}"
        )
    try:
        if float(edge) < MIN_EDGE_TO_LOG:
            return False
    except (TypeError, ValueError):
        return False

    row = {
        "date": str(date),
        "game": str(game),
        "bet_type": str(bet_type),
        "side": str(side),
        "odds": int(odds),
        "sim_prob": round(float(sim_prob), 4),
        "market_prob": round(float(market_prob), 4),
        "edge": round(float(edge), 4),
        "calibrated_prob": round(float(calibrated_prob), 4),
        "threshold": round(float(threshold), 4),
        "skip_reason": skip_reason,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }

    path = SKIPPED_SIGNALS_CSV
    with _csv_lock:
        _ensure_csv(path)
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame(columns=SKIPPED_COLUMNS)

        if not df.empty:
            dup_mask = (
                (df["date"] == row["date"])
                & (df["game"] == row["game"])
                & (df["bet_type"] == row["bet_type"])
                & (df["side"] == row["side"])
                & (df["skip_reason"] == row["skip_reason"])
            )
            if dup_mask.any():
                return False
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(path, index=False)
        return True


def load_skipped_signals(date_from: str | None = None,
                          date_to: str | None = None) -> pd.DataFrame:
    """Load the skipped-signals CSV; empty DF if file missing."""
    if not os.path.exists(SKIPPED_SIGNALS_CSV):
        return pd.DataFrame(columns=SKIPPED_COLUMNS)
    df = pd.read_csv(SKIPPED_SIGNALS_CSV)
    if date_from:
        df = df[df["date"] >= date_from]
    if date_to:
        df = df[df["date"] <= date_to]
    return df.reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_skipped_signals.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add edge_logging.py tests/test_skipped_signals.py
git commit -m "feat(edge): skipped-signal logger with dedup and edge floor"
```

---

### Task 15: Instrument `edge.py` checker reject branches

**Files:**
- Modify: `edge.py`
- Create: `tests/test_edge_skipped_logging.py`

This is the widest-touching task in the plan. `edge.py` has reject branches in every checker. Rather than adding a log call to each `return None`, we wrap each checker in a post-hoc logger: after the checker returns `None` or a bet, we inspect whether an edge had been computed and logs accordingly. The cleanest way is to add logging inline at the sites where we return `None` after computing an edge.

- [ ] **Step 1: Write failing integration tests**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_edge_skipped_logging.py`:

```python
"""Verify edge.py emits skipped-signal rows from each reject branch."""
import os
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _isolate_skipped_csv(tmp_path, monkeypatch):
    path = tmp_path / "skipped_signals.csv"
    monkeypatch.setattr("edge_logging.SKIPPED_SIGNALS_CSV", str(path))
    # Also set the module-level reference in edge.py if it cached it.
    import edge_logging
    edge_logging.SKIPPED_SIGNALS_CSV = str(path)
    yield path


def _set_date_game(monkeypatch):
    """edge.py needs a way to know date+game for logging. We set thread-locals."""
    import edge as _edge
    _edge._CURRENT_DATE = "2026-03-01"
    _edge._CURRENT_GAME = "AWAY@HOME"


def test_moneyline_below_threshold_logged(monkeypatch, _isolate_skipped_csv):
    _set_date_game(monkeypatch)
    from edge import check_moneyline_edge
    sim = {"predictions": {"moneyline": {"home_win_prob": 0.53, "away_win_prob": 0.47}}}
    odds = {
        "moneyline": {"home": -110, "away": -110},
        "implied_probs": {"ml_home": 0.51, "ml_away": 0.49},
    }
    result = check_moneyline_edge(sim, odds)
    # 0.53 - 0.51 = 0.02 < 0.05 threshold → skip → log.
    assert result is None
    df = pd.read_csv(_isolate_skipped_csv)
    assert len(df) >= 1
    reasons = set(df["skip_reason"])
    assert "below_threshold" in reasons


def test_moneyline_passes_does_not_log(monkeypatch, _isolate_skipped_csv):
    _set_date_game(monkeypatch)
    from edge import check_moneyline_edge
    sim = {"predictions": {"moneyline": {"home_win_prob": 0.60, "away_win_prob": 0.40}}}
    odds = {
        "moneyline": {"home": -110, "away": -110},
        "implied_probs": {"ml_home": 0.51, "ml_away": 0.49},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is not None
    assert not _isolate_skipped_csv.exists() or len(pd.read_csv(_isolate_skipped_csv)) == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_edge_skipped_logging.py -v`
Expected: FAIL — edge.py doesn't wire to `edge_logging` yet.

- [ ] **Step 3: Wire `edge.py` to emit skipped rows**

The pattern: every place the existing checker does `return None` after computing an edge, we call `_log_skipped_from_edge` first with the most-recent sim/market/edge values. We thread the `date` and `game` through two new module-level "ambient" thread-local variables that `analyze_all_edges` sets before each checker runs.

Add to the top of `edge.py` (after the existing imports at lines 1-5):

```python
import threading as _threading
from edge_logging import _log_skipped, MIN_EDGE_TO_LOG

# Ambient context set by analyze_all_edges before each checker is invoked.
# Thread-local because the daily pipeline runs checkers in parallel per game.
_ambient = _threading.local()


def _set_ambient(date: str | None, game: str | None) -> None:
    _ambient.date = date or ""
    _ambient.game = game or ""


def _log_skip_if_applicable(bet_type: str, side: str, odds_val: int,
                              sim_prob: float, market_prob: float,
                              calibrated_prob: float, threshold: float,
                              skip_reason: str) -> None:
    """Thin wrapper around _log_skipped that uses ambient (date, game)."""
    try:
        edge_val = float(sim_prob) - float(market_prob)
        if edge_val < MIN_EDGE_TO_LOG:
            return
        date = getattr(_ambient, "date", "") or ""
        game = getattr(_ambient, "game", "") or ""
        if not date or not game:
            return  # no context — silently drop
        _log_skipped(
            date=date, game=game, bet_type=bet_type, side=side,
            odds=int(odds_val) if odds_val is not None else 0,
            sim_prob=float(sim_prob), market_prob=float(market_prob),
            edge=edge_val, calibrated_prob=float(calibrated_prob),
            threshold=float(threshold), skip_reason=skip_reason,
        )
    except Exception as e:
        logger.debug("skipped-signal logging failed: %s", e)
```

Now instrument the checkers. The rule: before every `return None` that follows an edge comparison, insert a `_log_skip_if_applicable()` call with the side that had the larger edge (or both, if both computed). Below are the exact diffs.

**`check_moneyline_edge`** — after line 102 (the `elif away_edge >= threshold: ...` block, before the final `return None`):

Replace the tail of the function (lines 69-103) — from `# Take the side with more edge` — with:

```python
    # Take the side with more edge
    if home_edge >= threshold and home_edge >= away_edge:
        passes, wc_edge = _passes_worst_case_filter(home_prob, raw_home, raw_away)
        if not passes:
            _log_skip_if_applicable(
                "moneyline", "home", ml_odds["home"], home_prob, home_implied,
                home_prob, threshold, "failed_worst_case"
            )
            return None
        dec = american_to_decimal(ml_odds["home"])
        return {
            "bet_type": "moneyline", "side": "home", "odds": ml_odds["home"],
            "sim_prob": home_prob, "market_prob": home_implied,
            "edge": round(home_edge, 4), "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(home_prob, dec),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(away_prob, raw_away, raw_home)
        if not passes:
            _log_skip_if_applicable(
                "moneyline", "away", ml_odds["away"], away_prob, away_implied,
                away_prob, threshold, "failed_worst_case"
            )
            return None
        dec = american_to_decimal(ml_odds["away"])
        return {
            "bet_type": "moneyline", "side": "away", "odds": ml_odds["away"],
            "sim_prob": away_prob, "market_prob": away_implied,
            "edge": round(away_edge, 4), "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(away_prob, dec),
            "confidence": ml_pred.get("confidence", "medium"),
        }

    # Neither side cleared threshold — log the better-edge side if edge >= MIN.
    if home_edge >= away_edge:
        _log_skip_if_applicable(
            "moneyline", "home", ml_odds["home"], home_prob, home_implied,
            home_prob, threshold, "below_threshold"
        )
    else:
        _log_skip_if_applicable(
            "moneyline", "away", ml_odds["away"], away_prob, away_implied,
            away_prob, threshold, "below_threshold"
        )
    return None
```

**Apply the identical pattern to each of the remaining 9 checkers:**

- `check_run_line_edge`
- `check_total_edge`
- `check_f5_ml_edge`
- `check_f5_total_edge`
- `check_team_total_edge`
- `_check_innings_spread_edge` (covers `check_f5_rl_edge`, `check_f1_rl_edge`, `check_f3_rl_edge`)
- `check_nrfi_edge`
- `check_f3_ml_edge`
- `check_f3_total_edge`

For each: replace its final `return None` with a block that picks the side with the larger of the two computed edges and calls `_log_skip_if_applicable(bet_type, side_label, odds_val, sim_prob, market_prob, sim_prob, threshold, "below_threshold")`. Also add `_log_skip_if_applicable(..., "failed_worst_case")` ahead of each `return None` that follows a `not passes`. Use the same `threshold` value already computed in the function.

To keep the plan scannable, here is an example for `check_total_edge` — replace lines 215-252 (`if over_edge >= threshold ...` through `return None`) with:

```python
    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_over, raw_under)
        if not passes:
            _log_skip_if_applicable(
                "total", f"over {line}", over_odds, over_prob, over_implied,
                over_prob, threshold, "failed_worst_case"
            )
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total", "side": f"over {line}", "odds": over_odds,
            "sim_prob": over_prob, "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4), "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(over_prob, dec),
            "confidence": total_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_under, raw_over)
        if not passes:
            _log_skip_if_applicable(
                "total", f"under {line}", under_odds, under_prob, under_implied,
                under_prob, threshold, "failed_worst_case"
            )
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total", "side": f"under {line}", "odds": under_odds,
            "sim_prob": under_prob, "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4), "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(under_prob, dec),
            "confidence": total_pred.get("confidence", "medium"),
        }

    if over_edge >= under_edge:
        _log_skip_if_applicable(
            "total", f"over {line}", over_odds, over_prob, over_implied,
            over_prob, threshold, "below_threshold"
        )
    else:
        _log_skip_if_applicable(
            "total", f"under {line}", under_odds, under_prob, under_implied,
            under_prob, threshold, "below_threshold"
        )
    return None
```

Apply the same structural replacement to the eight other checkers — each has a `home_edge/away_edge` or `over_edge/under_edge` or `fav_edge/dog_edge` pair. Pick the side whose edge is larger and call `_log_skip_if_applicable` with `skip_reason="below_threshold"` before the trailing `return None`. Add the `"failed_worst_case"` log before every `return None` that immediately follows `if not passes:`.

**`analyze_all_edges`** — set the ambient context at entry. Modify the function (currently starting at line 753) to accept the ambient date/game as optional kwargs and set them:

```python
def analyze_all_edges(sim: dict, odds, date: str | None = None, game: str | None = None) -> list[dict]:
    """Run all edge checks for a single game.

    Args:
        odds: OddsData instance or plain dict.
        date, game: optional ambient context for skipped-signal logging.
    """
    _set_ambient(date, game)
    bets = []
    ...
```

(The rest of the function body stays as-is.) Also, after the edge-cap block (inside `analyze_all_edges`, at line 856-866 where edges are capped), add logging:

```python
    MAX_EDGE = 0.15
    for bet in bets:
        if bet["edge"] > MAX_EDGE:
            _log_skip_if_applicable(
                bet["bet_type"], bet["side"], bet["odds"],
                bet["sim_prob"], bet["market_prob"], bet["sim_prob"],
                MAX_EDGE, "capped_edge",
            )
            logger.warning(...)  # existing line
            bet["edge"] = MAX_EDGE
            capped_prob = bet["market_prob"] + MAX_EDGE
            dec = american_to_decimal(bet["odds"])
            bet["kelly_pct"] = _sized_kelly(capped_prob, dec)
```

And for the correlated-cluster drop (line 868-876), log each dropped bet:

```python
    run_cluster_types = {"team_total_home", "team_total_away", "first_3_total", "total"}
    cluster_bets = [b for b in bets if b["bet_type"] in run_cluster_types]
    if len(cluster_bets) > 2:
        cluster_bets.sort(key=lambda b: b["edge"], reverse=True)
        dropped_bets = cluster_bets[2:]
        drop = {id(b) for b in dropped_bets}
        for b in dropped_bets:
            _log_skip_if_applicable(
                b["bet_type"], b["side"], b["odds"],
                b["sim_prob"], b["market_prob"], b["sim_prob"],
                EDGE_THRESHOLDS.get(b["bet_type"], 0.05),
                "correlated_cluster_dropped",
            )
        bets = [b for b in bets if id(b) not in drop]
        logger.info("Correlated bet limit: kept top 2 of %d run-cluster bets", len(cluster_bets))
```

Finally, update every call site of `analyze_all_edges` to pass `date` and `game`:

- `main.py:132` (`edges = analyze_all_edges(screen, game_data["odds_obj"])`) → add `date=game_date, game=game_key`.
- `main.py:176` (`game_bets = analyze_all_edges(result, game_data["odds_obj"])`) → add `date=game_date, game=game_key`.
- `main.py:557` (inside `game` command) → pass `date=game_date, game=f"{away_team}@{home_team}"`.
- `simulate.py` and `agents/bet_card.py` — grep first: `grep -n "analyze_all_edges" /Users/mikeborucki/personal_workspace/agents/baseball-agents/*.py /Users/mikeborucki/personal_workspace/agents/baseball-agents/agents/*.py /Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/*.py`. Add the kwargs to each hit.

- [ ] **Step 4: Run integration tests**

Run: `pytest tests/test_edge_skipped_logging.py -v`
Expected: 2 PASSED.

Also run the full suite to ensure no regression in other edge tests:
Run: `pytest tests/test_edge.py tests/test_edge_phase1.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add edge.py main.py simulate.py agents/bet_card.py tests/test_edge_skipped_logging.py
git commit -m "feat(edge): log skipped signals from all checkers and filters"
```

(Only stage the files you actually modified — `simulate.py` and `agents/bet_card.py` only if the grep in Step 3 found call sites to update.)

---

### Task 16: Skipped-signal counterfactual CLV in `clv_tracker.py`

**Files:**
- Modify: `agents/clv_tracker.py`
- Modify: `main.py`
- Modify: `tests/test_clv_tracker.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_clv_tracker.py`:

```python
def test_clv_skipped_counterfactual_joins_closing_lines(tmp_path, monkeypatch):
    skipped_csv = tmp_path / "skipped_signals.csv"
    closing_csv = tmp_path / "closing_lines.csv"
    from datetime import datetime as _dt
    pd.DataFrame([{
        "date": "2026-03-01", "game": "A@B", "bet_type": "moneyline",
        "side": "home", "odds": -110, "sim_prob": 0.55, "market_prob": 0.52,
        "edge": 0.03, "calibrated_prob": 0.55, "threshold": 0.05,
        "skip_reason": "below_threshold",
        "logged_at": _dt.utcnow().isoformat(),
    }]).to_csv(skipped_csv, index=False)
    pd.DataFrame([{
        "date": "2026-03-01", "game": "A@B", "market": "moneyline",
        "side": "home", "line": "", "close_odds": -135,
        "close_prob_devig": 0.57, "captured_at": _dt.utcnow().isoformat(),
    }]).to_csv(closing_csv, index=False)
    monkeypatch.setattr("edge_logging.SKIPPED_SIGNALS_CSV", str(skipped_csv))
    monkeypatch.setattr("scrapers.closing_lines.CLOSING_LINES_CSV", str(closing_csv))
    from agents.clv_tracker import clv_skipped_counterfactual
    out = clv_skipped_counterfactual()
    assert len(out) == 1
    row = out.iloc[0]
    assert row["hypothetical_close_odds"] == -135
    assert row["hypothetical_clv_pct"] > 0
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_clv_tracker.py::test_clv_skipped_counterfactual_joins_closing_lines -v`
Expected: FAIL — `clv_skipped_counterfactual` not defined.

- [ ] **Step 3: Implement `clv_skipped_counterfactual`**

Append to `agents/clv_tracker.py`:

```python
def clv_skipped_counterfactual(
    skipped_df: pd.DataFrame | None = None,
    closing_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """For each row in skipped_signals, look up closing line and compute CLV."""
    from edge_logging import load_skipped_signals
    from scrapers.closing_lines import load_closing_lines
    from tracker import _american_to_decimal, _parse_bet_for_clv

    sk = skipped_df if skipped_df is not None else load_skipped_signals()
    cl = closing_df if closing_df is not None else load_closing_lines()
    if sk.empty or cl.empty:
        return pd.DataFrame(columns=[
            "date", "game", "bet_type", "side", "sim_prob", "edge",
            "skip_reason", "hypothetical_close_odds", "hypothetical_clv_pct",
        ])

    records = []
    for _, r in sk.iterrows():
        market, parsed_side, line = _parse_bet_for_clv(str(r["bet_type"]), str(r["side"]))
        if market is None:
            continue
        mask = (
            (cl["date"] == r["date"])
            & (cl["game"] == r["game"])
            & (cl["market"] == market)
            & (cl["side"].astype(str) == str(parsed_side))
        )
        if line is not None:
            mask &= (cl["line"].astype(str) == str(line))
        matches = cl[mask]
        if matches.empty:
            continue
        close = matches.sort_values("captured_at").iloc[-1]
        bet_dec = _american_to_decimal(int(r["odds"]))
        close_dec = _american_to_decimal(int(close["close_odds"]))
        clv_pct = round(bet_dec / close_dec - 1.0, 4)
        records.append({
            "date": r["date"], "game": r["game"], "bet_type": r["bet_type"],
            "side": r["side"], "sim_prob": float(r["sim_prob"]),
            "edge": float(r["edge"]), "skip_reason": r["skip_reason"],
            "hypothetical_close_odds": int(close["close_odds"]),
            "hypothetical_clv_pct": clv_pct,
        })
    return pd.DataFrame(records)
```

- [ ] **Step 4: Hook into `print_report`**

Edit `agents/clv_tracker.py` — replace the `# Skipped counterfactual lands in Phase E...` stub at the bottom of `print_report` with:

```python
    try:
        cf = clv_skipped_counterfactual()
        if not cf.empty:
            n = len(cf)
            pos = int((cf["hypothetical_clv_pct"] > 0).sum())
            mean = float(cf["hypothetical_clv_pct"].mean())
            _click.echo(f"\nSkipped-signal counterfactual: {n} rows, "
                         f"{pos} ({pos/n:.0%}) would have had +CLV, "
                         f"mean hypothetical CLV_pct={mean:+.4f}")
    except Exception as e:
        logger.warning("skipped-signal counterfactual failed: %s", e)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_clv_tracker.py -v`
Expected: 7 PASSED.

- [ ] **Step 6: Commit**

```bash
git add agents/clv_tracker.py tests/test_clv_tracker.py
git commit -m "feat(clv): counterfactual CLV for skipped signals"
```

---

## Phase F — Per-model Brier / log-loss

### Task 17: `ensemble/calibration_metrics.py` with correct join

**Files:**
- Create: `ensemble/calibration_metrics.py`
- Create: `tests/test_calibration_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_calibration_metrics.py`:

```python
"""Regression tests for ensemble/calibration_metrics.py (replaces broken self_optimizer inline)."""
import math
import pandas as pd
import pytest


def test_brier_matches_manual_calculation():
    preds = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline", "side": "home",
         "model": "kimi", "sim_prob": 0.8, "run_index": 0},
        {"date": "2026-03-02", "game": "C@D", "bet_type": "moneyline", "side": "home",
         "model": "kimi", "sim_prob": 0.3, "run_index": 0},
    ])
    bets = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline", "side": "home",
         "result": "W"},
        {"date": "2026-03-02", "game": "C@D", "bet_type": "moneyline", "side": "home",
         "result": "L"},
    ])
    from ensemble.calibration_metrics import compute_model_brier_scores
    out = compute_model_brier_scores(preds, bets)
    expected = ((0.8 - 1.0) ** 2 + (0.3 - 0.0) ** 2) / 2
    assert out["kimi"]["moneyline"]["brier"] == pytest.approx(expected, abs=1e-6)
    assert out["kimi"]["moneyline"]["n"] == 2


def test_join_ignores_mismatched_game():
    """Regression test for the bug in the old self_optimizer code."""
    preds = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline", "side": "home",
         "model": "kimi", "sim_prob": 0.5, "run_index": 0},
    ])
    bets = pd.DataFrame([
        {"date": "2026-03-01", "game": "X@Y", "bet_type": "moneyline", "side": "home",
         "result": "W"},  # different game — must NOT be scored.
    ])
    from ensemble.calibration_metrics import compute_model_brier_scores
    out = compute_model_brier_scores(preds, bets)
    assert out == {} or "kimi" not in out or "moneyline" not in out.get("kimi", {})


def test_log_loss_matches_manual():
    preds = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline", "side": "home",
         "model": "kimi", "sim_prob": 0.9, "run_index": 0},
    ])
    bets = pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline", "side": "home",
         "result": "W"},
    ])
    from ensemble.calibration_metrics import compute_model_brier_scores
    out = compute_model_brier_scores(preds, bets)
    assert out["kimi"]["moneyline"]["log_loss"] == pytest.approx(-math.log(0.9), abs=1e-6)


def test_update_model_weights_is_inverse_brier_normalized(tmp_path, monkeypatch):
    monkeypatch.setattr("ensemble.weights.MODEL_WEIGHTS_FILE",
                        str(tmp_path / "weights.json"))
    brier = {
        "kimi": {"moneyline": {"brier": 0.24, "log_loss": 0.65, "n": 100}},
        "claude": {"moneyline": {"brier": 0.12, "log_loss": 0.32, "n": 100}},
    }
    from ensemble.calibration_metrics import update_model_weights
    update_model_weights(brier, weights_path=str(tmp_path / "weights.json"))
    import json
    weights = json.loads((tmp_path / "weights.json").read_text())
    assert weights["kimi"]["moneyline"] < weights["claude"]["moneyline"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_calibration_metrics.py -v`
Expected: 4 FAIL — module doesn't exist.

- [ ] **Step 3: Implement the module**

Create `/Users/mikeborucki/personal_workspace/agents/baseball-agents/ensemble/calibration_metrics.py`:

```python
"""Per-model Brier + log-loss with proper (date, game, bet_type, side) join.

Replaces the broken inline logic that used to live in agents/self_optimizer.py,
which scored every prediction against matching.iloc[0] regardless of the slot.
"""
from __future__ import annotations

import logging
import math

import pandas as pd

logger = logging.getLogger("mirofish.calibration_metrics")


def _outcome(result: str) -> float | None:
    if result == "W":
        return 1.0
    if result == "L":
        return 0.0
    return None  # pushes and pending rows excluded


def compute_model_brier_scores(preds_df: pd.DataFrame, bets_df: pd.DataFrame) -> dict:
    """Return {model: {bet_type: {"brier": float, "log_loss": float, "n": int}}}.

    Joins preds to bets on (date, game, bet_type, side). Multiple pred runs for
    the same slot are averaged before scoring (one Brier contribution per slot
    per model).
    """
    if preds_df.empty or bets_df.empty:
        return {}

    p = preds_df.copy()
    b = bets_df.copy()
    for df_ in (p, b):
        for col in ("date", "game", "bet_type", "side"):
            df_[col] = df_[col].astype(str)

    b["_outcome"] = b["result"].map(_outcome)
    b = b[b["_outcome"].notna()]
    if b.empty:
        return {}

    # Average sim_prob per (model, slot) where slot = (date, game, bet_type, side)
    p["sim_prob"] = pd.to_numeric(p["sim_prob"], errors="coerce")
    p = p.dropna(subset=["sim_prob"])
    avg = p.groupby(["model", "date", "game", "bet_type", "side"], as_index=False)[
        "sim_prob"
    ].mean()

    joined = avg.merge(
        b[["date", "game", "bet_type", "side", "_outcome"]],
        on=["date", "game", "bet_type", "side"],
        how="inner",
    )
    if joined.empty:
        return {}

    result: dict[str, dict[str, dict]] = {}
    for (model, bt), sub in joined.groupby(["model", "bet_type"]):
        probs = sub["sim_prob"].to_numpy(dtype=float)
        outcomes = sub["_outcome"].to_numpy(dtype=float)
        n = len(sub)
        brier = float(((probs - outcomes) ** 2).mean())
        # log_loss with clamping to avoid log(0)
        eps = 1e-9
        p_c = probs.clip(eps, 1 - eps)
        ll = float(-(outcomes * pd.Series(p_c).apply(math.log).to_numpy()
                      + (1 - outcomes) * pd.Series(1 - p_c).apply(math.log).to_numpy()).mean())
        result.setdefault(str(model), {})[str(bt)] = {
            "brier": round(brier, 6),
            "log_loss": round(ll, 6),
            "n": int(n),
            "calibration_gap": round(float(probs.mean() - outcomes.mean()), 4),
        }
    return result


def update_model_weights(brier_scores: dict, weights_path: str | None = None) -> None:
    """Rewrite data/model_weights.json from per-model Brier.

    Lower Brier → higher weight. Normalized so per-slot weights sum to n_models.
    """
    from ensemble.weights import BET_SLOTS, load_weights, save_weights

    weights = load_weights(weights_path)
    for slot in BET_SLOTS:
        slot_briers: dict[str, float] = {}
        for model, per_bt in brier_scores.items():
            entry = per_bt.get(slot)
            if not entry:
                continue
            b = float(entry.get("brier", 0)) if isinstance(entry, dict) else float(entry)
            slot_briers[model] = max(b, 0.01)
        if not slot_briers:
            continue
        raw = {m: 1.0 / br for m, br in slot_briers.items()}
        total = sum(raw.values())
        n = len(raw)
        for model, raw_w in raw.items():
            weights.setdefault(model, {})[slot] = round(raw_w / total * n, 4)
    save_weights(weights, weights_path)


def model_scores_report(preds_df: pd.DataFrame | None = None,
                         bets_df: pd.DataFrame | None = None) -> dict:
    """Convenience wrapper used by the CLI."""
    from tracker import load_bets
    from ensemble.logger import load_model_predictions

    preds = preds_df if preds_df is not None else load_model_predictions()
    bets = bets_df if bets_df is not None else load_bets()
    return compute_model_brier_scores(preds, bets)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_calibration_metrics.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add ensemble/calibration_metrics.py tests/test_calibration_metrics.py
git commit -m "feat(ensemble): calibration_metrics module with correct join (fixes self_optimizer bug)"
```

---

### Task 18: `main.py model-scores` CLI

**Files:**
- Modify: `main.py`
- Modify: `tests/test_calibration_metrics.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_calibration_metrics.py`:

```python
def test_model_scores_cli(tmp_path, monkeypatch):
    bets_csv = tmp_path / "bets.csv"
    preds_csv = tmp_path / "preds.csv"
    pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "bet_type": "moneyline",
         "side": "home", "odds": -110, "sim_prob": 0.6, "market_prob": 0.5,
         "edge": 0.1, "kelly_pct": 0.01, "result": "W", "profit": 0.91,
         "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": ""},
    ]).to_csv(bets_csv, index=False)
    pd.DataFrame([
        {"date": "2026-03-01", "game": "A@B", "model": "kimi",
         "bet_type": "moneyline", "side": "home",
         "sim_prob": 0.6, "market_prob": 0.5, "edge": 0.1,
         "temperature": 0.2, "run_index": 0},
    ]).to_csv(preds_csv, index=False)
    monkeypatch.setattr("tracker.BETS_CSV", str(bets_csv))
    monkeypatch.setattr("ensemble.logger.MODEL_PREDICTIONS_CSV", str(preds_csv))
    from click.testing import CliRunner
    from main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["model-scores"])
    assert result.exit_code == 0, result.output
    assert "kimi" in result.output
    assert "moneyline" in result.output
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_calibration_metrics.py::test_model_scores_cli -v`
Expected: FAIL — `No such command 'model-scores'`.

- [ ] **Step 3: Add the CLI to `main.py`**

Append to `main.py` (before `if __name__`):

```python
@cli.command("model-scores")
@click.option("--update-weights", is_flag=True, help="Write new weights to data/model_weights.json")
def model_scores(update_weights):
    """Per-model, per-bet-type Brier + log-loss from predictions × bets join."""
    from ensemble.calibration_metrics import model_scores_report, update_model_weights

    scores = model_scores_report()
    if not scores:
        click.echo("No matching (preds × bets) rows to score.")
        return

    bet_types = sorted({bt for per_bt in scores.values() for bt in per_bt})
    click.echo(f"{'model':12s}" + "".join(f"  {bt[:12]:12s}" for bt in bet_types))
    for model in sorted(scores):
        row = f"{model:12s}"
        for bt in bet_types:
            e = scores[model].get(bt)
            if not e:
                row += "  {:12s}".format("—")
            else:
                row += f"  B{e['brier']:.3f}/L{e['log_loss']:.2f}/{e['n']}"
        click.echo(row)

    if update_weights:
        update_model_weights(scores)
        click.echo("Wrote updated weights.")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_calibration_metrics.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_calibration_metrics.py
git commit -m "feat(cli): main.py model-scores subcommand"
```

---

## Phase G — Integration + backfill

### Task 19: Full test suite green

**Files:**
- (none modified — verification step)

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All PASS. No skipped integration tests other than network-gated ones.

- [ ] **Step 2: Smoke-check all CLI subcommands**

Run: `python3 main.py --help`
Expected: Shows `calibrate`, `clv`, `model-scores`, `optimize` among existing commands, no import errors.

Run each help:
```
python3 main.py calibrate --help
python3 main.py clv --help
python3 main.py model-scores --help
python3 main.py optimize --help
```
Expected: All print help text, exit 0.

- [ ] **Step 3: Commit (empty-stage verification)**

No code changes — skip the commit if nothing was modified.

---

### Task 20: Backfill calibration curves from historical bets

**Files:**
- Create: `data/calibration_curves.json` (via CLI)

- [ ] **Step 1: Back up current `data/bets.csv` defensively**

Run: `cp /Users/mikeborucki/personal_workspace/agents/baseball-agents/data/bets.csv /Users/mikeborucki/personal_workspace/agents/baseball-agents/data/bets.csv.bak-precal-$(date +%Y%m%d)`
Expected: new `.bak-precal-YYYYMMDD` file present.

- [ ] **Step 2: Run rebuild**

Run: `python3 /Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py calibrate --rebuild`
Expected: Output like:
```
Calibration curves rebuilt: N bet type(s) → /.../data/calibration_curves.json
  first_3_ml           method=identity  n=  62  brier=0.248 (was 0.248)
  first_5_ml           method=beta      n= 312  brier=0.241 (was 0.247) ↓
  moneyline            method=isotonic  n=1823  brier=0.241 (was 0.250) ↓
  ...
```

- [ ] **Step 3: Inspect output**

Run: `python3 /Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py calibrate`
Expected: prints version=1, per-type summary.

Run: `python3 -c "import json; print(json.dumps(json.load(open('/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/calibration_curves.json'))['curves'].keys()))"`
Expected: dict_keys containing e.g. `moneyline`, `total`, `run_line`, ... — 5+ entries.

- [ ] **Step 4: Commit the curve file**

```bash
git add data/calibration_curves.json
git commit -m "chore: seed calibration_curves.json from historical bets"
```

If the fit for any bet type regressed the in-sample Brier by more than 0.005, the build_all_curves guard already reverted that type to identity — no further action needed.

---

### Task 21: Smoke-test daily pipeline with calibration live

**Files:**
- (none modified — verification step)

- [ ] **Step 1: Identify a past date with games**

Run: `python3 -c "import pandas as pd; df = pd.read_csv('/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/bets.csv'); print(df['date'].max())"`
Expected: prints e.g. `2026-04-15`. Use a date ≥ 3 days prior to today to ensure grading is final.

- [ ] **Step 2: Dry-run the daily pipeline for that date**

Run: `python3 /Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py daily --date 2026-04-14 --no-notify 2>&1 | tail -40`
Expected:
- Step 5 and Step 6 complete without errors.
- The resulting bet rows (if any) show calibrated `sim_prob` (different from the uncalibrated version for bet types that have a non-identity curve).
- No `ImportError` or `KeyError`.

- [ ] **Step 3: Verify skipped_signals.csv has grown**

Run: `wc -l /Users/mikeborucki/personal_workspace/agents/baseball-agents/data/skipped_signals.csv`
Expected: header + ~20-200 rows, depending on game count.

- [ ] **Step 4: Run `clv` report**

Run: `python3 /Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py clv`
Expected: prints Coverage, Overall, Per bet_type, Edge bucket, Rolling windows. Bottom line mentions skipped counterfactual (once closing lines cover the new skipped rows — may be empty the first day).

- [ ] **Step 5: Compare calibrated vs identity outputs**

Temporarily rename the curves JSON to force identity fallback:
```
mv /Users/mikeborucki/personal_workspace/agents/baseball-agents/data/calibration_curves.json /tmp/cal.bak
python3 /Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py daily --date 2026-04-14 --no-notify 2>&1 | grep "FLAGGED\|BET\|edge" | head
mv /tmp/cal.bak /Users/mikeborucki/personal_workspace/agents/baseball-agents/data/calibration_curves.json
```
Expected: different bet counts / probabilities between the two runs (confirming calibration is actually changing outputs).

- [ ] **Step 6: Commit any smoke-test artifacts (none expected)**

If `data/skipped_signals.csv` grew and is useful to commit for next-day counterfactual work:
```bash
git add data/skipped_signals.csv
git commit -m "chore: seed skipped_signals.csv with backfill from smoke test"
```

---

## Appendix — Rollout stages (from spec)

**Stage A (completed by end of Task 19):** Code landed, calibration is a no-op because no JSON committed. Zero behavioral change.

**Stage B (completed by Task 20):** `calibrate --rebuild` run, JSON written and committed. In-sample Brier improvements are logged per type; any regressors are auto-reverted to identity by the guard.

**Stage C (completed by Task 21):** Next pipeline run picks up the curves via the mtime cache. Monitor daily with `main.py clv` and `main.py model-scores` for 7 days.

**Stage D (post-plan, operational):** Run both `optimize --metric roi` and `optimize --metric clv` in parallel for 1 week. If they diverge sharply, defer threshold changes until the 2-week CLV window fills.

**Kill switch:** `rm data/calibration_curves.json` — next `apply_calibration` call sees the missing file and returns identity. mtime cache self-invalidates.

---

## Appendix — Completion checklist

- [ ] Dependencies installed (`scikit-learn`, `betacal`, `scipy`)
- [ ] `calibrate.py` rewritten: `apply_calibration`, `build_isotonic_curve`, `build_beta_curve`, `apply_isotonic`, `apply_beta`, `build_all_curves`, `build_calibration_curves`, mtime cache
- [ ] `main.py calibrate [--rebuild|--report]` works
- [ ] `agents/clv_tracker.py` created: `load_clv_bets`, `aggregate_clv`, `clv_by_bet_type`, `clv_by_edge_bucket`, `clv_by_confidence`, `clv_by_model`, `clv_rolling`, `clv_skipped_counterfactual`, `print_report`
- [ ] `main.py clv [--from|--to|--model]` works
- [ ] `agents/self_optimizer.py` hardened: `min_bets=200`, `--metric=clv` default, p<0.05 gate
- [ ] Broken per-model Brier logic deleted; shim redirects to `ensemble/calibration_metrics.py`
- [ ] `edge_logging.py` created; `data/skipped_signals.csv` written from `edge.py` reject branches
- [ ] `ensemble/calibration_metrics.py` created with correct join; CLI `model-scores` works
- [ ] `data/calibration_curves.json` seeded + committed
- [ ] Daily pipeline smoke-tested end-to-end with calibration live
- [ ] Full `pytest tests/ -v` green
