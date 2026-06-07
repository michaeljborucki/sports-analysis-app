import json
from datetime import date
from unittest.mock import patch, MagicMock
import pandas as pd
from scrapers.pitchers import get_starter_profile, get_probable_starters


MOCK_SCHEDULE_RESPONSE = {
    "dates": [
        {
            "games": [
                {
                    "gamePk": 12345,
                    "teams": {
                        "away": {
                            "team": {"name": "Boston Red Sox", "id": 111},
                            "probablePitcher": {"id": 543210, "fullName": "Brayan Bello"},
                        },
                        "home": {
                            "team": {"name": "New York Yankees", "id": 147},
                            "probablePitcher": {"id": 654321, "fullName": "Gerrit Cole"},
                        },
                    },
                    "venue": {"name": "Yankee Stadium"},
                    "gameDate": "2026-04-01T23:05:00Z",
                    "status": {"detailedState": "Scheduled"},
                }
            ]
        }
    ]
}


@patch("scrapers.pitchers.requests.get")
def test_get_probable_starters(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_SCHEDULE_RESPONSE
    mock_get.return_value = mock_resp

    games = get_probable_starters("2026-04-01")
    assert len(games) == 1
    game = games[0]
    assert game["away_pitcher"] == "Brayan Bello"
    assert game["home_pitcher"] == "Gerrit Cole"
    assert game["venue"] == "Yankee Stadium"


def test_get_starter_profile_returns_expected_shape():
    """Test that the profile dict has the right keys (using mock pybaseball data)."""
    with patch("scrapers.pitchers.pitching_stats") as mock_ps, \
         patch("scrapers.pitchers.playerid_lookup") as mock_lookup, \
         patch("scrapers.pitchers.statcast_pitcher") as mock_sc, \
         patch("scrapers.pitchers.requests.get") as mock_get:

        mock_lookup.return_value = pd.DataFrame({
            "key_mlbam": [543210],
            "name_first": ["Gerrit"],
            "name_last": ["Cole"],
        })

        mock_ps.return_value = pd.DataFrame({
            "Name": ["Gerrit Cole"],
            "IDfg": [13125],
            "W": [12], "L": [5],
            "ERA": [3.21], "FIP": [3.05], "xFIP": [3.12],
            "WHIP": [1.05], "K/9": [10.2], "BB/9": [2.1], "HR/9": [0.9],
            "IP": [142.1], "GS": [22],
        })

        mock_sc.return_value = pd.DataFrame({
            "pitch_type": ["FF", "SL", "CH"],
            "release_speed": [96.5, 88.2, 85.1],
        })

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"stats": []}
        mock_get.return_value = mock_resp

        profile = get_starter_profile("Gerrit Cole", season=2025)
        assert profile["name"] == "Gerrit Cole"
        assert "season_stats" in profile
        assert "era" in profile["season_stats"]
