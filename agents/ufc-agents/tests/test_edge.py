from edge import (
    american_to_decimal, kelly_criterion,
    check_moneyline_edge, check_total_rounds_edge, check_method_edge,
    analyze_all_edges,
)


def test_american_to_decimal_negative():
    assert american_to_decimal(-200) == 1.5


def test_american_to_decimal_positive():
    assert american_to_decimal(200) == 3.0


def test_kelly_criterion_positive_edge():
    result = kelly_criterion(0.60, 2.0)
    assert result > 0


def test_kelly_criterion_no_edge():
    result = kelly_criterion(0.40, 2.0)
    assert result == 0


def test_check_moneyline_edge_fighter_a():
    sim = {
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.75,
                "fighter_b_win_prob": 0.25,
                "confidence": "high",
            }
        }
    }
    odds = {
        "moneyline": {"fighter_a": -150, "fighter_b": 130},
        "implied_probs": {"fighter_a": 0.60, "fighter_b": 0.40},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "moneyline"
    assert result["side"] == "fighter_a"
    assert result["edge"] > 0.06


def test_check_moneyline_edge_no_value():
    sim = {
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.62,
                "fighter_b_win_prob": 0.38,
                "confidence": "medium",
            }
        }
    }
    odds = {
        "moneyline": {"fighter_a": -150, "fighter_b": 130},
        "implied_probs": {"fighter_a": 0.60, "fighter_b": 0.40},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is None


def test_check_total_rounds_edge_under():
    sim = {
        "predictions": {
            "total_rounds": {
                "over_prob": 0.35,
                "under_prob": 0.65,
                "confidence": "high",
            }
        }
    }
    odds = {
        "total_rounds": {
            "line": 2.5,
            "over_odds": -115,
            "under_odds": -105,
        }
    }
    result = check_total_rounds_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "total_rounds"
    assert "under" in result["side"]


def test_check_method_edge_ko():
    sim = {
        "predictions": {
            "method": {
                "ko_tko_prob": 0.65,
                "submission_prob": 0.15,
                "decision_prob": 0.20,
                "confidence": "medium",
            }
        }
    }
    odds = {
        "method_odds": {
            "ko_tko": -110,
            "submission": 200,
            "decision": 150,
        }
    }
    result = check_method_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "method"
    assert result["side"] == "ko_tko"


def test_analyze_all_edges_returns_list():
    sim = {"predictions": {}}
    odds = {}
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    assert len(bets) == 0


def test_no_mlb_edge_functions():
    import edge
    assert not hasattr(edge, "check_run_line_edge")
    assert not hasattr(edge, "check_f5_ml_edge")
    assert not hasattr(edge, "check_f5_total_edge")


def test_dynamic_threshold_high_confidence():
    from edge import dynamic_threshold
    base = 0.06
    result = dynamic_threshold(base, 0.85)
    assert result < base  # High confidence → lower threshold


def test_dynamic_threshold_low_confidence():
    from edge import dynamic_threshold
    base = 0.06
    result = dynamic_threshold(base, 0.35)
    assert result > base  # Low confidence → higher threshold


def test_kelly_with_confidence_high():
    from edge import kelly_with_confidence
    # High confidence should give bigger bet
    result = kelly_with_confidence(0.65, 2.0, 0.85, 0.125)
    baseline = kelly_with_confidence(0.65, 2.0, 0.55, 0.125)
    assert result > baseline


def test_correlation_reduces_method_kelly():
    sim = {
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.80,
                "fighter_b_win_prob": 0.20,
                "confidence": 0.80,
            },
            "method": {
                "ko_tko_prob": 0.70,
                "submission_prob": 0.15,
                "decision_prob": 0.15,
                "confidence": 0.75,
            },
        }
    }
    odds = {
        "moneyline": {"fighter_a": -150, "fighter_b": 130},
        "implied_probs": {"fighter_a": 0.60, "fighter_b": 0.40},
        "method_odds": {"ko_tko": -110, "submission": 300, "decision": 250},
    }
    bets = analyze_all_edges(sim, odds)
    method_bets = [b for b in bets if b["bet_type"] == "method"]
    if method_bets:
        # Method kelly should be reduced due to correlation with moneyline
        assert method_bets[0].get("kelly_pct", 0) < 0.05


def test_extreme_odds_filtered():
    sim = {
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.95,
                "fighter_b_win_prob": 0.05,
                "confidence": 0.85,
            },
        }
    }
    odds = {
        "moneyline": {"fighter_a": -600, "fighter_b": 450},
        "implied_probs": {"fighter_a": 0.85, "fighter_b": 0.15},
    }
    bets = analyze_all_edges(sim, odds)
    # -600 should be filtered as heavy chalk
    ml_bets = [b for b in bets if b["bet_type"] == "moneyline"]
    assert len(ml_bets) == 0
