"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES


def extract_vote(prediction: dict, bet_slot: str, odds: dict,
                 bet_slot_fields: dict = None) -> str | None:
    """Extract a model's normalized vote for a bet slot. Returns None for 'none' votes.

    Args:
        bet_slot_fields: Mapping of slot -> (section_key, value_field) or
                         slot -> (prob_field, side_a, side_b).
                         The first two elements are used: (section_key, field_name).
    """
    if bet_slot_fields is None:
        raise ValueError("bet_slot_fields is required — pass game_config.BET_SLOT_FIELDS")
    section_key, field_name = bet_slot_fields[bet_slot][:2]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    # Normalize map_handicap from relative (favorite/underdog) to absolute (team_a/team_b)
    if bet_slot == "map_handicap":
        hc_odds = odds.get("map_handicap", {})
        team_a_line = hc_odds.get("team_a_line", -1.5)
        team_a_is_fav = team_a_line < 0
        if raw_vote == "favorite_rl":
            return "team_a" if team_a_is_fav else "team_b"
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
