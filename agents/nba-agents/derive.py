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
