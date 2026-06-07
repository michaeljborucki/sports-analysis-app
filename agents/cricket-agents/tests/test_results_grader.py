from agents.results_grader import grade_bet


class FakeRow:
    def __init__(self, d):
        self._d = d
    def __getitem__(self, key):
        return self._d[key]


SCORE = {
    "team_a": "MI", "team_b": "CSK",
    "team_a_score": 185, "team_b_score": 162,
    "total_runs": 347,
    "dls_applied": False,
    "winner": "MI",
}

SCORE_DLS = {
    "team_a": "RCB", "team_b": "KKR",
    "team_a_score": 120, "team_b_score": 98,
    "total_runs": 218,
    "dls_applied": True,
    "winner": "RCB",
}


def test_grade_moneyline_team_a_win():
    row = FakeRow({"bet_type": "moneyline", "side": "team_a"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_moneyline_team_b_loss():
    row = FakeRow({"bet_type": "moneyline", "side": "team_b"})
    assert grade_bet(row, SCORE) == "L"


def test_grade_moneyline_team_b_win():
    score = {**SCORE, "team_a_score": 150, "team_b_score": 165, "winner": "CSK"}
    row = FakeRow({"bet_type": "moneyline", "side": "team_b"})
    assert grade_bet(row, score) == "W"


def test_grade_total_runs_over_win():
    row = FakeRow({"bet_type": "total_runs", "side": "over 320.5"})
    assert grade_bet(row, SCORE) == "W"  # 347 > 320.5


def test_grade_total_runs_under_win():
    row = FakeRow({"bet_type": "total_runs", "side": "under 360.5"})
    assert grade_bet(row, SCORE) == "W"  # 347 < 360.5


def test_grade_total_runs_under_loss():
    row = FakeRow({"bet_type": "total_runs", "side": "under 320.5"})
    assert grade_bet(row, SCORE) == "L"  # 347 > 320.5


def test_grade_total_runs_dls_void():
    """Total runs bets should be voided (push) when DLS is applied."""
    row = FakeRow({"bet_type": "total_runs", "side": "over 200.5"})
    assert grade_bet(row, SCORE_DLS) == "P"


def test_grade_unknown_bet_type_returns_loss():
    row = FakeRow({"bet_type": "unknown_type", "side": "something"})
    assert grade_bet(row, SCORE) == "L"
