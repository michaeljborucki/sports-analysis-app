from agents.health_check import check_cricket_api


def test_check_cricket_api_returns_tuple():
    # Just verify the function returns the right shape
    ok, msg = check_cricket_api()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert "Cricket API" in msg
