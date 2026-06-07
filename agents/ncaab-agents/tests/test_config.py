from config import (
    EDGE_THRESHOLDS, ODDS_API_BASE, KELLY_FRACTION,
    BET_SLOTS, POWER_CONFERENCES, HOME_COURT_ADVANTAGE,
    ESPN_CBB_BASE, ODDS_SPORT_KEY,
)


def test_edge_thresholds_exist_for_all_bet_types():
    for bet_type in ["moneyline", "spread", "total", "first_half_ml", "first_half_total"]:
        assert bet_type in EDGE_THRESHOLDS
        assert 0 < EDGE_THRESHOLDS[bet_type] < 1


def test_bet_slots_match_edge_thresholds():
    assert set(BET_SLOTS) == set(EDGE_THRESHOLDS.keys())


def test_power_conferences():
    assert len(POWER_CONFERENCES) >= 5
    assert "SEC" in POWER_CONFERENCES
    assert "ACC" in POWER_CONFERENCES


def test_home_court_advantage():
    assert 2.0 <= HOME_COURT_ADVANTAGE <= 5.0


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 0.25


def test_sport_key():
    assert ODDS_SPORT_KEY == "basketball_ncaab"


def test_total_threshold_raised():
    from config import EDGE_THRESHOLDS
    assert EDGE_THRESHOLDS["total"] >= 0.08, "Totals threshold must be >= 8% until calibrated"
    assert EDGE_THRESHOLDS["first_half_total"] >= 0.08


def test_h1_thresholds_raised():
    from config import EDGE_THRESHOLDS
    assert EDGE_THRESHOLDS["first_half_ml"] >= 0.07
    assert EDGE_THRESHOLDS["first_half_spread"] >= 0.07
