"""Regression tests pinning ensemble abstain behavior.

Background: when the ensemble legitimately decides not to bet (no consensus
across slots, or challenger kills every surviving slot), it used to return
``None``. That tripped ``simulate.run_mirofish``'s Plan B fallback path,
which wasted an extra LLM call per match and sometimes failed entirely.

Fix (2026-04-21): return a structured empty result with
``ensemble_meta.abstained = True``. ``edge.analyze_all_edges`` sees the
empty predictions dict and returns zero bets — which is correct —
without triggering the expensive fallback.

These tests pin that contract so it doesn't regress.
"""
from ensemble.orchestrator import _abstain_result


def test_abstain_result_has_expected_shape():
    r = _abstain_result("no_consensus")
    # Shape that downstream (edge.analyze_all_edges, simulate.run_mirofish) depends on
    assert r["predictions"] == {}
    assert r["analyst_assessments"] == []
    assert r["ensemble_runs"] == 1
    assert "ensemble_meta" in r


def test_abstain_result_flags_abstained_in_meta():
    r = _abstain_result("no_consensus")
    assert r["ensemble_meta"]["abstained"] is True
    assert r["ensemble_meta"]["abstain_reason"] == "no_consensus"


def test_abstain_result_is_truthy_so_run_mirofish_does_not_fall_back():
    """The key contract: simulate.run_mirofish uses ``if result:`` to decide
    whether to fall back to Plan B. Abstain results must be truthy.
    """
    r = _abstain_result("challenger_killed_all")
    assert bool(r) is True


def test_abstain_result_carries_diagnostic_meta():
    meta = {"phase_reached": 3, "total_calls": 12, "killed": ["moneyline"]}
    r = _abstain_result("challenger_killed_all", meta)
    assert r["ensemble_meta"]["phase_reached"] == 3
    assert r["ensemble_meta"]["total_calls"] == 12
    assert r["ensemble_meta"]["killed"] == ["moneyline"]
    assert r["ensemble_meta"]["abstained"] is True


def test_abstain_result_with_empty_predictions_produces_zero_bets():
    """edge.analyze_all_edges should return an empty list when given an
    abstained ensemble result — no crashes, no partial bets.
    """
    from edge import analyze_all_edges, apply_bet_filters

    r = _abstain_result("no_consensus")
    # Use realistic odds so the checkers don't short-circuit on missing odds
    odds = {
        "moneyline": {"player_a": -130, "player_b": 110},
        "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110,
                          "player_b_point": 3.5, "player_b_odds": -110},
        "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"player_a": 0.565, "player_b": 0.435},
    }
    bets = analyze_all_edges(r, odds, tour="atp")
    assert bets == []
    assert apply_bet_filters(bets) == []
