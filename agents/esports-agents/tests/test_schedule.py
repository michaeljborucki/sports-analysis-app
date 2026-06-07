from unittest.mock import patch, MagicMock
from scrapers.schedule import get_todays_matches

def test_returns_list():
    result = get_todays_matches()
    assert isinstance(result, list)

def test_filters_by_tier():
    mock_matches = [
        {"team_a": "A", "team_b": "B", "tier": 1, "date": "2026-03-20"},
        {"team_a": "C", "team_b": "D", "tier": 3, "date": "2026-03-20"},
    ]

    mock_game = MagicMock()
    mock_game.scrapers.fetch_upcoming_matches.return_value = mock_matches

    with patch("scrapers.schedule.get_game", return_value=mock_game):
        result = get_todays_matches(["cs2"])

    assert len(result) == 1
    assert result[0]["team_a"] == "A"
    assert result[0]["game_key"] == "cs2"

def test_adds_game_key():
    mock_matches = [
        {"team_a": "A", "team_b": "B", "tier": 1, "date": "2026-03-20"},
    ]

    mock_game = MagicMock()
    mock_game.scrapers.fetch_upcoming_matches.return_value = mock_matches

    with patch("scrapers.schedule.get_game", return_value=mock_game):
        result = get_todays_matches(["lol"])

    assert result[0]["game_key"] == "lol"

def test_sorts_by_date():
    mock_matches = [
        {"team_a": "Late", "team_b": "B", "tier": 1, "date": "2026-03-20T20:00"},
        {"team_a": "Early", "team_b": "D", "tier": 1, "date": "2026-03-20T10:00"},
    ]

    mock_game = MagicMock()
    mock_game.scrapers.fetch_upcoming_matches.return_value = mock_matches

    with patch("scrapers.schedule.get_game", return_value=mock_game):
        result = get_todays_matches(["cs2"])

    assert result[0]["team_a"] == "Early"
    assert result[1]["team_a"] == "Late"

def test_handles_scraper_error():
    mock_game = MagicMock()
    mock_game.scrapers.fetch_upcoming_matches.side_effect = Exception("API down")

    with patch("scrapers.schedule.get_game", return_value=mock_game):
        result = get_todays_matches(["cs2"])

    assert result == []

def test_empty_game_keys():
    result = get_todays_matches([])
    assert result == []
