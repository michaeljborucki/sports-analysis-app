"""Tests for scrapers/rest.py."""
from scrapers.rest import compute_rest_from_dates


def test_back_to_back():
    result = compute_rest_from_dates("2026-03-22", ["2026-03-21", "2026-03-19"])
    assert result["days_rest"] == 0
    assert result["is_b2b"] is True


def test_one_day_rest():
    result = compute_rest_from_dates("2026-03-22", ["2026-03-20", "2026-03-18"])
    assert result["days_rest"] == 1
    assert result["is_b2b"] is False


def test_no_recent_games():
    result = compute_rest_from_dates("2026-03-22", [])
    assert result["days_rest"] >= 3
    assert result["is_b2b"] is False


def test_games_last_7():
    dates = ["2026-03-21", "2026-03-19", "2026-03-17", "2026-03-10"]
    result = compute_rest_from_dates("2026-03-22", dates)
    assert result["games_last_7"] == 3
