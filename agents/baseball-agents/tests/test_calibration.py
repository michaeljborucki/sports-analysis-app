"""Tests for probability calibration layer."""
import json
import numpy as np
import pandas as pd
import pytest

from calibrate import (
    fit_calibrators,
    calibrate_prob,
    save_calibrators,
    load_calibrators,
    _side_bucket,
)


# ---------------------------------------------------------------------------
# _side_bucket: normalize any side string to over/under/other
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("side,expected", [
    ("over 1.5", "over"),
    ("Player Name over 0.5", "over"),
    ("under 8.5", "under"),
    ("Aaron Judge under 1.5", "under"),
    ("home", "other"),
    ("away -1.5", "other"),
    ("NRFI", "other"),
])
def test_side_bucket_classifies(side, expected):
    assert _side_bucket(side) == expected


# ---------------------------------------------------------------------------
# Production calibration file invariant
# ---------------------------------------------------------------------------

def test_batter_props_intentionally_uncalibrated():
    """No batter-prop market may have a fitted calibrator.

    Dropped 2026-06-03 after fixing the out_pct strikeout double-count and
    switching to per-stat regression in scrapers/player_stats.py. Those fixes
    are GLOBAL — they changed raw probabilities for every batter prop, so all
    the old batter calibrators were fit on biased pre-fix probabilities and
    would partly undo the correction. Batter props now flow through the
    SIM_PROB_CAP backstop only until refit on clean post-fix data.

    Pitcher and non-prop calibrators are unaffected (different stat path).
    """
    import os
    from config import DATA_DIR
    path = os.path.join(DATA_DIR, "calibration.json")
    with open(path) as f:
        cal = json.load(f)
    stale = [k for k in cal if k.startswith("batter_")]
    assert stale == [], f"stale batter calibrators present (refit on post-fix data first): {stale}"


# ---------------------------------------------------------------------------
# fit_calibrators: learns from (predicted, actual) pairs
# ---------------------------------------------------------------------------

def _synthetic_bets(bet_type, side, raw_probs, actual_win_rates, n_per_bucket=200):
    """Generate synthetic bets where model predicts raw_probs but actual win rate
    is actual_win_rates (simulating miscalibration)."""
    rows = []
    rng = np.random.default_rng(42)
    for raw, actual in zip(raw_probs, actual_win_rates):
        for _ in range(n_per_bucket):
            won = rng.random() < actual
            rows.append({
                "bet_type": bet_type,
                "side": side,
                "sim_prob": raw,
                "result": "W" if won else "L",
            })
    return pd.DataFrame(rows)


def test_fit_calibrators_corrects_overconfidence():
    """Model says 80% → actually wins 60%: calibrator should map 0.80 → ~0.60."""
    df = _synthetic_bets(
        "batter_rbis", "Aaron Judge over 1.5",
        raw_probs=[0.50, 0.60, 0.70, 0.80],
        actual_win_rates=[0.45, 0.50, 0.55, 0.60],
        n_per_bucket=500,
    )
    calibrators = fit_calibrators(df)
    key = "batter_rbis|over"
    assert key in calibrators

    calibrated_at_80 = calibrate_prob("batter_rbis", "Aaron Judge over 1.5", 0.80, calibrators)
    # Should map 0.80 → something close to 0.60 (tolerant to noise)
    assert 0.55 < calibrated_at_80 < 0.65


def test_fit_calibrators_separates_over_under():
    """Unders and overs on same bet_type get separate calibrators — critical because
    the bias direction differs."""
    over_bets = _synthetic_bets("batter_rbis", "X over 1.5",
                                [0.60, 0.70], [0.40, 0.45], n_per_bucket=500)
    under_bets = _synthetic_bets("batter_rbis", "X under 1.5",
                                 [0.60, 0.70], [0.60, 0.70], n_per_bucket=500)
    df = pd.concat([over_bets, under_bets], ignore_index=True)

    calibrators = fit_calibrators(df)
    cal_over = calibrate_prob("batter_rbis", "X over 1.5", 0.70, calibrators)
    cal_under = calibrate_prob("batter_rbis", "X under 1.5", 0.70, calibrators)
    # Over should be pulled way down; under should stay near 0.70
    assert cal_over < 0.55, f"over calibration expected < 0.55, got {cal_over}"
    assert cal_under > 0.65, f"under calibration expected > 0.65, got {cal_under}"


def test_calibrate_prob_unknown_bet_type_returns_raw():
    """Graceful fallback when no calibrator exists for a bet_type."""
    calibrators = {}
    assert calibrate_prob("unseen_bet_type", "over 0.5", 0.65, calibrators) == 0.65


def test_calibrate_prob_insufficient_data_returns_raw():
    """A bet_type with only 10 samples shouldn't have a calibrator built — the
    fitter should skip it and the app-layer should fall back to raw."""
    df = _synthetic_bets("rare_bet", "over 0.5", [0.60], [0.40], n_per_bucket=10)
    calibrators = fit_calibrators(df, min_samples=50)
    assert "rare_bet|over" not in calibrators
    # Calibrate returns raw when no calibrator exists
    assert calibrate_prob("rare_bet", "over 0.5", 0.70, calibrators) == 0.70


def test_calibrate_prob_clamps_outside_fit_range():
    """Extrapolation is dangerous — probs outside the training range clamp
    to the nearest known calibrated value."""
    df = _synthetic_bets("test_bet", "X over 1.5",
                         [0.55, 0.60, 0.65], [0.50, 0.55, 0.60], n_per_bucket=400)
    calibrators = fit_calibrators(df)
    # Below range: clamp to lowest fitted output
    low = calibrate_prob("test_bet", "X over 1.5", 0.30, calibrators)
    # Above range: clamp to highest fitted output
    high = calibrate_prob("test_bet", "X over 1.5", 0.95, calibrators)
    assert 0.40 < low < 0.55
    assert 0.55 < high < 0.70


# ---------------------------------------------------------------------------
# I/O: round-trip through JSON
# ---------------------------------------------------------------------------

def test_calibrators_round_trip_json(tmp_path):
    df = _synthetic_bets("batter_hits", "X over 0.5",
                         [0.55, 0.65, 0.75], [0.50, 0.55, 0.60], n_per_bucket=300)
    calibrators = fit_calibrators(df)
    path = tmp_path / "calibration.json"
    save_calibrators(calibrators, str(path))
    loaded = load_calibrators(str(path))
    # Applying loaded calibrators produces same result as in-memory
    for raw in [0.55, 0.60, 0.70]:
        a = calibrate_prob("batter_hits", "X over 0.5", raw, calibrators)
        b = calibrate_prob("batter_hits", "X over 0.5", raw, loaded)
        assert abs(a - b) < 1e-9


def test_load_calibrators_missing_file_returns_empty(tmp_path):
    """Pipeline should not crash on first run when no calibration has been fit yet."""
    path = tmp_path / "does_not_exist.json"
    assert load_calibrators(str(path)) == {}
