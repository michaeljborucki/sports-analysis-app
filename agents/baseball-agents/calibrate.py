"""Rolling calibration.

Two layers:

1. **Isotonic regression** per (bet_type, side_bucket) when a calibration file
   exists at `data/calibration.json`. Fitted offline from historical bets
   via `fit_calibrators()`. Corrects systematic model over-confidence by
   mapping predicted probabilities to empirical win rates.

2. **Hard cap** at `SIM_PROB_CAP` as a safety backstop — applied when no
   isotonic calibrator is available for the (bet_type, side) pair.

Historical analysis (2026-04-24) across 16,468 graded bets showed predicted
vs. actual win-rate gaps of -5 to -27 percentage points across every sim_prob
bucket. The isotonic layer is how we close that gap.
"""
import json
import logging
import os

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from config import DATA_DIR
from tracker import load_bets

logger = logging.getLogger("mirofish.calibrate")

SIM_PROB_CAP = 0.75
CALIBRATION_PATH = os.path.join(DATA_DIR, "calibration.json")

# Runtime cache so we don't re-read JSON on every edge calc
_CALIBRATORS: dict | None = None


def _side_bucket(side: str) -> str:
    """Collapse a raw side string to 'over' / 'under' / 'other'.

    Over/under is the primary axis where prop-model bias differs by direction
    (e.g. batter_rbis unders are calibrated, overs are overconfident).
    For non-directional bets (moneyline, NRFI, run line) we use 'other'.
    """
    s = str(side or "").lower()
    if "over" in s:
        return "over"
    if "under" in s:
        return "under"
    return "other"


def _key(bet_type: str, side: str) -> str:
    return f"{bet_type}|{_side_bucket(side)}"


def fit_calibrators(df: pd.DataFrame, min_samples: int = 50) -> dict:
    """Fit isotonic regression per (bet_type, side_bucket) from graded bets.

    Returns dict: {key: {"x": [...], "y": [...], "n_fit": int}}.
    Keys with < min_samples graded bets are skipped.
    """
    graded = df[df["result"].isin(["W", "L"])].copy()
    if graded.empty:
        return {}
    graded["won"] = (graded["result"] == "W").astype(float)
    graded["sim_prob"] = graded["sim_prob"].astype(float)
    graded["_key"] = graded.apply(lambda r: _key(r["bet_type"], r["side"]), axis=1)

    calibrators: dict = {}
    for key in graded["_key"].unique():
        sub = graded[graded["_key"] == key]
        if len(sub) < min_samples:
            continue
        x = sub["sim_prob"].to_numpy()
        y = sub["won"].to_numpy()
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(x, y)
        # Sample a smooth grid of breakpoints for JSON storage
        grid = np.linspace(x.min(), x.max(), num=21)
        mapped = iso.predict(grid)
        calibrators[key] = {
            "x": [round(float(v), 4) for v in grid],
            "y": [round(float(v), 4) for v in mapped],
            "n_fit": int(len(sub)),
        }
    return calibrators


def calibrate_prob(bet_type: str, side: str, raw_prob: float,
                   calibrators: dict | None = None) -> float:
    """Map a raw model probability to a calibrated probability.

    Falls back to the raw value when no calibrator exists for the (bet_type,
    side) pair. Clamps inputs outside the fitted range to the nearest known
    output (extrapolation is unsafe).
    """
    if raw_prob is None:
        return raw_prob
    if calibrators is None:
        calibrators = _load_cached()
    cal = calibrators.get(_key(bet_type, side)) if calibrators else None
    if not cal:
        return float(raw_prob)
    x = cal["x"]
    y = cal["y"]
    p = float(raw_prob)
    if p <= x[0]:
        return float(y[0])
    if p >= x[-1]:
        return float(y[-1])
    # Linear interpolation between breakpoints
    for i in range(1, len(x)):
        if p <= x[i]:
            t = (p - x[i-1]) / (x[i] - x[i-1])
            return float(y[i-1] + t * (y[i] - y[i-1]))
    return float(y[-1])


def apply_calibration(prob: float, bet_type: str = "", side: str = "") -> float:
    """Apply isotonic calibration, with the old hard cap as a fallback.

    When a (bet_type, side) calibrator exists, trust it — the cap would
    destroy real edge at high-win-rate segments. When no calibrator exists
    (untrained bet type or insufficient historical samples), apply the
    legacy 0.75 cap as a safety backstop against model over-confidence.

    Note (2026-04-27): a symmetric-guard rule was briefly tried — disabling
    per-side calibration when only one of over/under was fit. It was reverted
    after the next-day data showed it added under-side bet volume rather
    than enabling over-side picks (the asymmetric shrinkage was actually
    doing useful work). The directional bias is upstream of calibration —
    in the MC simulator's run-generation engine — so the right place to
    address it is there, not here.
    """
    if prob is None:
        return prob
    calibrators = _load_cached()
    has_cal = bool(calibrators) and _key(bet_type, side) in calibrators
    calibrated = calibrate_prob(bet_type, side, float(prob), calibrators)
    if has_cal:
        return calibrated
    return min(calibrated, SIM_PROB_CAP)


def save_calibrators(calibrators: dict, path: str = CALIBRATION_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(calibrators, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_calibrators(path: str = CALIBRATION_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("calibration file %s unreadable — using empty", path)
        return {}


def _load_cached() -> dict:
    """Lazy-load calibrators once per process. Reset via reset_cache()."""
    global _CALIBRATORS
    if _CALIBRATORS is None:
        _CALIBRATORS = load_calibrators()
    return _CALIBRATORS


def reset_cache() -> None:
    """Force calibrators to reload on next use — for tests and retraining."""
    global _CALIBRATORS
    _CALIBRATORS = None


def calibration_report() -> dict:
    """Generate calibration analysis from historical bets."""
    df = load_bets()
    settled = df[df["result"].isin(["W", "L"])]

    if len(settled) < 50:
        return {"status": "insufficient_data", "n": len(settled), "needed": 50}

    report = {}
    for bet_type in settled["bet_type"].unique():
        subset = settled[settled["bet_type"] == bet_type]
        wins = len(subset[subset["result"] == "W"])
        total = len(subset)
        report[bet_type] = {
            "n": total,
            "win_rate": round(wins / total, 3) if total > 0 else 0,
            "avg_edge": round(subset["edge"].mean(), 3) if "edge" in subset else 0,
        }

    return {"status": "ok", "by_type": report, "total_settled": len(settled)}
