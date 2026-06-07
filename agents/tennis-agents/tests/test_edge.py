from edge import (
    kelly_criterion, american_to_decimal, analyze_all_edges,
    check_moneyline_edge, check_game_handicap_edge, check_total_games_edge,
    apply_bet_filters, MAX_KELLY_PCT,
)
from calibrate import SIM_PROB_CAP


def test_kelly_criterion_positive_edge():
    kelly = kelly_criterion(0.55, 2.0)
    assert 0.05 < kelly < 0.15


def test_kelly_criterion_no_edge():
    assert kelly_criterion(0.50, 2.0) == 0


def test_kelly_criterion_negative_edge():
    assert kelly_criterion(0.40, 2.0) == 0


def test_american_to_decimal():
    assert american_to_decimal(-150) == round(100 / 150 + 1, 4)
    assert american_to_decimal(130) == round(130 / 100 + 1, 4)
    assert american_to_decimal(100) == 2.0


def test_check_moneyline_edge_found():
    sim = {"predictions": {"moneyline": {"player_a_win_prob": 0.62, "player_b_win_prob": 0.38}}}
    odds = {"moneyline": {"player_a": -130, "player_b": 110}, "implied_probs": {"player_a": 0.565, "player_b": 0.435}}
    result = check_moneyline_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["side"] == "player_a"
    assert result["edge"] > 0.05


def test_check_moneyline_edge_none():
    sim = {"predictions": {"moneyline": {"player_a_win_prob": 0.56, "player_b_win_prob": 0.44}}}
    odds = {"moneyline": {"player_a": -150, "player_b": 130}, "implied_probs": {"player_a": 0.585, "player_b": 0.415}}
    result = check_moneyline_edge(sim, odds, tour="atp")
    if result:
        assert result["edge"] >= 0.02


def test_check_game_handicap_edge():
    sim = {"predictions": {"game_handicap": {"favorite_cover_prob": 0.58}}}
    odds = {"game_handicap": {"player_a_point": -4.5, "player_a_odds": -110, "player_b_point": 4.5, "player_b_odds": -110}}
    result = check_game_handicap_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["bet_type"] == "game_handicap"


