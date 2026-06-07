"""Tests for scrapers/scores.py."""
from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores


@patch("scrapers.scores.ScoreboardV2")
def test_get_final_scores_returns_list(mock_sb):
    mock_sb.return_value.get_dict.return_value = {"resultSets": []}
    scores = get_final_scores("2026-03-22")
    assert isinstance(scores, list)


def test_score_dict_schema():
    score = {
        "away": "LAL", "home": "BOS",
        "away_score": 105, "home_score": 112,
        "away_score_h1": 52, "home_score_h1": 58,
        "total_points": 217, "total_points_h1": 110,
        "status": "Final",
    }
    assert "away_score_5" not in score
    assert "total_runs" not in score
    assert "away_score_h1" in score
    assert "total_points" in score


@patch("scrapers.scores.ScoreboardV2")
def test_half_score_aggregation(mock_sb):
    mock_sb.return_value.get_dict.return_value = {
        "resultSets": [
            {
                "name": "GameHeader",
                "headers": ["GAME_ID", "GAME_STATUS_TEXT", "HOME_TEAM_ID", "VISITOR_TEAM_ID"],
                "rowSet": [["0022500001", "Final", 100, 200]],
            },
            {
                "name": "LineScore",
                "headers": ["GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "PTS",
                            "PTS_QTR1", "PTS_QTR2", "PTS_QTR3", "PTS_QTR4"],
                "rowSet": [
                    ["0022500001", 100, "BOS", 112, 30, 28, 26, 28],
                    ["0022500001", 200, "LAL", 105, 25, 27, 24, 29],
                ],
            },
        ]
    }
    scores = get_final_scores("2026-03-22")
    assert len(scores) == 1
    s = scores[0]
    assert s["home"] == "BOS"
    assert s["away"] == "LAL"
    assert s["home_score"] == 112
    assert s["away_score"] == 105
    assert s["home_score_h1"] == 58
    assert s["away_score_h1"] == 52
    assert s["total_points"] == 217
    assert s["total_points_h1"] == 110
