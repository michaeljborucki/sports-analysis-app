from edge import (
    kelly_criterion, american_to_decimal, analyze_all_edges,
    analyze_all_bets, check_moneyline_edge, check_total_edge,
    check_h1_ml_edge, check_h1_total_edge,
)


def test_kelly_criterion_positive_edge():
    kelly = kelly_criterion(0.55, 2.0)
    assert 0.05 < kelly < 0.15


def test_kelly_criterion_no_edge():
    kelly = kelly_criterion(0.50, 2.0)
    assert kelly == 0


def test_kelly_criterion_negative_edge():
    kelly = kelly_criterion(0.40, 2.0)
    assert kelly == 0


def test_american_to_decimal():
    assert american_to_decimal(-150) == round(100 / 150 + 1, 4)
    assert american_to_decimal(130) == round(130 / 100 + 1, 4)
    assert american_to_decimal(100) == 2.0


def test_check_moneyline_edge_found():
    sim = {
        "predictions": {
            "moneyline": {
                "home_win_prob": 0.72,
                "away_win_prob": 0.28,
            }
        }
    }
    odds = {
        "moneyline": {"home": -130, "away": 110},
        "implied_probs": {"ml_home": 0.565, "ml_away": 0.435},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is not None
    assert result["side"] == "home"
    assert result["edge"] > 0.10


def test_check_moneyline_edge_none():
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.56, "away_win_prob": 0.44}
        }
    }
    odds = {
        "moneyline": {"home": -150, "away": 130},
        "implied_probs": {"ml_home": 0.585, "ml_away": 0.415},
    }
    result = check_moneyline_edge(sim, odds)
    if result:
        assert result["edge"] >= 0.05


def test_analyze_all_edges_returns_list():
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.65, "away_win_prob": 0.35},
            "spread": {"favorite_cover_prob": 0.45},
            "total": {"over_prob": 0.60, "under_prob": 0.40, "projected_total": 145.0},
            "first_half": {
                "h1_home_win_prob": 0.58, "h1_away_win_prob": 0.42,
                "h1_projected_total": 70.0,
            },
        }
    }
    odds = {
        "moneyline": {"home": -140, "away": 120},
        "spread": {"home": -6.5, "home_odds": -110, "away": 6.5, "away_odds": -110},
        "total": {"line": 142.5, "over_odds": -110, "under_odds": -110},
        "h1_moneyline": {"home": -130, "away": 110},
        "h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"ml_home": 0.583, "ml_away": 0.417},
    }
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    for bet in bets:
        assert "bet_type" in bet
        assert "edge" in bet
        assert "kelly_pct" in bet


def test_check_h1_ml_edge_found():
    sim = {
        "predictions": {
            "first_half": {"h1_home_win_prob": 0.62, "h1_away_win_prob": 0.38}
        }
    }
    odds = {
        "h1_moneyline": {"home": -130, "away": 110},
        "implied_probs": {"ml_home": 0.565, "ml_away": 0.435},
    }
    result = check_h1_ml_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "first_half_ml"


def test_check_h1_total_edge_runs():
    sim = {"predictions": {"first_half": {"h1_projected_total": 72.0}}}
    odds = {"h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110}}
    result = check_h1_total_edge(sim, odds)
    assert result is None or result["bet_type"] == "first_half_total"


def test_analyze_all_edges_returns_up_to_six():
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.70, "away_win_prob": 0.30},
            "spread": {"favorite_cover_prob": 0.55},
            "total": {"over_prob": 0.65, "under_prob": 0.35, "projected_total": 150.0},
            "first_half": {"h1_home_win_prob": 0.65, "h1_away_win_prob": 0.35, "h1_projected_total": 75.0},
        }
    }
    odds = {
        "moneyline": {"home": -140, "away": 120},
        "spread": {"home": -6.5, "home_odds": -110, "away": 6.5, "away_odds": -110},
        "total": {"line": 142.5, "over_odds": -110, "under_odds": -110},
        "h1_moneyline": {"home": -130, "away": 110},
        "h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"ml_home": 0.583, "ml_away": 0.417},
    }
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    assert len(bets) <= 6
    bet_types = [b["bet_type"] for b in bets]
    assert len(bet_types) == len(set(bet_types))


