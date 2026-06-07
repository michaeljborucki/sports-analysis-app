"""Regression tests pinning the deterministic edge-detection + filter pipeline.

These tests catch silent drift in any of: calibration cap, edge math, Kelly
sizing, worst-case-vig filter, BET_FILTERS behavior, bet-dict shape. If one
fails, READ the diff carefully before updating the expected values — the
point of this file is to make unintended behavior changes loud.

Inputs are canned sim-result + odds dicts; LLMs and live APIs are not touched.
"""
from edge import analyze_all_edges, apply_bet_filters


# -- Scenario 1: realistic match, all three bet types produce bets, none filtered
SIM_SCENARIO_1 = {
    "predictions": {
        # Raw ML 0.92 exceeds SIM_PROB_CAP (0.85) — exercises the calibration cap.
        "moneyline":     {"player_a_win_prob": 0.92, "player_b_win_prob": 0.08, "confidence": "medium"},
        "game_handicap": {"favorite_cover_prob": 0.58, "confidence": "medium"},
        "total_games":   {"over_prob": 0.62, "under_prob": 0.38, "projected_games": 24.0, "confidence": "medium"},
    }
}

ODDS_SCENARIO_1 = {
    "moneyline":     {"player_a": -400, "player_b": 300},
    "game_handicap": {"player_a_point": -4.5, "player_a_odds": -110, "player_b_point": 4.5, "player_b_odds": -110},
    "total_games":   {"line": 22.5, "over_odds": -110, "under_odds": -110},
    "implied_probs": {"player_a": 0.75, "player_b": 0.22},
}

EXPECTED_BETS_SCENARIO_1 = [
    {
        "bet_type": "moneyline", "side": "player_a", "odds": -400,
        "sim_prob": 0.85,       # calibrated from raw 0.92
        "sim_prob_raw": 0.92,
        "market_prob": 0.75, "edge": 0.1, "worst_case_edge": 0.1,
        "kelly_pct": 0.0437, "confidence": "medium",
    },
    {
        "bet_type": "game_handicap", "side": "player_a -4.5", "odds": -110,
        "sim_prob": 0.58, "sim_prob_raw": 0.58,
        "market_prob": 0.5, "edge": 0.08, "worst_case_edge": 0.1038,
        "kelly_pct": 0.0206, "confidence": "medium",
    },
    {
        "bet_type": "total_games", "side": "over 22.5", "odds": -110,
        "sim_prob": 0.62, "sim_prob_raw": 0.62,
        "market_prob": 0.5, "edge": 0.12, "worst_case_edge": 0.1438,
        "kelly_pct": 0.0353, "confidence": "medium",
    },
]


def test_pipeline_regression_all_three_bet_types_clean_pass():
    """Canonical three-market match: calibration caps ML, handicap and totals pass untouched,
    BET_FILTERS accepts all three.
    """
    bets = analyze_all_edges(SIM_SCENARIO_1, ODDS_SCENARIO_1, tour="atp")
    filtered = apply_bet_filters(bets)
    assert bets == EXPECTED_BETS_SCENARIO_1
    assert filtered == EXPECTED_BETS_SCENARIO_1  # nothing filtered


def test_pipeline_regression_wta_kelly_halved():
    """Same scenario, wta tour: Kelly fraction 0.125 (half of atp 0.25) should halve each kelly_pct."""
    bets = analyze_all_edges(SIM_SCENARIO_1, ODDS_SCENARIO_1, tour="wta")
    assert len(bets) == 3
    # Kelly halves via TOUR_CONFIG[wta].kelly_fraction = 0.125 (atp = 0.25). Not a
    # perfect halving due to intermediate rounding inside kelly_criterion().
    assert bets[0]["kelly_pct"] == 0.0219
    assert bets[1]["kelly_pct"] == 0.0103
    assert bets[2]["kelly_pct"] == 0.0177


# -- Scenario 2: moneyline edge too large, BET_FILTERS.max_edge rejects it
SIM_SCENARIO_2 = {
    "predictions": {
        "moneyline":     {"player_a_win_prob": 0.95, "player_b_win_prob": 0.05, "confidence": "high"},
        "game_handicap": {"favorite_cover_prob": 0.55, "confidence": "medium"},
        "total_games":   {"over_prob": 0.62, "under_prob": 0.38, "projected_games": 24.0, "confidence": "medium"},
    }
}

ODDS_SCENARIO_2 = {
    "moneyline":     {"player_a": +150, "player_b": -180},  # market massively underpricing A
    "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110, "player_b_point": 3.5, "player_b_odds": -110},
    "total_games":   {"line": 22.5, "over_odds": -110, "under_odds": -110},
    "implied_probs": {"player_a": 0.40, "player_b": 0.60},
}


