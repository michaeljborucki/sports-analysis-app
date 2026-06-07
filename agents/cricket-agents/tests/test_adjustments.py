import pytest
from adjustments import (
    get_league_factor,
    get_venue_factor,
    get_adjusted_std_dev,
    get_adjusted_multiplier,
)
from edge import detect_edge


def test_ipl_league_factor_match_total():
    factor = get_league_factor("ipl", "match_total_runs")
    assert factor == 1.21


def test_unknown_league_returns_1():
    factor = get_league_factor("nonexistent", "match_total_runs")
    assert factor == 1.0


def test_unknown_bet_type_returns_1():
    factor = get_league_factor("ipl", "nonexistent_type")
    assert factor == 1.0


def test_venue_factor_wankhede():
    factor = get_venue_factor("Wankhede Stadium")
    assert factor == 1.12


def test_venue_factor_chepauk():
    factor = get_venue_factor("M. A. Chidambaram Stadium")
    assert factor == 1.03  # Updated from research: avg 1st inn 168 vs baseline 163


def test_venue_factor_fuzzy_match():
    factor = get_venue_factor("Wankhede Stadium, Mumbai")
    assert factor == 1.12


def test_venue_factor_unknown_returns_1():
    factor = get_venue_factor("Some Random Ground")
    assert factor == 1.0


def test_venue_factor_none_returns_1():
    factor = get_venue_factor(None)
    assert factor == 1.0


def test_adjusted_std_dev_ipl_wankhede():
    """IPL at Wankhede should have higher std_dev (more variance)."""
    adj = get_adjusted_std_dev("match_total_runs", league="ipl", venue="Wankhede Stadium")
    base = 60  # from config
    expected = 60 * 1.21 * 1.12  # league * venue
    assert adj == pytest.approx(expected, abs=0.1)


def test_adjusted_std_dev_bbl_mcg():
    """BBL at MCG should have lower std_dev (less variance)."""
    adj = get_adjusted_std_dev("match_total_runs", league="bbl", venue="Melbourne Cricket Ground")
    base = 60
    expected = 60 * 1.02 * 0.95  # league * venue
    assert adj == pytest.approx(expected, abs=0.1)


def test_adjusted_std_dev_no_context():
    """Without context, returns base std_dev."""
    adj = get_adjusted_std_dev("match_total_runs")
    assert adj == 60


def test_adjusted_std_dev_exponential_returns_none():
    """Exponential engine types don't have std_dev."""
    adj = get_adjusted_std_dev("player_runs")
    assert adj is None


def test_adjusted_multiplier_ipl():
    """IPL multiplier should be smaller (higher variance → less sensitive)."""
    base_mult = 0.008  # from config
    adj_mult = get_adjusted_multiplier("match_total_runs", league="ipl")
    assert adj_mult < base_mult  # higher scoring = less sensitive


def test_adjusted_multiplier_bbl():
    """BBL multiplier should be larger (lower variance → more sensitive)."""
    base_mult = 0.008
    adj_mult = get_adjusted_multiplier("match_total_runs", league="bbl")
    assert adj_mult > base_mult  # lower scoring = more sensitive


def test_adjusted_multiplier_chennai_vs_chinnaswamy():
    """Chennai (slow turner) should produce a larger multiplier than Chinnaswamy (batting paradise)."""
    chennai = get_adjusted_multiplier("match_total_runs", venue="M. A. Chidambaram Stadium")
    chinnaswamy = get_adjusted_multiplier("match_total_runs", venue="M. Chinnaswamy Stadium")
    assert chennai > chinnaswamy  # lower scoring = more sensitive


# === Integration: detect_edge with context ===

def test_detect_edge_with_league_context():
    """Same projection, different leagues → different edges."""
    ipl_result = detect_edge("match_total_runs", 360, 340, league="ipl")
    bbl_result = detect_edge("match_total_runs", 360, 340, league="bbl")
    # BBL should show larger edge (tighter multiplier on same delta)
    if ipl_result and bbl_result:
        assert bbl_result["edge"] > ipl_result["edge"]


def test_detect_edge_with_venue_context():
    """Venue context adjusts the multiplier."""
    result = detect_edge("match_total_runs", 360, 340, venue="Wankhede Stadium")
    assert result is not None
    assert result["edge"] > 0


def test_detect_edge_without_context_unchanged():
    """Without context, behaves identically to base multiplier."""
    result_no_ctx = detect_edge("match_total_runs", 360, 340)
    result_with_ctx = detect_edge("match_total_runs", 360, 340, league=None, venue=None)
    assert result_no_ctx["edge"] == result_with_ctx["edge"]
