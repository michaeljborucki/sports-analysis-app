"""Regression tests pinning grader W/L/P logic and CLV math.

These are pure functions — no IO, no randomness — so snapshot tests work
cleanly. Covers every bet type × every outcome axis, plus every sign case
for CLV cents. If one fails, read the diff before updating.
"""
import pytest
from agents.results_grader import grade_bet
from scrapers.odds import compute_clv


# -- Reusable canonical score fixture --------------------------------------
SCORE_A_WINS_23_GAMES = {
    "player_a": "Player A", "player_b": "Player B",
    "winner": "Player A",
    "games_a": 14, "games_b": 9, "total_games": 23,
    "score": "6-3 6-2 7-5", "retired": False,
}


# ==========================================================================
#  Grader: moneyline
# ==========================================================================
def test_grader_moneyline_a_wins():
    assert grade_bet({"bet_type": "moneyline", "side": "player_a"}, SCORE_A_WINS_23_GAMES) == "W"


def test_grader_moneyline_b_loses():
    assert grade_bet({"bet_type": "moneyline", "side": "player_b"}, SCORE_A_WINS_23_GAMES) == "L"


# ==========================================================================
#  Grader: game_handicap
# ==========================================================================
def test_grader_handicap_fav_covers():
    # player_a won 14-9, covering -4.5 handicap (adjusted 9.5 > 9)
    assert grade_bet({"bet_type": "game_handicap", "side": "player_a -4.5"}, SCORE_A_WINS_23_GAMES) == "W"


def test_grader_handicap_fav_fails_to_cover():
    # -6.5: adjusted 7.5 < 9 → loss
    assert grade_bet({"bet_type": "game_handicap", "side": "player_a -6.5"}, SCORE_A_WINS_23_GAMES) == "L"


def test_grader_handicap_dog_fails_to_cover():
    # player_b +4.5: adjusted 13.5 < 14 → loss
    assert grade_bet({"bet_type": "game_handicap", "side": "player_b 4.5"}, SCORE_A_WINS_23_GAMES) == "L"


def test_grader_handicap_exact_push():
    # 10-10 with a 0-line reduces to games_a + 0 == games_b → push
    score = {**SCORE_A_WINS_23_GAMES, "games_a": 10, "games_b": 10, "total_games": 20}
    assert grade_bet({"bet_type": "game_handicap", "side": "player_a 0"}, score) == "P"


# ==========================================================================
#  Grader: total_games
# ==========================================================================
def test_grader_total_over_wins():
    assert grade_bet({"bet_type": "total_games", "side": "over 22.5"}, SCORE_A_WINS_23_GAMES) == "W"


def test_grader_total_over_loses():
    assert grade_bet({"bet_type": "total_games", "side": "over 23.5"}, SCORE_A_WINS_23_GAMES) == "L"


def test_grader_total_under_wins():
    assert grade_bet({"bet_type": "total_games", "side": "under 23.5"}, SCORE_A_WINS_23_GAMES) == "W"


def test_grader_total_exact_push():
    score = {**SCORE_A_WINS_23_GAMES, "total_games": 22}
    assert grade_bet({"bet_type": "total_games", "side": "over 22"}, score) == "P"
    assert grade_bet({"bet_type": "total_games", "side": "under 22"}, score) == "P"


# ==========================================================================
#  Grader: retirement → push
# ==========================================================================
def test_grader_retirement_returns_push_regardless_of_bet_type():
    score = {**SCORE_A_WINS_23_GAMES, "retired": True}
    for bet in [
        {"bet_type": "moneyline", "side": "player_a"},
        {"bet_type": "moneyline", "side": "player_b"},
        {"bet_type": "game_handicap", "side": "player_a -4.5"},
        {"bet_type": "total_games", "side": "over 22.5"},
    ]:
        assert grade_bet(bet, score) == "P", f"retirement should push, got non-P for {bet}"


# ==========================================================================
#  CLV: compute_clv across all sign combinations
# ==========================================================================
@pytest.mark.parametrize("bet_odds,close_odds,expected_cents,expected_pct", [
    # Same sign (both favorites): |close| shortened means fav got chalkier → +CLV for us
    (-130, -150, 20, 0.0615),
    # Same sign (both underdogs): dog lengthened means we got a better price → +CLV
    (150, 130, 20, 0.0870),
    # Cross-zero: dog→fav (we took dog, market closed fav on our side) — +CLV
    (110, -110, 20, 0.1000),
    # Cross-zero: fav→dog (we took fav, market closed dog on our side) — -CLV
    (-110, 110, -20, -0.0909),
    # Identical: zero movement
    (-110, -110, 0, 0.0),
    # Favorite shortened further
    (-200, -300, 100, 0.1250),
    # Underdog shortened (lost value)
    (150, 200, -50, -0.1667),
])
def test_clv_compute_across_sign_cases(bet_odds, close_odds, expected_cents, expected_pct):
    result = compute_clv(bet_odds, close_odds)
    assert result["clv_cents"] == expected_cents
    assert result["clv_pct"] == expected_pct
