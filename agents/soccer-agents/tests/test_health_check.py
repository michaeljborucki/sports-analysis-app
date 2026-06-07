from unittest.mock import patch
from agents.health_check import run_health_check

@patch("agents.health_check.check_espn_api", return_value=(True, "OK"))
@patch("agents.health_check.check_odds_api", return_value=(True, "OK"))
@patch("agents.health_check.check_openrouter", return_value=(True, "OK"))
@patch("agents.health_check.check_weather_api", return_value=(True, "OK"))
def test_health_check_all_pass(mock_w, mock_or, mock_odds, mock_espn):
    assert run_health_check() is True
