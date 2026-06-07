import copy
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS

def test_bet_slot_fields_has_five_slots():
    assert len(BET_SLOT_FIELDS) == 11


def test_bet_slot_fields_has_new_slots():
    new_slots = ["first_half_spread", "q1_ml", "q1_spread", "q1_total",
                 "team_total_home", "team_total_away"]
    for slot in new_slots:
        assert slot in BET_SLOT_FIELDS


def test_extract_vote_q1_ml():
    prediction = {"predictions": {"q1": {"q1_ml_value": "home"}}}
    vote = extract_vote(prediction, "q1_ml", {})
    assert vote == "home"


def test_extract_vote_team_total():
    prediction = {"predictions": {"team_totals": {"home_value": "over"}}}
    vote = extract_vote(prediction, "team_total_home", {})
    assert vote == "over"

def test_extract_vote_moneyline():
    vote = extract_vote(MOCK_PREDICTION, "moneyline", MOCK_ODDS)
    assert vote == "home"

def test_extract_vote_spread_normalizes_to_absolute():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["spread"]["value_side"] = "favorite"
    vote = extract_vote(pred, "spread", MOCK_ODDS)
    assert vote == "home_spread"  # home has -4.5

def test_extract_vote_spread_underdog():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["spread"]["value_side"] = "underdog"
    vote = extract_vote(pred, "spread", MOCK_ODDS)
    assert vote == "away_spread"

def test_extract_vote_none():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["moneyline"]["value_side"] = "none"
    vote = extract_vote(pred, "moneyline", MOCK_ODDS)
    assert vote is None

def test_extract_vote_first_half_ml():
    vote = extract_vote(MOCK_PREDICTION, "first_half_ml", MOCK_ODDS)
    assert vote == "home"

def test_extract_vote_first_half_total():
    vote = extract_vote(MOCK_PREDICTION, "first_half_total", MOCK_ODDS)
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
