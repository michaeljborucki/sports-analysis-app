from agents.results_grader import grade_bet


class FakeRow:
    def __init__(self, d):
        self._d = d
    def __getitem__(self, key):
        return self._d[key]


SCORE = {
    "away": "UNC", "home": "DUKE",
    "away_score": 65, "home_score": 78,
    "away_score_h1": 30, "home_score_h1": 40,
    "total_points": 143, "total_points_h1": 70,
}


def test_grade_moneyline_home_win():
    row = FakeRow({"bet_type": "moneyline", "side": "home"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_moneyline_away_loss():
    row = FakeRow({"bet_type": "moneyline", "side": "away"})
    assert grade_bet(row, SCORE) == "L"


def test_grade_spread_home_covers():
    # DUKE won by 13, -6.5 covers
    row = FakeRow({"bet_type": "spread", "side": "home -6.5"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_spread_home_doesnt_cover():
    score = {**SCORE, "home_score": 68, "total_points": 133}  # won by 3, doesn't cover -6.5
    row = FakeRow({"bet_type": "spread", "side": "home -6.5"})
    assert grade_bet(row, score) == "L"


def test_grade_total_over_win():
    row = FakeRow({"bet_type": "total", "side": "over 140.5"})
    assert grade_bet(row, SCORE) == "W"  # 143 > 140.5


def test_grade_total_under_win():
    row = FakeRow({"bet_type": "total", "side": "under 145.5"})
    assert grade_bet(row, SCORE) == "W"  # 143 < 145.5


def test_grade_total_under_loss():
    row = FakeRow({"bet_type": "total", "side": "under 140.5"})
    assert grade_bet(row, SCORE) == "L"  # 143 > 140.5


def test_grade_h1_ml():
    row = FakeRow({"bet_type": "first_half_ml", "side": "home H1 ML"})
    assert grade_bet(row, SCORE) == "W"  # home_h1=40 > away_h1=30
