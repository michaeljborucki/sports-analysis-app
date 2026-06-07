from agents.results_grader import grade_bet


def test_grade_moneyline_win():
    bet = {"bet_type": "moneyline", "side": "fighter_a"}
    result = {"winner": "fighter_a"}
    assert grade_bet(bet, result) == "W"


def test_grade_moneyline_loss():
    bet = {"bet_type": "moneyline", "side": "fighter_a"}
    result = {"winner": "fighter_b"}
    assert grade_bet(bet, result) == "L"


def test_grade_total_rounds_over_win():
    bet = {"bet_type": "total_rounds", "side": "over 2.5"}
    result = {"winner": "fighter_a", "method": "Decision", "round": 3}
    assert grade_bet(bet, result) == "W"


def test_grade_total_rounds_under_win():
    bet = {"bet_type": "total_rounds", "side": "under 2.5"}
    result = {"winner": "fighter_a", "method": "KO/TKO", "round": 1}
    assert grade_bet(bet, result) == "W"


def test_grade_method_ko_win():
    bet = {"bet_type": "method", "side": "ko_tko"}
    result = {"winner": "fighter_a", "method": "KO/TKO", "round": 2}
    assert grade_bet(bet, result) == "W"


def test_grade_method_ko_loss():
    bet = {"bet_type": "method", "side": "ko_tko"}
    result = {"winner": "fighter_a", "method": "Decision", "round": 3}
    assert grade_bet(bet, result) == "L"


def test_grade_method_submission_win():
    bet = {"bet_type": "method", "side": "submission"}
    result = {"winner": "fighter_a", "method": "Submission", "round": 2}
    assert grade_bet(bet, result) == "W"


def test_grade_method_decision_win():
    bet = {"bet_type": "method", "side": "decision"}
    result = {"winner": "fighter_b", "method": "Unanimous Decision", "round": 3}
    assert grade_bet(bet, result) == "W"
