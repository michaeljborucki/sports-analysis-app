"""Tests for scrapers/schedule.py."""
from unittest.mock import patch, MagicMock
from scrapers.schedule import get_todays_games


def _mock_scoreboard_response():
    mock = MagicMock()
    mock.get_dict.return_value = {
        "scoreboard": {
            "games": [
                {
                    "gameId": "0022500001",
                    "homeTeam": {"teamId": 1610612738, "teamTricode": "BOS", "teamName": "Celtics", "teamCity": "Boston"},
                    "awayTeam": {"teamId": 1610612747, "teamTricode": "LAL", "teamName": "Lakers", "teamCity": "Los Angeles"},
                    "gameStatusText": "7:30 pm ET",
                    "arenaName": "TD Garden",
                },
            ]
        }
    }
    return mock


@patch("scrapers.schedule.ScoreboardV3")
def test_get_todays_games(mock_sb):
    mock_sb.return_value = _mock_scoreboard_response()
    games = get_todays_games("2026-03-22")
    assert len(games) == 1
    assert games[0]["home_team"] == "BOS"
    assert games[0]["away_team"] == "LAL"
    assert games[0]["arena"] == "TD Garden"
    assert games[0]["game_id"] == "0022500001"


@patch("scrapers.schedule.ScoreboardV3")
def test_get_todays_games_empty(mock_sb):
    mock = MagicMock()
    mock.get_dict.return_value = {"scoreboard": {"games": []}}
    mock_sb.return_value = mock
    games = get_todays_games("2026-07-15")
    assert games == []
