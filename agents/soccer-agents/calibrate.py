"""Rolling calibration — to be built after 2 weeks of data.

After collecting ~200 games of predictions vs actual results:
1. Bin predicted probabilities (0-10%, 10-20%, etc.)
2. Compare predicted vs actual hit rates per bin
3. Build isotonic regression calibration curve
4. Apply calibration to future predictions before edge detection

This stub exists so imports don't break.
"""
from tracker import load_bets


def calibration_report() -> dict:
    """Generate calibration analysis from historical bets."""
    df = load_bets()
    settled = df[df["result"].isin(["W", "L"])]

    if len(settled) < 50:
        return {"status": "insufficient_data", "n": len(settled), "needed": 50}

    # Group by bet type
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
