"""Regression tests pinning the Option B individual-model-conviction fallback.

Added 2026-04-24 to fix the 0-bet pattern under median-of-medians aggregation.
When ≥4 of 6 models agree on a side AND each has per-model edge ≥ 3%, but
median-of-medians produces no primary bet, a conviction fallback surfaces a
down-sized bet flagged with ``source="individual_conviction"``.

If these tests fail, carefully diff: the fallback should NEVER fire when the
primary edge check already produced a bet.
"""
from edge import (
    analyze_all_edges,
    check_moneyline_conviction,
    check_game_handicap_conviction,
    check_total_games_conviction,
)


# ----- Scenario A: 4 of 6 models agree with ≥3% per-model edge; primary fails
# Market implies player_a = 0.50. 4 models see player_a at 0.54-0.58 (all
# beat market by ≥4%). 2 dissent at 0.20 / 0.15 (deeply confident player_b).
# Sorted medians: [0.15, 0.20, 0.54, 0.55, 0.57, 0.58] → median = 0.545.
# Edge = 0.045 — at 1% threshold primary WOULD fire. To exercise the
# fallback we need the primary to NOT produce a bet, which means market
# implied must sit close to that aggregated median. So we set implied = 0.545
# and confirm primary = None while conviction fallback surfaces a bet from
# the 4 agreeing models.
def _ml_sim_with_per_model(per_model_a_probs: dict, confidence: str = "medium") -> dict:
    """Build a sim dict containing the _per_model_medians payload."""
    # Take the median of the per-model probs as the aggregated value, mirroring
    # what orchestrator.build_ensemble_result does.
    import statistics
    agg = statistics.median(per_model_a_probs.values())
    return {
        "predictions": {
            "moneyline": {
                "player_a_win_prob": round(agg, 4),
                "player_b_win_prob": round(1 - agg, 4),
                "confidence": confidence,
                "_per_model_medians": {
                    "player_a_win_prob": per_model_a_probs,
                },
            },
        }
    }


def test_conviction_fires_when_four_models_agree_with_per_model_edge():
    """Four of six models individually see ≥3% edge on player_a. Fallback
    returns a well-formed bet when invoked directly.

    Note: at the current 1% primary threshold, the primary edge check almost
    always fires too — so ``analyze_all_edges`` will prefer primary. We test
    the fallback function directly to exercise its logic in isolation.
    """
    sim = _ml_sim_with_per_model({
        "kimi":     0.58,
        "claude":   0.57,
        "gpt4o":    0.56,
        "gemini":   0.55,
        "deepseek": 0.20,
        "maverick": 0.15,
    })
    odds = {
        "moneyline": {"player_a": 100, "player_b": -120},
        "implied_probs": {"player_a": 0.50, "player_b": 0.50},
    }
    bet = check_moneyline_conviction(sim, odds, tour="atp")
    assert bet is not None
    assert bet["bet_type"] == "moneyline"
    assert bet["side"] == "player_a"
    assert bet.get("source") == "individual_conviction"
    assert bet["conviction_models"] == 4
    assert bet["kelly_pct"] > 0


