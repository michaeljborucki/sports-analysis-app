from scrapers.scores import _parse_sets_summary, _parse_games_from_pbp


def test_parse_sets_summary_straight():
    assert _parse_sets_summary("2 - 0") == (2, 0)


def test_parse_sets_summary_three_sets():
    assert _parse_sets_summary("2 - 1") == (2, 1)


def test_parse_sets_summary_underdog():
    assert _parse_sets_summary("1 - 2") == (1, 2)


def test_parse_sets_summary_empty():
    assert _parse_sets_summary("") == (0, 0)


def test_parse_sets_summary_malformed():
    assert _parse_sets_summary("-") == (0, 0)


def _pbp_game(set_num, score):
    return {"set_number": set_num, "score": score}


def test_parse_games_three_set_win():
    pbp = [
        _pbp_game("Set 1", "0 - 1"),
        _pbp_game("Set 1", "3 - 6"),
        _pbp_game("Set 2", "1 - 0"),
        _pbp_game("Set 2", "6 - 2"),
        _pbp_game("Set 3", "1 - 0"),
        _pbp_game("Set 3", "6 - 2"),
    ]
    assert _parse_games_from_pbp(pbp) == (15, 10)


def test_parse_games_straight_sets():
    pbp = [
        _pbp_game("Set 1", "1 - 0"),
        _pbp_game("Set 1", "6 - 4"),
        _pbp_game("Set 2", "1 - 0"),
        _pbp_game("Set 2", "6 - 3"),
    ]
    assert _parse_games_from_pbp(pbp) == (12, 7)


def test_parse_games_empty():
    assert _parse_games_from_pbp([]) == (0, 0)
