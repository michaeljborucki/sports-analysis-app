"""Tests for scrapers/players.py — Key player profiles scraper."""
from unittest.mock import patch, MagicMock

import pytest

from scrapers.players import get_key_players, PlayerProfile


# ---------------------------------------------------------------------------
# Sample API response mimicking CricketData.org /players reply
# ---------------------------------------------------------------------------

SAMPLE_PLAYERS_RESPONSE = {
    "status": "success",
    "data": [
        {
            "id": "player-001",
            "name": "MS Dhoni",
            "role": "keeper",
            "batting_style": "Right-hand bat",
            "bowling_style": "Right-arm medium",
            "batting_avg": 38.09,
            "batting_sr": 135.92,
            "tournament_runs": 420,
            "bowling_econ": 7.5,
            "bowling_avg": 32.0,
            "tournament_wickets": 2,
            "recent_form": ["50", "32", "18", "75*", "22"],
            "venue_record": "Avg 45.2 at Chepauk",
        },
        {
            "id": "player-002",
            "name": "Ravindra Jadeja",
            "role": "all-rounder",
            "batting_style": "Left-hand bat",
            "bowling_style": "Slow left-arm orthodox",
            "batting_avg": 29.5,
            "batting_sr": 142.3,
            "tournament_runs": 210,
            "bowling_econ": 7.12,
            "bowling_avg": 22.4,
            "tournament_wickets": 8,
            "recent_form": ["22", "1W", "2W", "35", "1W"],
            "venue_record": "7 wkts at Chepauk",
        },
        {
            "id": "player-003",
            "name": "Devon Conway",
            "role": "batsman",
            "batting_style": "Left-hand bat",
            "bowling_style": "",
            "batting_avg": 44.1,
            "batting_sr": 147.8,
            "tournament_runs": 385,
            "bowling_econ": 0.0,
            "bowling_avg": 0.0,
            "tournament_wickets": 0,
            "recent_form": ["82", "14", "61", "33", "90*"],
            "venue_record": "New to venue",
        },
        {
            "id": "player-004",
            "name": "Matheesha Pathirana",
            "role": "bowler",
            "batting_style": "Right-hand bat",
            "bowling_style": "Right-arm fast",
            "batting_avg": 5.0,
            "batting_sr": 100.0,
            "tournament_runs": 12,
            "bowling_econ": 8.25,
            "bowling_avg": 18.3,
            "tournament_wickets": 14,
            "recent_form": ["2W", "3W", "1W", "0W", "2W"],
            "venue_record": "4 wkts in 2 matches",
        },
    ],
}

EMPTY_PLAYERS_RESPONSE = {"status": "success", "data": []}

SPARSE_PLAYER_RESPONSE = {
    "status": "success",
    "data": [
        {
            "id": "player-sparse-001",
            "name": "Unknown Player",
            # Minimal fields — scraper should use defaults
        }
    ],
}


# ---------------------------------------------------------------------------
# get_key_players — successful response
# ---------------------------------------------------------------------------


@patch("scrapers.players.requests.get")
def test_get_key_players_returns_list_of_player_profiles(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_PLAYERS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    players = get_key_players("CSK", "ipl")

    assert isinstance(players, list)
    assert len(players) == 4
    assert all(isinstance(p, PlayerProfile) for p in players)


@patch("scrapers.players.requests.get")
def test_get_key_players_parses_fields_correctly(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_PLAYERS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    players = get_key_players("CSK", "ipl")
    dhoni = players[0]

    assert dhoni.player_id == "player-001"
    assert dhoni.name == "MS Dhoni"
    assert dhoni.role == "keeper"
    assert dhoni.batting_style == "Right-hand bat"
    assert dhoni.bowling_style == "Right-arm medium"
    assert abs(dhoni.batting_avg - 38.09) < 1e-6
    assert abs(dhoni.batting_sr - 135.92) < 1e-6
    assert dhoni.tournament_runs == 420
    assert abs(dhoni.bowling_econ - 7.5) < 1e-6
    assert abs(dhoni.bowling_avg - 32.0) < 1e-6
    assert dhoni.tournament_wickets == 2
    assert dhoni.recent_form == ["50", "32", "18", "75*", "22"]
    assert dhoni.venue_record == "Avg 45.2 at Chepauk"


# ---------------------------------------------------------------------------
# get_key_players — limit parameter
# ---------------------------------------------------------------------------


@patch("scrapers.players.requests.get")
def test_get_key_players_respects_limit(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_PLAYERS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    players = get_key_players("CSK", "ipl", limit=2)

    assert len(players) == 2


@patch("scrapers.players.requests.get")
def test_get_key_players_default_limit_is_6(mock_get):
    """Default limit is 6; if API returns fewer, all are returned."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_PLAYERS_RESPONSE  # only 4 items
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    players = get_key_players("CSK", "ipl")

    # 4 < 6, so all 4 returned
    assert len(players) == 4


# ---------------------------------------------------------------------------
# get_key_players — empty response
# ---------------------------------------------------------------------------


@patch("scrapers.players.requests.get")
def test_get_key_players_empty_response_returns_empty_list(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_PLAYERS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    players = get_key_players("RCB", "ipl")

    assert players == []


# ---------------------------------------------------------------------------
# get_key_players — API call verification
# ---------------------------------------------------------------------------


@patch("scrapers.players.requests.get")
def test_get_key_players_calls_api_with_apikey(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_PLAYERS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    get_key_players("CSK", "ipl")

    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    params = kwargs.get("params", {})
    assert "apikey" in params


@patch("scrapers.players.requests.get")
def test_get_key_players_calls_players_endpoint(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_PLAYERS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    get_key_players("CSK", "ipl")

    call_args = mock_get.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "/players" in url


# ---------------------------------------------------------------------------
# get_key_players — sparse / missing fields handled gracefully
# ---------------------------------------------------------------------------


@patch("scrapers.players.requests.get")
def test_get_key_players_defaults_for_missing_fields(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SPARSE_PLAYER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    players = get_key_players("CSK", "ipl")

    assert len(players) == 1
    p = players[0]
    assert p.name == "Unknown Player"
    assert p.role == ""
    assert p.batting_avg == 0.0
    assert p.batting_sr == 0.0
    assert p.tournament_runs == 0
    assert p.bowling_econ == 0.0
    assert p.bowling_avg == 0.0
    assert p.tournament_wickets == 0
    assert p.recent_form == []
    assert p.venue_record == ""
