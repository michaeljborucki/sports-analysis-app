from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores, get_postponed_games


MOCK_FINAL = {
    "dates": [{
        "games": [{
            "gamePk": 99,
            "status": {"detailedState": "Final"},
            "teams": {
                "away": {"team": {"name": "Boston Red Sox"}, "score": 3},
                "home": {"team": {"name": "New York Yankees"}, "score": 5},
            },
            "linescore": {
                "innings": [
                    {"away": {"runs": 1}, "home": {"runs": 0}},
                    {"away": {"runs": 0}, "home": {"runs": 2}},
                    {"away": {"runs": 0}, "home": {"runs": 0}},
                    {"away": {"runs": 0}, "home": {"runs": 1}},
                    {"away": {"runs": 0}, "home": {"runs": 0}},
                    {"away": {"runs": 1}, "home": {"runs": 0}},
                    {"away": {"runs": 0}, "home": {"runs": 2}},
                    {"away": {"runs": 1}, "home": {"runs": 0}},
                    {"away": {"runs": 0}, "home": {"runs": 0}},
                ],
            },
        }]
    }]
}


@patch("scrapers.scores.requests.get")
def test_get_final_scores(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_FINAL
    mock_get.return_value = mock_resp

    scores = get_final_scores("2026-04-01")
    assert len(scores) == 1
    s = scores[0]
    assert s["away"] == "BOS"
    assert s["home"] == "NYY"
    assert s["away_score"] == 3
    assert s["home_score"] == 5
    assert s["away_score_5"] == 1
    assert s["home_score_5"] == 3
    assert s["total_runs"] == 8


@patch("scrapers.scores.requests.get")
def test_skips_non_final_games(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "dates": [{"games": [{
            "gamePk": 1,
            "status": {"detailedState": "In Progress"},
            "teams": {
                "away": {"team": {"name": "Boston Red Sox"}, "score": 2},
                "home": {"team": {"name": "New York Yankees"}, "score": 1},
            },
        }]}]
    }
    mock_get.return_value = mock_resp

    scores = get_final_scores("2026-04-01")
    assert len(scores) == 0


@patch("scrapers.scores.requests.get")
def test_get_postponed_games_returns_postponed_only(mock_get):
    """Postponed/Canceled games are returned; Final games are not."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "dates": [{"games": [
            {
                "gamePk": 1, "status": {"detailedState": "Final"},
                "teams": {
                    "away": {"team": {"name": "Boston Red Sox"}},
                    "home": {"team": {"name": "New York Yankees"}},
                },
            },
            {
                "gamePk": 2, "status": {"detailedState": "Postponed"},
                "teams": {
                    "away": {"team": {"name": "Milwaukee Brewers"}},
                    "home": {"team": {"name": "Kansas City Royals"}},
                },
            },
            {
                "gamePk": 3, "status": {"detailedState": "Cancelled"},
                "teams": {
                    "away": {"team": {"name": "Chicago Cubs"}},
                    "home": {"team": {"name": "St. Louis Cardinals"}},
                },
            },
        ]}]
    }
    mock_get.return_value = mock_resp

    postponed = get_postponed_games("2026-04-03")
    assert len(postponed) == 2
    keys = {(p["away"], p["home"]) for p in postponed}
    assert ("MIL", "KC") in keys
    assert ("CHC", "STL") in keys
    assert all(p["status"] in ("Postponed", "Cancelled") for p in postponed)


@patch("scrapers.scores.requests.get")
def test_get_postponed_games_empty_when_all_final(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "dates": [{"games": [{
            "gamePk": 1, "status": {"detailedState": "Final"},
            "teams": {
                "away": {"team": {"name": "Boston Red Sox"}},
                "home": {"team": {"name": "New York Yankees"}},
            },
        }]}]
    }
    mock_get.return_value = mock_resp
    assert get_postponed_games("2026-04-01") == []