def test_check_total_games_edge_over():
    sim = {"predictions": {"total_games": {"over_prob": 0.62, "under_prob": 0.38, "projected_games": 24.0}}}
    odds = {"total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110}}
    result = check_total_games_edge(sim, odds, tour="atp")
    assert result is not None
    assert "over" in result["side"]


def test_analyze_all_edges_returns_list():
    sim = {"predictions": {
        "moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35},
        "game_handicap": {"favorite_cover_prob": 0.55},
        "total_games": {"over_prob": 0.60, "under_prob": 0.40, "projected_games": 24.0},
    }}
    odds = {
        "moneyline": {"player_a": -140, "player_b": 120},
        "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110, "player_b_point": 3.5, "player_b_odds": -110},
        "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"player_a": 0.583, "player_b": 0.417},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert isinstance(bets, list)
    assert len(bets) <= 3
    for bet in bets:
        assert "bet_type" in bet
        assert "edge" in bet
        assert "kelly_pct" in bet


def test_wta_uses_smaller_kelly():
    sim = {"predictions": {"moneyline": {"player_a_win_prob": 0.70, "player_b_win_prob": 0.30}}}
    odds = {"moneyline": {"player_a": -140, "player_b": 120}, "implied_probs": {"player_a": 0.583, "player_b": 0.417}}
    atp_result = check_moneyline_edge(sim, odds, tour="atp")
    wta_result = check_moneyline_edge(sim, odds, tour="wta")
    assert atp_result is not None and wta_result is not None
    assert wta_result["kelly_pct"] < atp_result["kelly_pct"]


def test_confidence_affects_kelly():
    """High confidence should produce larger Kelly than low confidence."""
    sim_high = {"predictions": {"moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35, "confidence": "high"}}}
    sim_low = {"predictions": {"moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35, "confidence": "low"}}}
    odds = {"moneyline": {"player_a": -140, "player_b": 120}, "implied_probs": {"player_a": 0.583, "player_b": 0.417}}
    high = check_moneyline_edge(sim_high, odds, tour="atp")
    low = check_moneyline_edge(sim_low, odds, tour="atp")
    assert high is not None and low is not None
    assert high["kelly_pct"] > low["kelly_pct"]


def test_ml_and_game_handicap_both_kept():
    """ML and game handicap are separate bets and should both surface when each has edge."""
    sim = {"predictions": {
        "moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35, "confidence": "high"},
        "game_handicap": {"favorite_cover_prob": 0.58, "confidence": "medium"},
        "total_games": {"over_prob": 0.60, "under_prob": 0.40, "projected_games": 24.0, "confidence": "medium"},
    }}
    odds = {
        "moneyline": {"player_a": -140, "player_b": 120},
        "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110, "player_b_point": 3.5, "player_b_odds": -110},
        "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"player_a": 0.583, "player_b": 0.417},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    bet_types = [b["bet_type"] for b in bets]
    assert "moneyline" in bet_types and "game_handicap" in bet_types


def test_kelly_capped():
    """Kelly should never exceed MAX_KELLY_PCT."""
    sim = {"predictions": {"moneyline": {"player_a_win_prob": 0.90, "player_b_win_prob": 0.10, "confidence": "high"}}}
    odds = {"moneyline": {"player_a": -110, "player_b": -110}, "implied_probs": {"player_a": 0.524, "player_b": 0.476}}
    result = check_moneyline_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["kelly_pct"] <= MAX_KELLY_PCT


def test_moneyline_returns_sim_prob_raw_alongside_calibrated():
    sim = {"predictions": {"moneyline": {"player_a_win_prob": 0.62, "player_b_win_prob": 0.38}}}
    odds = {"moneyline": {"player_a": -130, "player_b": 110}, "implied_probs": {"player_a": 0.565, "player_b": 0.435}}
    result = check_moneyline_edge(sim, odds, tour="atp")
    assert result is not None
    # Mid-range prob: calibrated == raw
    assert result["sim_prob"] == 0.62
    assert result["sim_prob_raw"] == 0.62


def test_moneyline_calibration_caps_high_prob():
    """Raw 0.92 should be capped to SIM_PROB_CAP on the returned sim_prob; raw preserved."""
    sim = {"predictions": {"moneyline": {"player_a_win_prob": 0.92, "player_b_win_prob": 0.08}}}
    # Market implies 0.78 / 0.22 — still leaves a 0.07 edge after capping to 0.85.
    odds = {"moneyline": {"player_a": -400, "player_b": 300}, "implied_probs": {"player_a": 0.78, "player_b": 0.22}}
    result = check_moneyline_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["side"] == "player_a"
    assert result["sim_prob"] == SIM_PROB_CAP
    assert result["sim_prob_raw"] == 0.92
    # Edge should be computed against the calibrated prob, not raw.
    assert abs(result["edge"] - (SIM_PROB_CAP - 0.78)) < 1e-6


def test_game_handicap_returns_sim_prob_raw():
    sim = {"predictions": {"game_handicap": {"favorite_cover_prob": 0.58}}}
    odds = {"game_handicap": {"player_a_point": -4.5, "player_a_odds": -110, "player_b_point": 4.5, "player_b_odds": -110}}
    result = check_game_handicap_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["sim_prob_raw"] == 0.58


def test_total_games_returns_sim_prob_raw():
    sim = {"predictions": {"total_games": {"over_prob": 0.62, "under_prob": 0.38, "projected_games": 24.0}}}
    odds = {"total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110}}
    result = check_total_games_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["sim_prob_raw"] == 0.62


def test_apply_bet_filters_keeps_in_range_bet():
    bets = [{"bet_type": "moneyline", "side": "player_a", "odds": -110, "edge": 0.10}]
    assert apply_bet_filters(bets) == bets


def test_apply_bet_filters_drops_bet_above_max_edge():
    # moneyline max_edge is 0.25 — 0.35 should be dropped
    bets = [{"bet_type": "moneyline", "side": "player_a", "odds": -110, "edge": 0.35}]
    assert apply_bet_filters(bets) == []


def test_apply_bet_filters_passes_unknown_type_through():
    bets = [{"bet_type": "some_future_market", "side": "x", "odds": 100, "edge": 0.99}]
    assert apply_bet_filters(bets) == bets


def test_apply_bet_filters_per_type_thresholds_differ():
    # total_games max_edge (0.18) is tighter than moneyline (0.25).
    bets = [
        {"bet_type": "moneyline",   "side": "player_a",  "odds": -110, "edge": 0.22},
        {"bet_type": "total_games", "side": "over 22.5", "odds": -110, "edge": 0.22},
    ]
    kept_types = [b["bet_type"] for b in apply_bet_filters(bets)]
    assert "moneyline" in kept_types
    assert "total_games" not in kept_types


def test_apply_bet_filters_disabled_drops_all_of_type(monkeypatch):
    import config
    monkeypatch.setitem(config.BET_FILTERS, "moneyline", {"disabled": True})
    bets = [{"bet_type": "moneyline", "side": "player_a", "odds": -110, "edge": 0.08}]
    assert apply_bet_filters(bets) == []


def test_apply_bet_filters_empty_input():
    assert apply_bet_filters([]) == []
