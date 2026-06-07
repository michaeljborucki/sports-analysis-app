"""Tests for scrapers/injuries.py."""
from scrapers.injuries import classify_impact_tier, get_injuries


def test_classify_star():
    assert classify_impact_tier(34.5) == "star"


def test_classify_rotation():
    assert classify_impact_tier(22.0) == "rotation"


def test_classify_bench():
    assert classify_impact_tier(10.0) == "bench"


def test_get_injuries_returns_list():
    result = get_injuries()
    assert isinstance(result, list)
