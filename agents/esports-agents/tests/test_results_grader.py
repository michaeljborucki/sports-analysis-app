from agents.results_grader import grade_moneyline, grade_map_handicap, grade_total_maps


def test_grade_moneyline_win():
    assert grade_moneyline("team_a", {"winner": "team_a", "score": "2-1"}) == "W"


def test_grade_moneyline_loss():
    assert grade_moneyline("team_a", {"winner": "team_b", "score": "1-2"}) == "L"


def test_grade_map_handicap_cover():
    # Team A -1.5, wins 2-0 → covers (2 + (-1.5) = 0.5 > 0)
    assert grade_map_handicap("team_a", -1.5, {"score": "2-0", "maps_played": 2}) == "W"


def test_grade_map_handicap_no_cover():
    # Team A -1.5, wins 2-1 → doesn't cover (2 + (-1.5) = 0.5, not > 1)
    assert grade_map_handicap("team_a", -1.5, {"score": "2-1", "maps_played": 3}) == "L"


def test_grade_map_handicap_underdog():
    # Team B +1.5, loses 1-2 → covers (1 + 1.5 = 2.5 > 2)
    assert grade_map_handicap("team_b", 1.5, {"score": "2-1", "maps_played": 3}) == "W"


def test_grade_total_maps_over_win():
    assert grade_total_maps("over", 2.5, {"maps_played": 3}) == "W"


def test_grade_total_maps_over_loss():
    assert grade_total_maps("over", 2.5, {"maps_played": 2}) == "L"


def test_grade_total_maps_under_win():
    assert grade_total_maps("under", 2.5, {"maps_played": 2}) == "W"


def test_grade_total_maps_under_loss():
    assert grade_total_maps("under", 2.5, {"maps_played": 3}) == "L"


def test_grade_total_maps_push():
    # Line is 2.5 so push shouldn't happen, but test with integer line
    assert grade_total_maps("over", 3.0, {"maps_played": 3}) == "P"
