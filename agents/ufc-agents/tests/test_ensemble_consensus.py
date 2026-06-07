import copy
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS

def test_bet_slot_fields_has_three_slots():
    assert len(BET_SLOT_FIELDS) == 3

def test_extract_vote_moneyline():
    vote = extract_vote(MOCK_PREDICTION, "moneyline", MOCK_ODDS)
    assert vote == "fighter_a"

def test_extract_vote_total_rounds():
    vote = extract_vote(MOCK_PREDICTION, "total_rounds", MOCK_ODDS)
    assert vote == "over"

def test_extract_vote_method():
    vote = extract_vote(MOCK_PREDICTION, "method", MOCK_ODDS)
    assert vote == "dec"

def test_extract_vote_none():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["moneyline"]["value_side"] = "none"
    vote = extract_vote(pred, "moneyline", MOCK_ODDS)
    assert vote is None

def test_count_votes_strong_consensus():
    votes = {"kimi": "fighter_a", "claude": "fighter_a", "gpt4o": "fighter_a",
             "gemini": "fighter_a", "deepseek": "fighter_b", "maverick": "fighter_a"}
    side, count = count_votes(votes)
    assert side == "fighter_a"
    assert count == 5

def test_count_votes_no_consensus():
    votes = {"kimi": "fighter_a", "claude": "fighter_b", "gpt4o": "fighter_a",
             "gemini": "fighter_b", "deepseek": None, "maverick": None}
    side, count = count_votes(votes)
    assert count == 2

def test_check_consensus_passes():
    votes = {"kimi": "fighter_a", "claude": "fighter_a", "gpt4o": "fighter_a",
             "gemini": "fighter_b", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is True

def test_check_consensus_fails():
    votes = {"kimi": "fighter_a", "claude": "fighter_b", "gpt4o": "fighter_a",
             "gemini": "fighter_b", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is False

def test_weighted_average_prob():
    runs = [
        {"model_key": "kimi", "prob": 0.55},
        {"model_key": "gpt4o", "prob": 0.60},
        {"model_key": "gemini", "prob": 0.50},
    ]
    weights = {"kimi": 1.0, "gpt4o": 2.0, "gemini": 1.0}
    avg = weighted_average_prob(runs, weights)
    assert abs(avg - 0.5625) < 0.001

def test_apply_stability_bonus_tight():
    # std_dev=0.02 → multiplier=1.2-0.06=1.14
    assert apply_stability_bonus(1.0, 0.02) == 1.14

def test_apply_stability_bonus_noisy():
    # std_dev=0.15 → multiplier=1.2-0.45=0.75
    assert apply_stability_bonus(1.0, 0.15) == 0.75

def test_apply_stability_bonus_normal():
    # std_dev=0.05 → multiplier=1.2-0.15=1.05
    assert apply_stability_bonus(1.0, 0.05) == 1.05

def test_majority_vote_clear_winner():
    assert majority_vote(["high", "high", "medium"]) == "high"

def test_majority_vote_tie_breaks_to_default():
    assert majority_vote(["high", "low", "medium"], default="medium") == "medium"

def test_majority_vote_empty():
    assert majority_vote([], default="medium") == "medium"


def test_count_votes_weighted():
    from ensemble.consensus import count_votes_weighted
    votes = {"kimi": "fighter_a", "claude": "fighter_a", "gpt4o": "fighter_b"}
    weights = {
        "kimi": {"moneyline": 1.0},
        "claude": {"moneyline": 1.5},  # Claude gets higher weight
        "gpt4o": {"moneyline": 1.2},
    }
    winner, count = count_votes_weighted(votes, weights)
    assert winner == "fighter_a"  # kimi(1.0) + claude(1.5) = 2.5 > gpt4o(1.2)
    assert count > 2.0


def test_stability_bonus_smooth():
    from ensemble.consensus import apply_stability_bonus
    # Should be continuous, not stepped
    w1 = apply_stability_bonus(1.0, 0.01)  # Very stable
    w2 = apply_stability_bonus(1.0, 0.05)  # Somewhat stable
    w3 = apply_stability_bonus(1.0, 0.10)  # Moderate
    w4 = apply_stability_bonus(1.0, 0.18)  # Unstable
    assert w1 > w2 > w3 > w4  # Monotonically decreasing
    assert w1 <= 1.2
    assert w4 >= 0.6