def test_analyze_all_bets_returns_all_types():
    """analyze_all_bets always returns all 6 bet types regardless of edge."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.56, "away_win_prob": 0.44},
            "spread": {"favorite_cover_prob": 0.52},
            "total": {"over_prob": 0.51, "under_prob": 0.49, "projected_total": 140.0},
            "first_half": {
                "h1_home_win_prob": 0.53, "h1_away_win_prob": 0.47,
                "h1_favorite_cover_prob": 0.51,
                "h1_projected_total": 68.0,
            },
        }
    }
    odds = {
        "moneyline": {"home": -140, "away": 120},
        "spread": {"home": -6.5, "home_odds": -110, "away": 6.5, "away_odds": -110},
        "total": {"line": 142.5, "over_odds": -110, "under_odds": -110},
        "h1_moneyline": {"home": -130, "away": 110},
        "h1_spread": {"home": -3.5, "home_odds": -110, "away": 3.5, "away_odds": -110},
        "h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"ml_home": 0.583, "ml_away": 0.417},
    }
    all_bets = analyze_all_bets(sim, odds)
    assert len(all_bets) == 6
    types = {b["bet_type"] for b in all_bets}
    assert types == {"moneyline", "spread", "total", "first_half_ml",
                     "first_half_spread", "first_half_total"}
    for b in all_bets:
        assert "has_edge" in b
        assert "sim_prob" in b
        assert "edge" in b
        assert "kelly_pct" in b


def test_analyze_all_bets_has_edge_flag():
    """has_edge flag correctly identifies bets above threshold."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.70, "away_win_prob": 0.30},
            "spread": {"favorite_cover_prob": 0.52},
            "total": {"over_prob": 0.51, "under_prob": 0.49},
            "first_half": {
                "h1_home_win_prob": 0.53, "h1_away_win_prob": 0.47,
                "h1_favorite_cover_prob": 0.51,
                "h1_projected_total": 68.0,
            },
        }
    }
    odds = {
        "moneyline": {"home": -140, "away": 120},
        "spread": {"home": -6.5, "home_odds": -110, "away": 6.5, "away_odds": -110},
        "total": {"line": 142.5, "over_odds": -110, "under_odds": -110},
        "h1_moneyline": {"home": -130, "away": 110},
        "h1_spread": {"home": -3.5, "home_odds": -110, "away": 3.5, "away_odds": -110},
        "h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"ml_home": 0.583, "ml_away": 0.417},
    }
    all_bets = analyze_all_bets(sim, odds)
    ml_bet = [b for b in all_bets if b["bet_type"] == "moneyline"][0]
    # home_prob=0.70 vs market=0.583 → edge=0.117 → should have edge
    assert ml_bet["has_edge"] is True


def test_moneyline_rejects_heavy_underdog():
    """Moneyline bets on heavy underdogs (+400 or worse) should be rejected."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.25, "away_win_prob": 0.75}
        }
    }
    odds = {
        "moneyline": {"home": 500, "away": -700},
        "implied_probs": {"ml_home": 0.167, "ml_away": 0.833},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is None


def test_moneyline_allows_moderate_underdog():
    """Moderate underdogs (+180) should still be allowed if edge exists."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.50, "away_win_prob": 0.50}
        }
    }
    odds = {
        "moneyline": {"home": 180, "away": -220},
        "implied_probs": {"ml_home": 0.357, "ml_away": 0.643},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is not None
    assert result["side"] == "home"


def test_h1_total_uses_ensemble_probs():
    """H1 total should use ensemble over/under probs, not hardcoded heuristic."""
    sim = {
        "predictions": {
            "first_half": {
                "h1_projected_total": 72.0,
                "h1_over_prob": 0.62,
                "h1_under_prob": 0.38,
            }
        }
    }
    odds = {"h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110}}
    result = check_h1_total_edge(sim, odds)
    if result:
        assert result["sim_prob"] == 0.62 or result["sim_prob"] == 0.38


def test_h1_total_falls_back_to_heuristic():
    """When ensemble doesn't provide H1 probs, fall back to heuristic."""
    sim = {
        "predictions": {
            "first_half": {"h1_projected_total": 72.0}
        }
    }
    odds = {"h1_total": {"line": 68.5, "over_odds": -110, "under_odds": -110}}
    result = check_h1_total_edge(sim, odds)
    assert result is None or result["bet_type"] == "first_half_total"


from edge import dampen_probability


def test_dampen_no_change_for_favorites():
    """Favorites (prob > 0.5) should not be dampened."""
    result = dampen_probability(0.60, 0.55)
    assert result == 0.60


def test_dampen_pulls_underdog_toward_market():
    """Underdogs should be pulled toward market implied prob."""
    result = dampen_probability(0.25, 0.167)
    assert result < 0.25
    assert result > 0.167


def test_dampen_stronger_for_extreme_underdogs():
    """More extreme underdogs get more dampening."""
    mild = dampen_probability(0.35, 0.30)   # mild underdog
    extreme = dampen_probability(0.25, 0.10)  # extreme underdog
    mild_kept = (mild - 0.30) / (0.35 - 0.30)
    extreme_kept = (extreme - 0.10) / (0.25 - 0.10)
    assert mild_kept > extreme_kept
