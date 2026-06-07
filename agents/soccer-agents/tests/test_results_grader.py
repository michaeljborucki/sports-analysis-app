import pytest
from agents.results_grader import grade_bet

SCORE = {
    "home": "Inter Miami CF", "away": "LA Galaxy",
    "home_score": 2, "away_score": 1,
    "total_goals": 3, "both_scored": True,
}

def test_grade_asian_handicap_home_covers():
    bet = {"bet_type": "asian_handicap", "side": "home -0.5"}
    assert grade_bet(bet, SCORE) == "W"

def test_grade_asian_handicap_away_covers():
    bet = {"bet_type": "asian_handicap", "side": "away 0.5"}
    score = {"home_score": 1, "away_score": 1, "total_goals": 2, "both_scored": True}
    assert grade_bet(bet, score) == "W"

def test_grade_asian_handicap_push():
    bet = {"bet_type": "asian_handicap", "side": "home -1.0"}
    assert grade_bet(bet, SCORE) == "P"

def test_grade_total_over():
    bet = {"bet_type": "total", "side": "over 2.5"}
    assert grade_bet(bet, SCORE) == "W"

def test_grade_total_under():
    bet = {"bet_type": "total", "side": "under 2.5"}
    assert grade_bet(bet, SCORE) == "L"

def test_grade_btts_yes():
    bet = {"bet_type": "btts", "side": "yes"}
    assert grade_bet(bet, SCORE) == "W"

def test_grade_btts_no():
    bet = {"bet_type": "btts", "side": "no"}
    assert grade_bet(bet, SCORE) == "L"

def test_grade_btts_no_wins():
    bet = {"bet_type": "btts", "side": "no"}
    score = {"home_score": 1, "away_score": 0, "total_goals": 1, "both_scored": False}
    assert grade_bet(bet, score) == "W"

def test_no_mlb_grading():
    bet = {"bet_type": "run_line", "side": "home -1.5"}
    assert grade_bet(bet, SCORE) == "L"
    bet = {"bet_type": "first_5", "side": "home F5 ML"}
    assert grade_bet(bet, SCORE) == "L"
