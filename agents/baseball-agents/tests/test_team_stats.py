from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_team_profile, pythagorean_win_pct


def test_pythagorean_win_pct():
    # Team scoring 5 runs/game allowing 4 should be above .500
    pct = pythagorean_win_pct(5.0, 4.0)
    assert 0.55 < pct < 0.65


def test_pythagorean_equal_runs():
    pct = pythagorean_win_pct(4.5, 4.5)
    assert abs(pct - 0.5) < 0.001


@patch("scrapers.team_stats.requests.get")
def test_get_team_profile_shape(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "teams": [
            {
                "name": "New York Yankees",
                "abbreviation": "NYY",
                "division": {"name": "American League East"},
                "record": {
                    "wins": 45, "losses": 30,
                    "winningPercentage": ".600",
                    "records": {
                        "splitRecords": [
                            {"type": "home", "wins": 25, "losses": 12},
                            {"type": "away", "wins": 20, "losses": 18},
                        ]
                    },
                    "runsScored": 360, "runsAllowed": 298,
                    "divisionRank": "1",
                },
            }
        ]
    }
    mock_get.return_value = mock_resp

    profile = get_team_profile("NYY", season=2026)
    assert profile["team"] == "NYY"
    assert profile["record"] == "45-30"
    assert profile["run_diff"] == 62
    assert "pyth_pct" in profile
