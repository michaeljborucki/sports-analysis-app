import pytest
from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_team_profile

# Mock the standings API response structure
MOCK_STANDINGS = {
    "children": [
        {
            "standings": {
                "entries": [
                    {
                        "team": {"displayName": "Inter Miami CF"},
                        "stats": [
                            {"name": "wins", "value": 8},
                            {"name": "losses", "value": 4},
                            {"name": "ties", "value": 3},
                            {"name": "points", "value": 27},
                            {"name": "pointsFor", "value": 24},
                            {"name": "pointsAgainst", "value": 15},
                            {"name": "gamesPlayed", "value": 15},
                            {"name": "rank", "value": 1},
                        ],
                    }
                ]
            }
        }
    ]
}


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_basic(mock_get):
    # Clear the standings cache so the mock is used
    from scrapers import team_stats
    team_stats._standings_cache.clear()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_STANDINGS
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    profile = get_team_profile("Inter Miami CF", league="MLS")
    assert profile["team"] == "Inter Miami CF"
    assert profile["record"] == "8W-3D-4L"
    assert profile["points"] == 27
    assert profile["goals_for"] == 24
    assert profile["goals_against"] == 15
    assert profile["goal_diff"] == 9
    assert profile["standing"] == "1st in MLS"


def test_get_team_profile_signature():
    import inspect
    sig = inspect.signature(get_team_profile)
    params = list(sig.parameters.keys())
    assert "team_name" in params
    assert "league" in params
