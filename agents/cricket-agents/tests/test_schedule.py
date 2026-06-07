"""Tests for scrapers/schedule.py — CricketData.org match schedule scraper."""
from unittest.mock import patch, MagicMock

import pytest

from scrapers.schedule import get_upcoming_matches, MatchInfo, _resolve_team, _detect_league


# ---------------------------------------------------------------------------
# Sample API response that mimics a CricketData.org /matches reply
# ---------------------------------------------------------------------------

SAMPLE_MATCHES_RESPONSE = {
    "status": "success",
    "data": [
        {
            "id": "match-001",
            "name": "Chennai Super Kings vs Mumbai Indians",
            "matchType": "t20",
            "status": "upcoming",
            "venue": "M. A. Chidambaram Stadium",
            "date": "2026-03-25",
            "dateTimeGMT": "2026-03-25T14:00:00",
            "teams": ["Chennai Super Kings", "Mumbai Indians"],
            "teamInfo": [
                {"name": "Chennai Super Kings", "shortname": "CSK"},
                {"name": "Mumbai Indians", "shortname": "MI"},
            ],
        },
        {
            "id": "match-002",
            "name": "Trinbago Knight Riders vs Guyana Amazon Warriors",
            "matchType": "t20",
            "status": "upcoming",
            "venue": "Queen's Park Oval",
            "date": "2026-08-10",
            "dateTimeGMT": "2026-08-10T20:00:00",
            "teams": ["Trinbago Knight Riders", "Guyana Amazon Warriors"],
            "teamInfo": [
                {"name": "Trinbago Knight Riders", "shortname": "TKR"},
                {"name": "Guyana Amazon Warriors", "shortname": "GAW"},
            ],
        },
        {
            # Non-T20 match — should be filtered out
            "id": "match-003",
            "name": "England vs Australia",
            "matchType": "test",
            "status": "upcoming",
            "venue": "Lord's",
            "date": "2026-06-01",
            "dateTimeGMT": "2026-06-01T10:00:00",
            "teams": ["England", "Australia"],
            "teamInfo": [],
        },
    ],
}

EMPTY_RESPONSE = {"status": "success", "data": []}


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_resolve_team_known():
    abbrev = _resolve_team("Chennai Super Kings")
    assert abbrev == "CSK"


def test_resolve_team_unknown():
    abbrev = _resolve_team("Unknown Team FC")
    assert abbrev == "Unknown Team FC"


def test_detect_league_ipl():
    league = _detect_league("Chennai Super Kings", "Mumbai Indians")
    assert league == "ipl"


def test_detect_league_cpl():
    league = _detect_league("Trinbago Knight Riders", "Guyana Amazon Warriors")
    assert league == "cpl"


def test_detect_league_unknown():
    league = _detect_league("England", "Australia")
    assert league is None


# ---------------------------------------------------------------------------
# get_upcoming_matches tests
# ---------------------------------------------------------------------------


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_returns_matchinfo(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_MATCHES_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches()

    # Only t20 matches should be returned
    assert len(matches) == 2
    first = matches[0]
    assert isinstance(first, MatchInfo)
    assert first.match_id == "match-001"
    assert first.team_a == "CSK"
    assert first.team_b == "MI"
    assert first.team_a_full == "Chennai Super Kings"
    assert first.team_b_full == "Mumbai Indians"
    assert first.league == "ipl"
    assert first.venue == "M. A. Chidambaram Stadium"
    assert first.date == "2026-03-25"
    assert first.datetime_gmt == "2026-03-25T14:00:00"
    assert first.status == "upcoming"


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_abbreviations(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_MATCHES_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches()
    cpl_match = matches[1]
    assert cpl_match.team_a == "TKR"
    assert cpl_match.team_b == "GAW"
    assert cpl_match.league == "cpl"


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches()
    assert matches == []


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_filter_by_league(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_MATCHES_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches(league="ipl")
    assert len(matches) == 1
    assert matches[0].league == "ipl"


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_filters_non_t20(mock_get):
    """Non-T20 matches (e.g., test cricket) must be excluded."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_MATCHES_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    matches = get_upcoming_matches()
    match_types = [m.match_id for m in matches]
    assert "match-003" not in match_types


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_matches_calls_api_with_key(mock_get):
    """Ensure the API key is passed as a query parameter."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = EMPTY_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    get_upcoming_matches()

    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    params = kwargs.get("params", {})
    assert "apikey" in params
