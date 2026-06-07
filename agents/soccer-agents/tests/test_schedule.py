import pytest
from unittest.mock import patch, MagicMock
from scrapers.schedule import get_fixtures

MOCK_ESPN_RESPONSE = {
    "events": [
        {
            "id": "12345",
            "date": "2026-03-25T23:30Z",
            "name": "Inter Miami CF vs LA Galaxy",
            "competitions": [
                {
                    "venue": {"fullName": "Chase Stadium"},
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Inter Miami CF", "abbreviation": "MIA"}},
                        {"homeAway": "away", "team": {"displayName": "LA Galaxy", "abbreviation": "LA"}},
                    ],
                }
            ],
        }
    ],
}

@patch("scrapers.schedule.requests.get")
def test_get_fixtures_returns_matches(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fixtures = get_fixtures(league="MLS", game_date="2026-03-25")
    assert len(fixtures) == 1
    f = fixtures[0]
    assert f["home_team"] == "Inter Miami CF"
    assert f["away_team"] == "LA Galaxy"
    assert f["venue"] == "Chase Stadium"
    assert f["league"] == "MLS"

@patch("scrapers.schedule.requests.get")
def test_get_fixtures_no_events(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"events": []}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    fixtures = get_fixtures(league="MLS", game_date="2026-03-25")
    assert fixtures == []