def test_pipeline_regression_filter_rejects_extreme_edge():
    """Raw 0.95 caps to 0.85, market says 0.40, edge = 0.45 — well above moneyline
    max_edge (0.25). Filter drops the moneyline bet. game_handicap and totals
    clear the (now 3%) edge threshold and pass BET_FILTERS (their edges are
    below their per-type max_edge caps)."""
    bets = analyze_all_edges(SIM_SCENARIO_2, ODDS_SCENARIO_2, tour="atp")
    filtered = apply_bet_filters(bets)

    # All three bet types surface at the edge-detection stage now that
    # EDGE_THRESHOLDS are 3%/3%/3% uniform.
    assert "moneyline" in {b["bet_type"] for b in bets}

    ml_bet = next(b for b in bets if b["bet_type"] == "moneyline")
    assert ml_bet["edge"] == 0.45
    assert ml_bet["sim_prob"] == 0.85       # calibrated
    assert ml_bet["sim_prob_raw"] == 0.95   # preserved

    # Post-filter: moneyline (edge 0.45 > max_edge 0.25) must be dropped by BET_FILTERS
    assert "moneyline" not in {b["bet_type"] for b in filtered}


# -- Scenario 3: no edge anywhere
def test_pipeline_regression_no_edge():
    """Sim agrees with market — no bets surface. Tightened on 2026-04-24 when
    EDGE_THRESHOLDS dropped to 2%; sim probs now match market implieds exactly
    so no edge can surface regardless of threshold."""
    sim = {
        "predictions": {
            "moneyline":     {"player_a_win_prob": 0.55, "player_b_win_prob": 0.45, "confidence": "medium"},
            "game_handicap": {"favorite_cover_prob": 0.505, "confidence": "medium"},
            "total_games":   {"over_prob": 0.50, "under_prob": 0.50, "projected_games": 22.5, "confidence": "medium"},
        }
    }
    odds = {
        "moneyline":     {"player_a": -130, "player_b": 110},
        "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110, "player_b_point": 3.5, "player_b_odds": -110},
        "total_games":   {"line": 22.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"player_a": 0.55, "player_b": 0.45},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert apply_bet_filters(bets) == []


# -- Scenario 4: underdog moneyline value
def test_pipeline_regression_underdog_moneyline_value():
    """Sim thinks player_b is actually the winner, market disagrees."""
    sim = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.40, "player_b_win_prob": 0.60, "confidence": "medium"},
        }
    }
    odds = {
        "moneyline":     {"player_a": -140, "player_b": 120},
        "implied_probs": {"player_a": 0.50, "player_b": 0.45},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert len(bets) == 1
    assert bets[0]["bet_type"] == "moneyline"
    assert bets[0]["side"] == "player_b"
    assert bets[0]["sim_prob"] == 0.60
    assert bets[0]["sim_prob_raw"] == 0.60
    assert bets[0]["edge"] == 0.15
    assert bets[0]["odds"] == 120


# -- Scenario 5: handicap dog side value
def test_pipeline_regression_handicap_dog_side():
    """favorite_cover_prob 0.35 means dog has 0.65 — check dog-side bet path."""
    sim = {
        "predictions": {
            "game_handicap": {"favorite_cover_prob": 0.35, "confidence": "medium"},
        }
    }
    odds = {
        "game_handicap": {"player_a_point": -4.5, "player_a_odds": -110, "player_b_point": 4.5, "player_b_odds": -110},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert len(bets) == 1
    b = bets[0]
    assert b["bet_type"] == "game_handicap"
    assert b["side"] == "player_b 4.5"
    assert b["sim_prob"] == 0.65        # 1 - 0.35
    assert b["sim_prob_raw"] == 0.65    # 1 - 0.35 (since fav raw was below cap)
    assert b["edge"] == 0.15


# -- Notify filter_bets regression (separate from BET_FILTERS — this is the Discord-display gate)
def test_regression_notify_filter_bets():
    """notify.filter_bets: allowlist + min_edge + min_kelly."""
    from notify.format import filter_bets
    bets = [
        {"bet_type": "moneyline",   "edge": 0.10, "kelly_pct": 0.02},
        {"bet_type": "moneyline",   "edge": 0.02, "kelly_pct": 0.02},   # below min_edge
        {"bet_type": "total_games", "edge": 0.10, "kelly_pct": 0.001},  # below min_kelly
        {"bet_type": "prop_market", "edge": 0.99, "kelly_pct": 0.05},   # not in allowed_types
    ]
    kept = filter_bets(bets, ["moneyline", "total_games"], min_edge=0.05, min_kelly=0.005)
    assert kept == [{"bet_type": "moneyline", "edge": 0.10, "kelly_pct": 0.02}]
