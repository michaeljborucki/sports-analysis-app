import pytest
from edge import (
    american_to_decimal, kelly_criterion,
    check_asian_handicap_edge, check_total_edge, check_btts_edge,
    analyze_all_edges,
)


def test_american_to_decimal():
    assert american_to_decimal(-110) == pytest.approx(1.9091, abs=0.001)
    assert american_to_decimal(200) == pytest.approx(3.0, abs=0.001)


def test_kelly_criterion():
    assert kelly_criterion(0.55, 2.0) == pytest.approx(0.10, abs=0.01)
    assert kelly_criterion(0.40, 2.0) == 0  # no edge


def test_check_asian_handicap_edge_home():
    sim = {"predictions": {"asian_handicap": {
        "home_cover_prob": 0.60, "away_cover_prob": 0.40,
        "value_side": "home", "confidence": "medium",
    }}}
    odds = {"asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
            "implied_probs": {"ah_home": 0.524, "ah_away": 0.476}}
    result = check_asian_handicap_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "asian_handicap"
    assert result["side"] == "home -0.5"
    assert result["edge"] > 0.05


def test_check_asian_handicap_edge_no_value():
    sim = {"predictions": {"asian_handicap": {
        "home_cover_prob": 0.53, "away_cover_prob": 0.47,
        "confidence": "low",
    }}}
    odds = {"asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
            "implied_probs": {"ah_home": 0.524, "ah_away": 0.476}}
    result = check_asian_handicap_edge(sim, odds)
    assert result is None


def test_check_total_edge_over():
    sim = {"predictions": {"total": {
        "over_prob": 0.62, "under_prob": 0.38,
        "projected_goals": 3.0, "confidence": "high",
    }}}
    odds = {"total": {"line": 2.5, "over_odds": -115, "under_odds": -105}}
    result = check_total_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "total"
    assert "over" in result["side"]


def test_check_btts_edge_yes():
    sim = {"predictions": {"btts": {
        "btts_yes_prob": 0.65, "btts_no_prob": 0.35,
        "confidence": "medium",
    }}}
    odds = {"btts": {"yes_odds": -110, "no_odds": -110},
            "implied_probs": {}}
    result = check_btts_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "btts"
    assert result["side"] == "yes"


def test_check_btts_edge_no_value():
    sim = {"predictions": {"btts": {
        "btts_yes_prob": 0.52, "btts_no_prob": 0.48,
        "confidence": "low",
    }}}
    odds = {"btts": {"yes_odds": -110, "no_odds": -110},
            "implied_probs": {}}
    result = check_btts_edge(sim, odds)
    assert result is None


def test_analyze_all_edges():
    sim = {"predictions": {
        "asian_handicap": {"home_cover_prob": 0.60, "away_cover_prob": 0.40, "confidence": "medium"},
        "total": {"over_prob": 0.62, "under_prob": 0.38, "projected_goals": 3.0, "confidence": "high"},
        "btts": {"btts_yes_prob": 0.65, "btts_no_prob": 0.35, "confidence": "medium"},
    }}
    odds = {
        "asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
        "total": {"line": 2.5, "over_odds": -115, "under_odds": -105},
        "btts": {"yes_odds": -110, "no_odds": -110},
        "implied_probs": {"ah_home": 0.524, "ah_away": 0.476},
    }
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    assert len(bets) <= 3
    for b in bets:
        assert b["bet_type"] in ("asian_handicap", "total", "btts")


def test_no_mlb_edge_functions():
    import edge
    assert not hasattr(edge, "check_moneyline_edge")
    assert not hasattr(edge, "check_run_line_edge")
    assert not hasattr(edge, "check_f5_ml_edge")
    assert not hasattr(edge, "check_f5_total_edge")