def test_conviction_does_not_fire_when_primary_succeeds():
    """If primary edge check produces a bet, fallback must NOT double-count."""
    sim = _ml_sim_with_per_model({
        "kimi": 0.70, "claude": 0.70, "gpt4o": 0.70, "gemini": 0.70,
        "deepseek": 0.30, "maverick": 0.30,
    })
    odds = {
        "moneyline": {"player_a": -110, "player_b": -110},
        "implied_probs": {"player_a": 0.524, "player_b": 0.476},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    ml = [b for b in bets if b["bet_type"] == "moneyline"]
    assert len(ml) == 1
    # Source flag must be absent (or at least not "individual_conviction")
    assert ml[0].get("source") != "individual_conviction"


def test_conviction_does_not_fire_below_min_models():
    """Only 3 of 6 agree with ≥3% edge — below CONVICTION_MIN_MODELS=4."""
    sim = _ml_sim_with_per_model({
        "kimi": 0.60, "claude": 0.58, "gpt4o": 0.56,  # 3 agree
        "gemini": 0.50, "deepseek": 0.48, "maverick": 0.45,  # 3 don't
    })
    # Market = aggregated median (~0.53) so primary doesn't fire either.
    odds = {
        "moneyline": {"player_a": -120, "player_b": 100},
        "implied_probs": {"player_a": 0.53, "player_b": 0.47},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert bets == []


def test_conviction_does_not_fire_when_per_model_edges_too_small():
    """4 models agree on direction but each has <3% per-model edge."""
    sim = _ml_sim_with_per_model({
        "kimi": 0.52, "claude": 0.51, "gpt4o": 0.52, "gemini": 0.515,  # 4 but tiny
        "deepseek": 0.45, "maverick": 0.40,
    })
    odds = {
        "moneyline": {"player_a": 100, "player_b": -120},
        "implied_probs": {"player_a": 0.50, "player_b": 0.50},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    # Primary might fire at 1% threshold (median ~0.51 vs 0.50 = 1%). In
    # that case source != individual_conviction. If primary doesn't fire,
    # fallback won't either because per-model edges are all ≤2%.
    for b in bets:
        assert b.get("source") != "individual_conviction"


def test_conviction_prefers_side_with_more_agreeing_models():
    """3 models see A-edge, 4 see B-edge — fallback picks B side."""
    sim = _ml_sim_with_per_model({
        "kimi": 0.62, "claude": 0.58, "gpt4o": 0.57,  # 3 say A
        "gemini": 0.30, "deepseek": 0.28, "maverick": 0.25, "claude2": 0.30,  # 4 say B
    })
    odds = {
        "moneyline": {"player_a": -110, "player_b": -110},
        "implied_probs": {"player_a": 0.50, "player_b": 0.50},
    }
    bet = check_moneyline_conviction(sim, odds, tour="atp")
    assert bet is not None
    assert bet["side"] == "player_b"
    assert bet.get("source") == "individual_conviction"
    assert bet["conviction_models"] == 4


def test_conviction_kelly_halved_vs_primary():
    """Conviction bets are sized with CONVICTION_KELLY_MULT=0.5 on top of
    the normal confidence multiplier, reflecting weaker signal quality.

    Build comparable scenarios where primary and conviction produce bets with
    the same sim_prob vs the same market, then assert conviction Kelly is
    meaningfully smaller.
    """
    from edge import check_moneyline_edge
    sim_primary = {
        "predictions": {
            "moneyline": {
                "player_a_win_prob": 0.58, "player_b_win_prob": 0.42,
                "confidence": "medium",
            }
        }
    }
    sim_conv = _ml_sim_with_per_model({
        "kimi": 0.58, "claude": 0.58, "gpt4o": 0.58, "gemini": 0.58,  # 4 all at 0.58
        "deepseek": 0.20, "maverick": 0.15,
    })
    odds = {
        "moneyline": {"player_a": -110, "player_b": -110},
        "implied_probs": {"player_a": 0.50, "player_b": 0.50},
    }
    prim = check_moneyline_edge(sim_primary, odds, tour="atp")
    conv = check_moneyline_conviction(sim_conv, odds, tour="atp")
    assert prim and conv
    # Same sim_prob (0.58), same market (0.50), same edge (0.08) → the only
    # difference is CONVICTION_KELLY_MULT=0.5. Conviction Kelly should be
    # roughly half of primary Kelly.
    assert prim["edge"] == conv["edge"]
    assert prim["sim_prob"] == conv["sim_prob"]
    assert conv["kelly_pct"] < prim["kelly_pct"]
    assert conv["kelly_pct"] / prim["kelly_pct"] < 0.75


def test_conviction_absent_when_per_model_medians_missing():
    """Legacy sim dicts without _per_model_medians must not break — fallback
    returns None gracefully, primary behavior preserved."""
    sim = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.52, "player_b_win_prob": 0.48,
                          "confidence": "medium"}
            # no _per_model_medians key
        }
    }
    odds = {
        "moneyline": {"player_a": 100, "player_b": -120},
        "implied_probs": {"player_a": 0.52, "player_b": 0.48},  # exact match, no primary edge
    }
    # Should not raise, should return empty.
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert bets == []


