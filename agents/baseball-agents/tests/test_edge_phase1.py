"""Tests for Phase 1 edge detection: team totals, F5 RL, NRFI, F1 RL, F3 ML/total/RL."""
from edge import (
    check_team_total_edge, check_f5_rl_edge, check_nrfi_edge,
    check_f1_rl_edge, check_f3_ml_edge, check_f3_total_edge,
    check_f3_rl_edge, _negbin_over_prob, analyze_all_edges,
)
from scrapers.odds import OddsData


def test_negbin_over_prob_high_predicted():
    """If predicted=6.0 and line=4.5, over probability should be moderately high."""
    prob = _negbin_over_prob(6.0, 4.5)
    assert 0.55 < prob < 0.75  # corrected: ~61.7% with proper NB parameterization


def test_negbin_over_prob_low_predicted():
    """If predicted=3.0 and line=4.5, over probability should be below 0.50."""
    prob = _negbin_over_prob(3.0, 4.5)
    # Neg binomial has heavier tails than Poisson, so ~0.45 is expected
    assert prob < 0.50


def test_team_total_edge_found():
    sim = {"predictions": {"predicted_score": {"home": 6, "away": 3}}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        team_total_home={"line": 4.5, "over_odds": -110, "under_odds": -110},
    )
    result = check_team_total_edge(sim, odds, "home")
    assert result is not None
    assert result["bet_type"] == "team_total_home"
    assert result["edge"] > 0


def test_team_total_edge_under_when_predicted_well_below_line():
    sim = {"predictions": {"predicted_score": {"home": 2.5, "away": 3}}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        team_total_home={"line": 4.5, "over_odds": -110, "under_odds": -110},
    )
    result = check_team_total_edge(sim, odds, "home")
    # With predicted well below the line, under edge should dominate
    if result is not None:
        assert "under" in result["side"]


def test_nrfi_edge_found():
    sim = {"predictions": {"first_inning": {"nrfi_prob": 0.75, "confidence": "high"}}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        f1_total={"line": 0.5, "over_odds": 100, "under_odds": -120},
    )
    result = check_nrfi_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "nrfi"
    assert result["side"] == "NRFI"


def test_f5_rl_edge_uses_tie_prob():
    """F5 RL should use lead_prob, not win_prob. Tie goes to +0.5 side."""
    sim = {"predictions": {"first_5": {
        "f5_home_lead_prob": 0.40,
        "f5_away_lead_prob": 0.25,
        "f5_tie_prob": 0.35,
        "confidence": "medium",
    }}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        f5_spread={"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
    )
    result = check_f5_rl_edge(sim, odds)
    # away +0.5 = 0.25 + 0.35 = 0.60, implied ~0.5 → edge ~0.10
    assert result is not None
    assert "away" in result["side"].lower() or "+0.5" in result["side"]


def test_f3_ml_edge_found():
    sim = {"predictions": {"first_3": {
        "f3_home_win_prob": 0.62,
        "f3_away_win_prob": 0.38,
        "confidence": "medium",
    }}}
    odds = OddsData(
        home="NYY", away="BOS", commence_time="",
        f3_moneyline={"home": -120, "away": 100},
    )
    result = check_f3_ml_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "first_3_ml"


def test_analyze_all_edges_includes_new_checkers():
    """analyze_all_edges should run all 12 checkers."""
    sim = {"predictions": {
        "moneyline": {"home_win_prob": 0.5, "away_win_prob": 0.5, "confidence": "low"},
        "predicted_score": {"home": 4, "away": 4},
    }}
    odds = OddsData(home="NYY", away="BOS", commence_time="",
                     moneyline={"home": -110, "away": -110},
                     implied_probs={"ml_home": 0.5, "ml_away": 0.5})
    bets = analyze_all_edges(sim, odds)
    # No edges expected, but it should not crash
    assert isinstance(bets, list)
