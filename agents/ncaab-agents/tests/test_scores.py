from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores


MOCK_ESPN_SCOREBOARD = {
    "events": [{
        "id": "401596123",
        "date": "2026-03-20T23:00:00Z",
        "competitions": [{
            "status": {"type": {"name": "STATUS_FINAL"}},
            "competitors": [
                {
                    "homeAway": "home",
                    "score": "78",
                    "team": {"abbreviation": "DUKE", "displayName": "Duke Blue Devils"},
                    "linescores": [{"value": "40"}, {"value": "38"}],
                },
                {
                    "homeAway": "away",
                    "score": "65",
                    "team": {"abbreviation": "UNC", "displayName": "North Carolina Tar Heels"},
                    "linescores": [{"value": "30"}, {"value": "35"}],
                },
            ],
        }],
    }]
}


@patch("scrapers.scores.requests.get")
def test_get_final_scores(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_SCOREBOARD
    mock_get.return_value = mock_resp

    scores = get_final_scores("2026-03-20")
    assert len(scores) == 1
    s = scores[0]
    assert s["away"] == "UNC"
    assert s["home"] == "DUKE"
    assert s["away_score"] == 65
    assert s["home_score"] == 78
    assert s["away_score_h1"] == 30
    assert s["home_score_h1"] == 40
    assert s["total_points"] == 143
    assert s["total_points_h1"] == 70


@patch("scrapers.scores.requests.get")
def test_skips_non_final_games(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "events": [{
            "id": "123",
            "competitions": [{
                "status": {"type": {"name": "STATUS_IN_PROGRESS"}},
                "competitors": [
                    {"homeAway": "home", "score": "30", "team": {"abbreviation": "DUKE"}},
                    {"homeAway": "away", "score": "25", "team": {"abbreviation": "UNC"}},
                ],
            }],
        }]
    }
    mock_get.return_value = mock_resp

    scores = get_final_scores("2026-03-20")
    assert len(scores) == 0
