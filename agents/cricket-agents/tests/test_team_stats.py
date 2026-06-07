"""Tests for scrapers/team_stats.py — Cricket team stats scraper."""
from unittest.mock import patch, MagicMock

import pytest

from scrapers.team_stats import get_team_profile, TeamProfile


# ---------------------------------------------------------------------------
# Sample API response mimicking CricketData.org /teams reply
# ---------------------------------------------------------------------------

SAMPLE_TEAMS_RESPONSE = {
    "status": "success",
    "data": [
        {
            "id": "team-csk-001",
            "name": "Chennai Super Kings",
            "shortname": "CSK",
            "img": "https://example.com/csk.png",
        },
        {
            "id": "team-mi-002",
            "name": "Mumbai Indians",
            "shortname": "MI",
            "img": "https://example.com/mi.png",
        },
    ],
}

# Detailed response for a single team that the implementation should parse.
# The scraper uses defaults/None for fields not present in the API.
SAMPLE_TEAM_DETAIL_RESPONSE = {
    "status": "success",
    "data": [
        {
            "id": "team-csk-001",
            "name": "Chennai Super Kings",
            "shortname": "CSK",
            "matches": 14,
            "won": 9,
            "lost": 5,
            "no_result": 0,
            "nrr": 0.425,
            "standing": 2,
            "last_5": ["W", "W", "L", "W", "W"],
            "bat_first_wins": 5,
            "chase_wins": 4,
            "avg_score_bat_first": 182.3,
            "avg_score_chasing": 174.1,
            "powerplay_run_rate": 8.6,
            "death_overs_economy": 10.2,
        }
    ],
}

EMPTY_TEAMS_RESPONSE = {"status": "success", "data": []}


# ---------------------------------------------------------------------------
# get_team_profile — found
# ---------------------------------------------------------------------------


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_returns_team_profile(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_TEAM_DETAIL_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    profile = get_team_profile("CSK", "ipl")

    assert isinstance(profile, TeamProfile)
    assert profile.team == "CSK"
    assert profile.league == "ipl"
    assert profile.matches == 14
    assert profile.won == 9
    assert profile.lost == 5
    assert profile.no_result == 0
    assert abs(profile.win_rate - 9 / 14) < 1e-6
    assert profile.nrr == 0.425
    assert profile.standing == 2
    assert profile.last_5 == ["W", "W", "L", "W", "W"]
    assert profile.bat_first_wins == 5
    assert profile.chase_wins == 4
    assert abs(profile.avg_score_bat_first - 182.3) < 1e-6
    assert abs(profile.avg_score_chasing - 174.1) < 1e-6
    assert abs(profile.powerplay_run_rate - 8.6) < 1e-6
    assert abs(profile.death_overs_economy - 10.2) < 1e-6


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_win_rate_computed(mock_get):
    """win_rate must be computed as won / matches."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_TEAM_DETAIL_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    profile = get_team_profile("CSK", "ipl")
    expected = 9 / 14
    assert abs(profile.win_rate - expected) < 1e-6


# ---------------------------------------------------------------------------
# get_team_profile — not found
# ---------------------------------------------------------------------------


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_not_found_returns_none(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_TEAMS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = get_team_profile("XYZ", "ipl")
    assert result is None


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_wrong_shortname_returns_none(mock_get):
    """Returns None when only unrelated teams are in the response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_TEAMS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = get_team_profile("RCB", "ipl")
    assert result is None


# ---------------------------------------------------------------------------
# API call verification
# ---------------------------------------------------------------------------


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_calls_api_with_key(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_TEAMS_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    get_team_profile("CSK", "ipl")

    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    params = kwargs.get("params", {})
    assert "apikey" in params


# ---------------------------------------------------------------------------
# Defaults for missing optional fields
# ---------------------------------------------------------------------------


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_defaults_for_missing_fields(mock_get):
    """TeamProfile should handle missing optional fields gracefully."""
    sparse_response = {
        "status": "success",
        "data": [
            {
                "name": "Chennai Super Kings",
                "shortname": "CSK",
                # Only the bare minimum — no stats fields
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = sparse_response
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    profile = get_team_profile("CSK", "ipl")
    assert profile is not None
    assert profile.team == "CSK"
    assert profile.matches == 0
    assert profile.won == 0
    assert profile.lost == 0
    assert profile.win_rate == 0.0
    assert profile.last_5 == []
