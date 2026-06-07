from unittest.mock import patch, MagicMock
from scrapers.ballpark import get_game_environment, _classify_wind_impact


def test_classify_wind_impact_out():
    assert _classify_wind_impact(15, "out") == "hitter_boost"


def test_classify_wind_impact_in():
    assert _classify_wind_impact(15, "in") == "pitcher_boost"


def test_classify_wind_impact_calm():
    assert _classify_wind_impact(3, "out") == "neutral"


@patch("scrapers.ballpark.requests.get")
def test_get_game_environment(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "main": {"temp": 72, "humidity": 55},  # imperial units = Fahrenheit
        "wind": {"speed": 12, "deg": 180},  # imperial units = mph
        "weather": [{"main": "Clear"}],
    }
    mock_get.return_value = mock_resp

    env = get_game_environment("NYY", "2026-04-01", "19:05")
    assert env["ballpark"] == "Yankee Stadium"
    # NYY runs factor updated 2026-04-21 (1.05 → 1.03) in the park-factor
    # recalibration; pin the current value to catch any unintended drift.
    assert env["park_factor_runs"] == 1.03
    assert "weather" in env
    assert env["weather"]["temp_f"] > 0
