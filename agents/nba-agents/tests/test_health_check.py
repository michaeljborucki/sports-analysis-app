from agents.health_check import check_nba_api


def test_check_nba_api_returns_tuple():
    # Just verify the function returns the right shape
    ok, msg = check_nba_api()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert "NBA API" in msg
