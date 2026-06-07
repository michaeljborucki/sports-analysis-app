from agents.health_check import check_ufc_stats


def test_check_ufc_stats_returns_dict():
    # Just verify the function returns the right shape
    result = check_ufc_stats()
    assert isinstance(result, dict)
    assert "status" in result
