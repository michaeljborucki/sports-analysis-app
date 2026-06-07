import pytest
from unittest.mock import patch
from scrapers.xg import get_xg_profile, _regress_to_mean, _estimate_clean_sheet_pct, _compute_btts_probability, estimate_btts_prob


def test_regress_to_mean_no_games():
    """With 0 games, returns league average."""
    assert _regress_to_mean(2.0, 1.3, 0) == 1.3


def test_regress_to_mean_many_games():
    """With many games, trusts observed rate more."""
    result = _regress_to_mean(2.0, 1.3, 30)
    assert result > 1.7  # Mostly trusts observed
    assert result < 2.0  # Still some regression


def test_regress_to_mean_few_games():
    """With few games, regresses heavily toward mean."""
    result = _regress_to_mean(2.0, 1.3, 3)
    assert result < 1.5  # Mostly league average


def test_clean_sheet_pct():
    """Higher xGA = lower clean sheet probability."""
    high_xga = _estimate_clean_sheet_pct(2.0)
    low_xga = _estimate_clean_sheet_pct(0.8)
    assert low_xga > high_xga
    assert 0 < high_xga < 1
    assert 0 < low_xga < 1


def test_btts_probability():
    """Both high-scoring teams = high BTTS probability."""
    high = _compute_btts_probability(2.0, 1.5, 2.0, 1.5)
    low = _compute_btts_probability(0.5, 0.5, 0.5, 0.5)
    assert high > low
    assert 0 < high < 1
    assert 0 < low < 1


@patch("scrapers.xg.get_team_profile")
def test_get_xg_profile_with_data(mock_profile):
    mock_profile.return_value = {
        "team": "Arsenal", "goals_for": 30, "goals_against": 12,
        "games_played": 15, "points": 35, "record": "11W-2D-2L",
        "goal_diff": 18, "standing": "1st in EPL",
    }
    profile = get_xg_profile("Arsenal", league="EPL")
    assert profile["team"] == "Arsenal"
    assert profile["xg_per_match"] > 1.3  # Better than average
    assert profile["xga_per_match"] < 1.3  # Better defense than average
    assert profile["xg_diff"] > 0
    assert profile["games_used"] == 15


@patch("scrapers.xg.get_team_profile")
def test_get_xg_profile_no_data(mock_profile):
    mock_profile.return_value = {
        "team": "New Team", "goals_for": 0, "goals_against": 0,
        "games_played": 0, "points": 0, "record": "", "goal_diff": 0, "standing": "",
    }
    profile = get_xg_profile("New Team", league="EPL")
    assert profile["xg_per_match"] == 1.4  # EPL avg / 2
    assert profile["xga_per_match"] == 1.4
    assert profile["xg_overperformance"] == 0.0
