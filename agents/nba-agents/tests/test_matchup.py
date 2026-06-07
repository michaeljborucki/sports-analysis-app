"""Tests for scrapers/matchup.py."""
from scrapers.matchup import compute_pace_matchup


def test_compute_pace_matchup_similar():
    result = compute_pace_matchup(100.0, 101.0)
    assert result["projected_pace"] == 100.5
    assert "similar" in result["mismatch"].lower()


def test_compute_pace_matchup_fast_vs_slow():
    result = compute_pace_matchup(105.0, 95.0)
    assert result["projected_pace"] == 100.0
    assert result["projected_possessions"] > 0
