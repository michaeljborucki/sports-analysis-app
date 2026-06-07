"""Tests for scrapers/team_stats.py."""
from scrapers.team_stats import pythagorean_win_pct


def test_pythagorean_win_pct_nba():
    pct = pythagorean_win_pct(110, 105, exp=14)
    assert 0.6 < pct < 0.8


def test_pythagorean_win_pct_equal():
    assert pythagorean_win_pct(100, 100) == 0.5


def test_pythagorean_win_pct_zero():
    assert pythagorean_win_pct(0, 0) == 0.5
