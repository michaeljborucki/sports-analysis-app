"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES

BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "spread": ("spread", "value_side"),
    "total": ("total", "value_side"),
    "first_half_ml": ("first_half", "h1_ml_value"),
    "first_half_spread": ("first_half", "h1_spread_value"),
    "first_half_total": ("first_half", "h1_total_value"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot. Returns None for 'none' votes."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    # Normalize spread from relative (favorite/underdog) to absolute (home/away)
    if bet_slot == "spread":
        sp_odds = odds.get("spread", {})
        home_point = sp_odds.get("home", 0)
        home_is_fav = home_point < 0
        if raw_vote == "favorite":
            return "home_sp" if home_is_fav else "away_sp"
        elif raw_vote == "underdog":
            return "away_sp" if home_is_fav else "home_sp"
        return raw_vote

    if bet_slot == "first_half_spread":
        h1_sp_odds = odds.get("h1_spread", {})
        home_point = h1_sp_odds.get("home", 0)
        home_is_fav = home_point < 0
        if raw_vote == "favorite":
            return "home_sp" if home_is_fav else "away_sp"
        elif raw_vote == "underdog":
            return "away_sp" if home_is_fav else "home_sp"
        return raw_vote

    return raw_vote


def count_votes(votes: dict[str, str | None]) -> tuple[str | None, int]:
    """Count votes and return (winning_side, count). Excludes None votes."""
    counts = {}
    for vote in votes.values():
        if vote is not None:
            counts[vote] = counts.get(vote, 0) + 1
    if not counts:
        return None, 0
    winner = max(counts, key=counts.get)
    return winner, counts[winner]


def check_consensus(votes: dict[str, str | None], min_votes: int = None) -> bool:
    """Check if enough models agree on the same side."""
    min_votes = min_votes or CONSENSUS_MIN_VOTES
    _, count = count_votes(votes)
    return count >= min_votes


def weighted_average_prob(runs: list[dict], weights: dict[str, float]) -> float:
    """Weighted average of probability estimates across runs.
    Each run dict has: {"model_key": str, "prob": float}
    """
    numerator = 0.0
    denominator = 0.0
    for run in runs:
        w = weights.get(run["model_key"], 1.0)
        numerator += w * run["prob"]
        denominator += w
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def apply_stability_bonus(weight: float, std_dev: float) -> float:
    """Apply stability multiplier based on temperature sweep std dev."""
    if std_dev < 0.03:
        return round(weight * 1.2, 4)
    elif std_dev > 0.10:
        return round(weight * 0.8, 4)
    return weight


def majority_vote(values: list[str], default: str = "medium") -> str:
    """Return the most common value. Ties broken toward default."""
    if not values:
        return default
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    winners = [v for v, c in counts.items() if c == max_count]
    if default in winners:
        return default
    return winners[0]


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
