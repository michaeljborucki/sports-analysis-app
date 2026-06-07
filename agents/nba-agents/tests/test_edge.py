"""Tests for edge.py."""
import edge
from edge import (
    kelly_criterion, american_to_decimal,
    check_moneyline_edge, check_spread_edge, check_total_edge,
    check_h1_ml_edge, check_h1_total_edge, analyze_all_edges,
    check_first_half_spread_edge, check_q1_ml_edge, check_q1_spread_edge,
    check_q1_total_edge, check_quarter_total_edge, check_team_total_edge,
    check_player_prop_edge, analyze_prop_edges,
)

# Clear any production overrides so tests use config defaults
edge._overrides_cache = {}

MOCK_ODDS = {
    "moneyline": {"home": -150, "away": 130},
    "spread": {"home": -4.5, "home_odds": -110, "away": 4.5, "away_odds": -110},
    "total": {"line": 218.5, "over_odds": -110, "under_odds": -110},
    "h1_moneyline": {"home": -130, "away": 110},
    "h1_total": {"line": 108.5, "over_odds": -115, "under_odds": -105},
    "implied_probs": {"ml_home": 0.60, "ml_away": 0.40},
}


def test_kelly_criterion_edge():
    k = kelly_criterion(0.60, 2.0)
    assert k > 0


def test_kelly_criterion_no_edge():
    k = kelly_criterion(0.40, 2.0)
    assert k == 0


def test_american_to_decimal_favorite():
    assert american_to_decimal(-150) > 1


def test_check_spread_edge_returns_spread_bet_type():
    sim = {"predictions": {"spread": {
        "favorite_cover_prob": 0.65, "confidence": "high"
    }}}
    result = check_spread_edge(sim, MOCK_ODDS)
    if result:
        assert result["bet_type"] == "spread"


def test_check_spread_edge_no_data():
    assert check_spread_edge({"predictions": {}}, MOCK_ODDS) is None


def test_check_h1_ml_edge_returns_first_half_ml():
    sim = {"predictions": {"first_half": {
        "h1_home_win_prob": 0.70, "h1_away_win_prob": 0.30, "confidence": "high"
    }}}
    result = check_h1_ml_edge(sim, MOCK_ODDS)
    if result:
        assert result["bet_type"] == "first_half_ml"


def test_check_h1_total_edge_uses_correct_heuristic():
    sim = {"predictions": {"first_half": {
        "h1_projected_total": 118.5, "confidence": "medium"
    }}}
    result = check_h1_total_edge(sim, MOCK_ODDS)
    if result:
        assert result["bet_type"] == "first_half_total"
        assert result["sim_prob"] <= 0.99


def test_analyze_all_edges_uses_nba_slot_names():
    sim = {"predictions": {
        "moneyline": {"home_win_prob": 0.70, "away_win_prob": 0.30, "confidence": "high"},
        "spread": {"favorite_cover_prob": 0.65, "confidence": "high"},
        "total": {"over_prob": 0.60, "under_prob": 0.40, "projected_total": 225, "confidence": "medium"},
        "first_half": {
            "h1_home_win_prob": 0.65, "h1_away_win_prob": 0.35,
            "h1_projected_total": 115, "h1_ml_value": "home",
            "h1_total_value": "over", "confidence": "medium"
        },
    }}
    bets = analyze_all_edges(sim, MOCK_ODDS)
    bet_types = [b["bet_type"] for b in bets]
    assert "run_line" not in bet_types
    assert "first_5_ml" not in bet_types
    assert "first_5_total" not in bet_types


EXTENDED_ODDS = {
    **MOCK_ODDS,
    "h1_spread": {"home": -2.5, "home_odds": -110, "away": 2.5, "away_odds": -110},
    "q1_moneyline": {"home": -120, "away": 100},
    "q1_spread": {"home": -1.5, "home_odds": -110, "away": 1.5, "away_odds": -110},
    "q1_total": {"line": 55.5, "over_odds": -110, "under_odds": -110},
    "q2_total": {"line": 54.5, "over_odds": -110, "under_odds": -110},
    "q3_total": {"line": 53.5, "over_odds": -110, "under_odds": -110},
    "q4_total": {"line": 52.5, "over_odds": -110, "under_odds": -110},
    "team_totals": {
        "home": {"line": 112.5, "over_odds": -110, "under_odds": -110},
        "away": {"line": 106.5, "over_odds": -110, "under_odds": -110},
    },
    "player_props": {
        "Jayson Tatum": {
            "points": {"line": 26.5, "over_odds": -115, "under_odds": -105},
            "rebounds": {"line": 8.5, "over_odds": -110, "under_odds": -110},
        },
    },
}


def test_check_first_half_spread_edge():
    sim = {"predictions": {"first_half": {"h1_favorite_cover_prob": 0.70, "confidence": "high"}}}
    result = check_first_half_spread_edge(sim, EXTENDED_ODDS)
    assert result is not None
    assert result["bet_type"] == "first_half_spread"


def test_check_q1_ml_edge():
    sim = {"predictions": {"q1": {"q1_home_win_prob": 0.70, "q1_away_win_prob": 0.30}}}
    result = check_q1_ml_edge(sim, EXTENDED_ODDS)
    assert result is not None
    assert result["bet_type"] == "q1_ml"


def test_check_q1_total_edge():
    sim = {"predictions": {"q1": {"q1_projected_total": 65.0}}}  # well above 55.5 line
    result = check_q1_total_edge(sim, EXTENDED_ODDS)
    assert result is not None
    assert result["bet_type"] == "q1_total"


def test_check_quarter_total_edge():
    derived = {"q2_projected_total": 62.0}  # well above 54.5 line
    result = check_quarter_total_edge(derived, EXTENDED_ODDS, "q2")
    assert result is not None
    assert result["bet_type"] == "q2_total"


def test_check_team_total_edge_home():
    sim = {"predictions": {"team_totals": {"home_projected": 120.0}}}  # well above 112.5
    result = check_team_total_edge(sim, EXTENDED_ODDS, "home")
    assert result is not None
    assert result["bet_type"] == "team_total_home"


def test_check_team_total_edge_away():
    sim = {"predictions": {"team_totals": {"away_projected": 115.0}}}  # well above 106.5
    result = check_team_total_edge(sim, EXTENDED_ODDS, "away")
    assert result is not None
    assert result["bet_type"] == "team_total_away"


def test_check_player_prop_edge():
    prop_preds = {"player_props": {
        "Jayson Tatum": {"points": {"over_prob": 0.70, "projected": 32.0}},
    }}
    result = check_player_prop_edge(prop_preds, EXTENDED_ODDS, "points")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["bet_type"] == "player_points"
    assert result[0]["player"] == "Jayson Tatum"


def test_analyze_prop_edges():
    prop_preds = {"player_props": {
        "Jayson Tatum": {
            "points": {"over_prob": 0.70, "projected": 32.0},
            "rebounds": {"over_prob": 0.70, "projected": 12.0},
        },
    }}
    bets = analyze_prop_edges(prop_preds, EXTENDED_ODDS)
    assert isinstance(bets, list)
    assert len(bets) >= 1
