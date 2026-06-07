from config import (
    EDGE_THRESHOLDS, PARK_FACTORS, TEAM_ABBREVS,
    MLB_API_BASE, ODDS_API_BASE, KELLY_FRACTION,
)


def test_edge_thresholds_exist_for_all_bet_types():
    for bet_type in ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]:
        assert bet_type in EDGE_THRESHOLDS
        assert 0 < EDGE_THRESHOLDS[bet_type] < 1


def test_moneyline_threshold_lowered_to_three_pct():
    """ML threshold lowered to 0.03 (from 0.05) on 2026-04-28 — ML is the
    sharpest market, real edges are smaller and rarer. Pinning the value
    so it isn't silently bumped back without justification."""
    assert EDGE_THRESHOLDS["moneyline"] == 0.03


def test_run_line_threshold_lowered_to_five_pct():
    """Run line lowered to 0.05 (from 0.06) on 2026-04-28 — historical ROI
    is +17.8% on this bet type, the strongest signal in the system. Lower
    bar lets more legitimate edges flow through."""
    assert EDGE_THRESHOLDS["run_line"] == 0.05


def test_park_factors_cover_all_30_teams():
    assert len(PARK_FACTORS) == 30
    for team, factors in PARK_FACTORS.items():
        assert "runs" in factors
        assert "hr" in factors
        assert "name" in factors


def test_team_abbrevs():
    assert len(TEAM_ABBREVS) == 30
    assert "NYY" in TEAM_ABBREVS
    assert "LAD" in TEAM_ABBREVS


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 0.25
