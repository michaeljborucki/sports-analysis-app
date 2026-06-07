"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES

BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "game_handicap": ("game_handicap", "value_side"),
    "total_games": ("total_games", "value_side"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    if bet_slot == "game_handicap":
        gh_odds = odds.get("game_handicap", {})
        a_point = gh_odds.get("player_a_point", 0)
        a_is_fav = a_point < 0
        if raw_vote == "favorite":
            return "player_a_gh" if a_is_fav else "player_b_gh"
        elif raw_vote == "underdog":
            return "player_b_gh" if a_is_fav else "player_a_gh"
        return raw_vote

    return raw_vote


def count_votes(votes: dict[str, str | None]) -> tuple[str | None, int]:
    counts = {}
    for vote in votes.values():
        if vote is not None:
            counts[vote] = counts.get(vote, 0) + 1
    if not counts:
        return None, 0
    winner = max(counts, key=counts.get)
    return winner, counts[winner]


def check_consensus(votes: dict[str, str | None], min_votes: int = None) -> bool:
    min_votes = min_votes or CONSENSUS_MIN_VOTES
    _, count = count_votes(votes)
    return count >= min_votes


def weighted_average_prob(runs: list[dict], weights: dict[str, float]) -> float:
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
    """Apply stability multiplier. More aggressive than before."""
    if std_dev < 0.02:
        return round(weight * 1.3, 4)   # Very consistent: 30% boost
    elif std_dev < 0.05:
        return weight                     # Normal range: no change
    elif std_dev < 0.10:
        return round(weight * 0.6, 4)   # Noisy: 40% penalty
    else:
        return round(weight * 0.3, 4)   # Very noisy: 70% penalty


def majority_vote(values: list[str], default: str = "medium") -> str:
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
