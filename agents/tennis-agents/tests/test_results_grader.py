from agents.results_grader import grade_bet, _match_score


def _mock_score():
    return {
        "player_a": "Djokovic",
        "player_b": "Alcaraz",
        "score": "6-4 6-3",
        "winner": "Djokovic",
        "total_games": 19,
        "games_a": 12,
        "games_b": 7,
        "sets_a": 2,
        "sets_b": 0,
        "retired": False,
    }


def test_grade_moneyline_win():
    row = {"bet_type": "moneyline", "side": "player_a"}
    assert grade_bet(row, _mock_score()) == "W"


def test_grade_moneyline_loss():
    row = {"bet_type": "moneyline", "side": "player_b"}
    assert grade_bet(row, _mock_score()) == "L"


def test_grade_game_handicap_cover():
    row = {"bet_type": "game_handicap", "side": "player_a -4.5"}
    # Djokovic won 12 games, Alcaraz 7. 12 + (-4.5) = 7.5 > 7 → W
    assert grade_bet(row, _mock_score()) == "W"


def test_grade_game_handicap_no_cover():
    row = {"bet_type": "game_handicap", "side": "player_a -5.5"}
    # 12 + (-5.5) = 6.5 < 7 → L
    assert grade_bet(row, _mock_score()) == "L"


def test_grade_total_games_over():
    row = {"bet_type": "total_games", "side": "over 18.5"}
    # Total 19 > 18.5 → W
    assert grade_bet(row, _mock_score()) == "W"


def test_grade_total_games_under():
    row = {"bet_type": "total_games", "side": "under 20.5"}
    # Total 19 < 20.5 → W
    assert grade_bet(row, _mock_score()) == "W"


def test_grade_retirement_is_push():
    score = _mock_score()
    score["retired"] = True
    row = {"bet_type": "moneyline", "side": "player_a"}
    assert grade_bet(row, score) == "P"


def test_match_score_found():
    scores = [_mock_score()]
    assert _match_score("Djokovic vs Alcaraz", scores) is not None


def test_match_score_reversed():
    scores = [_mock_score()]
    assert _match_score("Alcaraz vs Djokovic", scores) is not None


def test_match_score_not_found():
    scores = [_mock_score()]
    assert _match_score("Sinner vs Medvedev", scores) is None
