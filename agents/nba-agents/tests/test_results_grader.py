from agents.results_grader import grade_bet


class FakeRow:
    def __init__(self, d):
        self._d = d
    def __getitem__(self, key):
        return self._d[key]


SCORE = {
    "away": "BOS", "home": "NYK",
    "away_score": 98, "home_score": 112,
    "away_score_h1": 45, "home_score_h1": 58,
    "total_points": 210, "total_points_h1": 103,
}


def test_grade_moneyline_home_win():
    row = FakeRow({"bet_type": "moneyline", "side": "home"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_moneyline_away_loss():
    row = FakeRow({"bet_type": "moneyline", "side": "away"})
    assert grade_bet(row, SCORE) == "L"


def test_grade_spread_home_covers():
    # NYK won by 14, -1.5 covers
    row = FakeRow({"bet_type": "spread", "side": "home -1.5"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_spread_home_doesnt_cover():
    score = {**SCORE, "home_score": 99}  # won by 1, doesn't cover -1.5
    row = FakeRow({"bet_type": "spread", "side": "home -1.5"})
    assert grade_bet(row, score) == "L"


def test_grade_total_over_win():
    row = FakeRow({"bet_type": "total", "side": "over 209.5"})
    assert grade_bet(row, SCORE) == "W"  # 210 > 209.5


def test_grade_total_under_win():
    row = FakeRow({"bet_type": "total", "side": "under 210.5"})
    assert grade_bet(row, SCORE) == "W"  # 210 < 210.5


def test_grade_total_under_loss():
    row = FakeRow({"bet_type": "total", "side": "under 209.5"})
    assert grade_bet(row, SCORE) == "L"  # 210 > 209.5


def test_grade_h1_ml():
    row = FakeRow({"bet_type": "first_half_ml", "side": "home H1 ML"})
    assert grade_bet(row, SCORE) == "W"  # home_h1=58 > away_h1=45


def test_grade_first_half_ml_win():
    row = FakeRow({"bet_type": "first_half_ml", "side": "home H1 ML"})
    score = {"home_score": 110, "away_score": 100, "home_score_h1": 58,
             "away_score_h1": 50, "total_points": 210, "total_points_h1": 108}
    assert grade_bet(row, score) == "W"


def test_grade_q1_total_over():
    row = FakeRow({"bet_type": "q1_total", "side": "over 55.5"})
    score = {"home_score": 110, "away_score": 100, "total_points": 210,
             "home_score_q1": 30, "away_score_q1": 28,
             "home_score_h1": 58, "away_score_h1": 50, "total_points_h1": 108}
    assert grade_bet(row, score) == "W"  # 30+28=58 > 55.5


def test_grade_team_total_home_over():
    row = FakeRow({"bet_type": "team_total_home", "side": "over 108.5"})
    score = {"home_score": 110, "away_score": 100, "total_points": 210,
             "home_score_h1": 58, "away_score_h1": 50, "total_points_h1": 108}
    assert grade_bet(row, score) == "W"  # 110 > 108.5
