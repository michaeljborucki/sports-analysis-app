from agents.health_check import check_oddspapi, check_openrouter, run_health_check


def test_check_oddspapi_returns_tuple():
    ok, msg = check_oddspapi()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert "OddsPapi" in msg


def test_check_openrouter_returns_tuple():
    ok, msg = check_openrouter()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert "OpenRouter" in msg


def test_run_health_check_returns_bool():
    # run_health_check returns True when all critical checks pass,
    # False otherwise. Either is valid in CI (no real API keys set).
    result = run_health_check()
    assert isinstance(result, bool)
