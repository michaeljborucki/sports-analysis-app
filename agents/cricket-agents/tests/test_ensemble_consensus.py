import copy
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS

def test_bet_slot_fields_has_two_slots():
    assert len(BET_SLOT_FIELDS) == 2

def test_extract_vote_moneyline():
    vote = extract_vote(MOCK_PREDICTION, "moneyline", MOCK_ODDS)
    assert vote == "team_a"

def test_extract_vote_total_runs():
    vote = extract_vote(MOCK_PREDICTION, "total_runs", MOCK_ODDS)
    assert vote == "over"

def test_extract_vote_none():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["moneyline"]["value_side"] = "none"
    vote = extract_vote(pred, "moneyline", MOCK_ODDS)
    assert vote is None

def test_count_votes_strong_consensus():
    votes = {"kimi": "team_a", "claude": "team_a", "gpt4o": "team_a",
             "gemini": "team_a", "deepseek": "team_b", "maverick": "team_a"}
    side, count = count_votes(votes)
    assert side == "team_a"
    assert count == 5

def test_count_votes_no_consensus():
    votes = {"kimi": "team_a", "claude": "team_b", "gpt4o": "team_a",
             "gemini": "team_b", "deepseek": None, "maverick": None}
    side, count = count_votes(votes)
    assert count == 2

def test_check_consensus_passes():
    votes = {"kimi": "team_a", "claude": "team_a", "gpt4o": "team_a",
             "gemini": "team_b", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is True

def test_check_consensus_fails():
    votes = {"kimi": "team_a", "claude": "team_b", "gpt4o": "team_a",
             "gemini": "team_b", "deepseek": None, "maverick": None}
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
    assert apply_stability_bonus(1.0, 0.02) == 1.2

def test_apply_stability_bonus_noisy():
    assert apply_stability_bonus(1.0, 0.15) == 0.8

def test_apply_stability_bonus_normal():
    assert apply_stability_bonus(1.0, 0.05) == 1.0

def test_majority_vote_clear_winner():
    assert majority_vote(["high", "high", "medium"]) == "high"

def test_majority_vote_tie_breaks_to_default():
    assert majority_vote(["high", "low", "medium"], default="medium") == "medium"

def test_majority_vote_empty():
    assert majority_vote([], default="medium") == "medium"
