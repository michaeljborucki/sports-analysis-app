import copy
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS

def test_bet_slot_fields_has_thirteen_slots():
    assert len(BET_SLOT_FIELDS) == 13

def test_extract_vote_moneyline():
    vote = extract_vote(MOCK_PREDICTION, "moneyline", MOCK_ODDS)
    assert vote == "home"

def test_extract_vote_run_line_normalizes_to_absolute():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["run_line"]["value_side"] = "favorite_rl"
    vote = extract_vote(pred, "run_line", MOCK_ODDS)
    assert vote == "home_rl"  # home has -1.5

def test_extract_vote_run_line_underdog():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["run_line"]["value_side"] = "underdog_rl"
    vote = extract_vote(pred, "run_line", MOCK_ODDS)
    assert vote == "away_rl"

def test_extract_vote_none():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["moneyline"]["value_side"] = "none"
    vote = extract_vote(pred, "moneyline", MOCK_ODDS)
    assert vote is None

def test_extract_vote_first_5_ml():
    vote = extract_vote(MOCK_PREDICTION, "first_5_ml", MOCK_ODDS)
    assert vote == "home"

def test_extract_vote_first_5_total():
    vote = extract_vote(MOCK_PREDICTION, "first_5_total", MOCK_ODDS)
    assert vote == "under"

def test_count_votes_strong_consensus():
    votes = {"kimi": "home", "claude": "home", "gpt4o": "home",
             "gemini": "home", "deepseek": "away", "maverick": "home"}
    side, count = count_votes(votes)
    assert side == "home"
    assert count == 5

def test_count_votes_no_consensus():
    votes = {"kimi": "home", "claude": "away", "gpt4o": "home",
             "gemini": "away", "deepseek": None, "maverick": None}
    side, count = count_votes(votes)
    assert count == 2

def test_check_consensus_passes():
    votes = {"kimi": "home", "claude": "home", "gpt4o": "home",
             "gemini": "away", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is True

def test_check_consensus_fails():
    votes = {"kimi": "home", "claude": "away", "gpt4o": "home",
             "gemini": "away", "deepseek": None, "maverick": None}
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

def test_weighted_average_prob_with_confidences():
    """High-confidence models should pull average toward their estimate."""
    runs = [
        {"model_key": "kimi", "prob": 0.55},
        {"model_key": "gpt4o", "prob": 0.60},
        {"model_key": "gemini", "prob": 0.50},
    ]
    weights = {"kimi": 1.0, "gpt4o": 1.0, "gemini": 1.0}
    confidences = {"kimi": "high", "gpt4o": "medium", "gemini": "low"}
    avg = weighted_average_prob(runs, weights, confidences)
    # kimi: 1.0*1.3=1.3, gpt4o: 1.0*1.0=1.0, gemini: 1.0*0.7=0.7
    # num = 1.3*0.55 + 1.0*0.60 + 0.7*0.50 = 0.715+0.60+0.35 = 1.665
    # den = 1.3+1.0+0.7 = 3.0 -> avg = 0.555
    assert abs(avg - 0.555) < 0.001

def test_weighted_average_prob_no_confidences_unchanged():
    """Without confidences param, result matches old behavior."""
    runs = [
        {"model_key": "a", "prob": 0.60},
        {"model_key": "b", "prob": 0.40},
    ]
    weights = {"a": 2.0, "b": 1.0}
    avg = weighted_average_prob(runs, weights)
    # (2.0*0.60 + 1.0*0.40) / (2.0+1.0) = 1.60/3.0 = 0.5333
    assert abs(avg - 0.5333) < 0.001
