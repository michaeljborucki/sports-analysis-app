from agents.health_check import check_espn_api, check_odds_api, check_openrouter
from unittest.mock import patch, MagicMock


@patch("agents.health_check.requests.get")
def test_check_espn_api_success(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    ok, msg = check_espn_api()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert "ESPN" in msg
