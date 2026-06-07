from agents.health_check import check_mlb_api


def test_check_mlb_api_returns_tuple():
    # Just verify the function returns the right shape
    ok, msg = check_mlb_api()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert "MLB Stats API" in msg
