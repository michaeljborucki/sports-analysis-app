"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES

CONFIDENCE_MULTIPLIERS = {"high": 1.3, "medium": 1.0, "low": 0.7}

BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "run_line": ("run_line", "value_side"),
    "total": ("total", "value_side"),
    "first_5_ml": ("first_5", "f5_ml_value"),
    "first_5_total": ("first_5", "f5_total_value"),
    # Phase 1 new
    "team_total_home": ("total", "home_total_value"),
    "team_total_away": ("total", "away_total_value"),
    "first_5_rl": ("first_5", "f5_rl_value"),
    "nrfi": ("first_inning", "nrfi_value"),
    "first_1_rl": ("first_inning", "f1_rl_value"),
    "first_3_ml": ("first_3", "f3_ml_value"),
    "first_3_total": ("first_3", "f3_total_value"),
    "first_3_rl": ("first_3", "f3_rl_value"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot. Returns None for 'none' votes."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    # Normalize run_line from relative (favorite/underdog) to absolute (home/away)
    if bet_slot == "run_line":
        rl_odds = odds.get("run_line", {})
        home_point = rl_odds.get("home", -1.5)
        home_is_fav = home_point < 0
        if raw_vote == "favorite_rl":
            return "home_rl" if home_is_fav else "away_rl"
        elif raw_vote == "underdog_rl":
            return "away_rl" if home_is_fav else "home_rl"
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


def weighted_average_prob(runs: list[dict], weights: dict[str, float],
                          confidences: dict[str, str] = None) -> float:
    """Weighted average of probability estimates across runs.
    Each run dict has: {"model_key": str, "prob": float}
    Optional confidences dict maps model_key -> "high"/"medium"/"low".
    """
    numerator = 0.0
    denominator = 0.0
    for run in runs:
        w = weights.get(run["model_key"], 1.0)
        if confidences:
            conf = confidences.get(run["model_key"], "medium")
            w *= CONFIDENCE_MULTIPLIERS.get(conf, 1.0)
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
