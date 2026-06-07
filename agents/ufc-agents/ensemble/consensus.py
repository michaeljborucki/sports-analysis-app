"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES

BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "total_rounds": ("total_rounds", "value_side"),
    "method": ("method", "value_method"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot. Returns None for 'none' votes."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

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


def count_votes_weighted(votes: dict, weights: dict) -> tuple[str | None, float]:
    """Count votes using model quality weights. Returns (winning_side, weighted_count).

    Args:
        votes: {model_key: vote_string}
        weights: {model_key: {slot: weight, ...}} from model weights file
    """
    weighted_counts = {}
    for model_key, vote in votes.items():
        if vote is None:
            continue
        # Average weight across all slots for this model
        model_weights = weights.get(model_key, {})
        avg_weight = sum(model_weights.values()) / max(len(model_weights), 1) if model_weights else 1.0
        weighted_counts[vote] = weighted_counts.get(vote, 0) + avg_weight

    if not weighted_counts:
        return None, 0
    winner = max(weighted_counts, key=weighted_counts.get)
    return winner, weighted_counts[winner]


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
    """Apply stability multiplier based on temperature sweep std dev.

    Uses smooth continuous function instead of hard thresholds.
    Very stable predictions (low std_dev) -> bonus up to 20%
    Highly variable predictions (high std_dev) -> penalty up to 40%
    """
    # Continuous multiplier: 1.2 at std_dev=0, decaying to 0.6 at std_dev=0.20
    # Formula: 1.2 - 3.0 * std_dev (clamped to [0.6, 1.2])
    multiplier = 1.2 - 3.0 * std_dev
    multiplier = max(0.60, min(1.20, multiplier))
    return round(weight * multiplier, 4)


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
