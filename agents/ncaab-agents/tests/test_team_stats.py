from scrapers.team_stats import get_team_efficiency, _normalize_team_stats, _empty_team_stats


def test_normalize_team_stats():
    raw = {
        "team": "Duke",
        "conf": "ACC",
        "rk": 5,
        "adjoe": 118.2,
        "adjde": 89.7,
        "adj_tempo": 68.5,
        "sos": 0.85,
        "luck": 0.02,
    }
    result = _normalize_team_stats(raw)
    assert result["team"] == "Duke"
    assert result["conference"] == "ACC"
    assert result["trank"] == 5
    assert result["adj_oe"] == 118.2


def test_empty_team_stats():
    result = _empty_team_stats("Unknown Team")
    assert result["team"] == "Unknown Team"
    assert result["adj_oe"] == 0
