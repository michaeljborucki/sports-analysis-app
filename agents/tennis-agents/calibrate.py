"""Probability calibration for tennis predictions.

Two concerns live here:

1. ``apply_calibration(prob, bet_type)`` — called from ``edge.py`` on every
   sim probability before edge detection and Kelly sizing. Current policy is
   a symmetric hard cap at ``SIM_PROB_CAP`` (dampens overconfidence at the
   tails); the ``bet_type`` argument is accepted now so the signature is
   stable when we swap in isotonic regression later.

2. ``calibration_report()`` — offline analysis of bets.csv used to decide
   when the hard cap can be replaced with a proper per-bet-type calibration
   curve. See ``INVESTIGATE_LATER.md`` item 2 for the revisit trigger.
"""
from tracker import load_bets


SIM_PROB_CAP = 0.85


def apply_calibration(prob, bet_type: str = None) -> float:
    """Symmetric hard-cap calibration: clamp ``prob`` into ``[1-CAP, CAP]``.

    The cap is a conservative starting point for an un-measured model. It
    kills the "both model and market say 0.90 favorite" corner where a small
    overconfidence error × big Kelly = big regret, while leaving the middle
    range (where tennis edges actually live) untouched.

    Replace with per-``bet_type`` isotonic regression once we have ~2 weeks
    of CLV data per bet type.
    """
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return prob
    floor = round(1.0 - SIM_PROB_CAP, 6)
    if p > SIM_PROB_CAP:
        return SIM_PROB_CAP
    if p < floor:
        return floor
    return p


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
