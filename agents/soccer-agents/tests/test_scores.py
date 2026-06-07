import pytest
from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores

MOCK_ESPN_SCOREBOARD = {
    "events": [
        {
            "competitions": [
                {
                    "status": {"type": {"name": "STATUS_FINAL"}},
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Inter Miami CF"}, "score": "2"},
                        {"homeAway": "away", "team": {"displayName": "LA Galaxy"}, "score": "1"},
                    ],
                }
            ]
        }
    ]
}

@patch("scrapers.scores.requests.get")
def test_get_final_scores(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_SCOREBOARD
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    scores = get_final_scores(game_date="2026-03-25", league="MLS")
    assert len(scores) == 1
    s = scores[0]
    assert s["home"] == "Inter Miami CF"
    assert s["away"] == "LA Galaxy"
    assert s["home_score"] == 2
    assert s["away_score"] == 1
    assert s["total_goals"] == 3
    assert s["both_scored"] is True

@patch("scrapers.scores.requests.get")
def test_get_final_scores_no_finals(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"events": []}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    scores = get_final_scores(game_date="2026-03-25", league="MLS")
    assert scores == []