# ----- Game handicap conviction fallback -----
def test_conviction_fires_for_game_handicap():
    import statistics
    fav_model_probs = {
        "kimi": 0.60, "claude": 0.58, "gpt4o": 0.57, "gemini": 0.56,  # 4 agree ≥4% vs ~0.50
        "deepseek": 0.30, "maverick": 0.25,
    }
    agg = statistics.median(fav_model_probs.values())
    sim = {
        "predictions": {
            "game_handicap": {
                "favorite_cover_prob": round(agg, 4),
                "confidence": "medium",
                "_per_model_medians": {"favorite_cover_prob": fav_model_probs},
            }
        }
    }
    odds = {
        "game_handicap": {
            "player_a_point": -3.5, "player_a_odds": -110,
            "player_b_point": 3.5, "player_b_odds": -110,
        }
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    gh = [b for b in bets if b["bet_type"] == "game_handicap"]
    # Either primary or conviction fires depending on devigged implied. If
    # conviction fires, the flag must be set; if primary fires, it shouldn't.
    assert len(gh) == 1
    # At devigged implied ~0.50 and aggregated 0.57, primary likely fires at
    # 1% threshold. That's fine — we just need to prove the conviction helper
    # works when invoked directly.
    bet = check_game_handicap_conviction(sim, odds, tour="atp")
    assert bet is not None
    assert bet["bet_type"] == "game_handicap"
    assert bet.get("source") == "individual_conviction"
    assert bet["conviction_models"] >= 4


# ----- Total games conviction fallback -----
def test_conviction_fires_for_total_games():
    over_model_probs = {
        "kimi": 0.60, "claude": 0.58, "gpt4o": 0.57, "gemini": 0.55,  # 4 agree
        "deepseek": 0.30, "maverick": 0.28,
    }
    sim = {
        "predictions": {
            "total_games": {
                "over_prob": 0.55, "under_prob": 0.45,
                "projected_games": 22.0, "confidence": "medium",
                "_per_model_medians": {"over_prob": over_model_probs},
            }
        }
    }
    odds = {"total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110}}
    bet = check_total_games_conviction(sim, odds, tour="atp")
    assert bet is not None
    assert bet["bet_type"] == "total_games"
    assert "over" in bet["side"]
    assert bet.get("source") == "individual_conviction"
    assert bet["conviction_models"] >= 4


# ----- Challenger-pollution guard -----
def test_strip_internal_fields_removes_per_model_medians():
    """_strip_internal_fields in challenger.py must remove _per_model_medians
    before predictions are JSON-serialized to Claude. Otherwise the prompt
    bloats and the challenger sees irrelevant Python-side metadata."""
    from ensemble.challenger import _strip_internal_fields
    predictions = {
        "moneyline": {
            "player_a_win_prob": 0.6,
            "_per_model_medians": {"player_a_win_prob": {"kimi": 0.7}},
        },
        "game_handicap": {"favorite_cover_prob": 0.55},
    }
    cleaned = _strip_internal_fields(predictions)
    assert "_per_model_medians" not in cleaned["moneyline"]
    assert cleaned["moneyline"]["player_a_win_prob"] == 0.6
    assert cleaned["game_handicap"]["favorite_cover_prob"] == 0.55
    # Original must not be mutated (function returns a shallow copy).
    assert "_per_model_medians" in predictions["moneyline"]
