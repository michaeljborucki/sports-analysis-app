"""Tests for ensemble orchestrator — adaptive 3-phase ensemble."""
import copy
from unittest.mock import patch, MagicMock
from tests.ensemble_fixtures import (
    MOCK_PREDICTION, MOCK_ODDS, MOCK_GAME_CONFIG, make_prediction,
)


BET_SLOTS = MOCK_GAME_CONFIG.config.BET_SLOTS
BET_SLOT_FIELDS = MOCK_GAME_CONFIG.config.BET_SLOT_FIELDS


def _make_run_result(model_key, prediction=None, temperature=0.7, cost=0.001):
    """Helper to build a run result dict."""
    return {
        "model_key": model_key,
        "parsed": prediction or copy.deepcopy(MOCK_PREDICTION),
        "temperature": temperature,
        "cost": cost,
    }


def _mock_run_single_model(model_key, model_id, briefing, temperature,
                           max_tokens, timeout, input_price, output_price,
                           system_prompt=None):
    """Fake runner that returns a result keyed by model_key."""
    return _make_run_result(model_key, temperature=temperature)


PANEL_MODELS = [
    ("kimi", {"id": "m1", "default_temp": 0.7, "max_tokens": 12288, "timeout": 45, "input_price": 0.45, "output_price": 2.25}),
    ("claude", {"id": "m2", "default_temp": 0.7, "max_tokens": 12288, "timeout": 45, "input_price": 3.0, "output_price": 15.0}),
    ("gpt4o", {"id": "m3", "default_temp": 0.7, "max_tokens": 12288, "timeout": 45, "input_price": 2.5, "output_price": 10.0}),
    ("gemini", {"id": "m4", "default_temp": 0.7, "max_tokens": 12288, "timeout": 30, "input_price": 0.3, "output_price": 2.5}),
    ("deepseek", {"id": "m5", "default_temp": 0.7, "max_tokens": 12288, "timeout": 90, "input_price": 0.7, "output_price": 2.5}),
    ("maverick", {"id": "m6", "default_temp": 0.7, "max_tokens": 12288, "timeout": 30, "input_price": 0.15, "output_price": 0.6}),
]


@patch("ensemble.orchestrator.get_panel_models", return_value=PANEL_MODELS)
@patch("ensemble.orchestrator.run_single_model", side_effect=_mock_run_single_model)
def test_run_phase1_returns_results(mock_runner, mock_models):
    from ensemble.orchestrator import run_phase1
    results, cost = run_phase1("test briefing")
    assert len(results) == 6
    assert all(r["model_key"] in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"] for r in results)
    assert cost > 0


def test_classify_consensus_strong():
    """All 6 models agree on team_a for moneyline -> strong."""
    from ensemble.orchestrator import classify_consensus
    results = [_make_run_result(m) for m in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]]
    classification = classify_consensus(results, MOCK_ODDS,
                                        bet_slots=BET_SLOTS,
                                        bet_slot_fields=BET_SLOT_FIELDS)
    # All predict team_a for moneyline, so should be strong (6 agree >= 5)
    assert classification["moneyline"]["level"] == "strong"


def test_classify_consensus_no_consensus():
    """2v2 split with 2 None -> none."""
    from ensemble.orchestrator import classify_consensus

    team_a_pred = make_prediction(moneyline={"value_side": "team_a"})
    team_b_pred = make_prediction(moneyline={"value_side": "team_b"})
    none_pred = make_prediction(moneyline={"value_side": "none"})

    results = [
        _make_run_result("kimi", team_a_pred),
        _make_run_result("claude", team_b_pred),
        _make_run_result("gpt4o", team_a_pred),
        _make_run_result("gemini", team_b_pred),
        _make_run_result("deepseek", none_pred),
        _make_run_result("maverick", none_pred),
    ]
    classification = classify_consensus(results, MOCK_ODDS,
                                        bet_slots=BET_SLOTS,
                                        bet_slot_fields=BET_SLOT_FIELDS)
    assert classification["moneyline"]["level"] == "none"


def test_reclassify_consensus_uses_majority_of_runs():
    """Model with 1 team_a + 2 team_b votes -> team_b majority."""
    from ensemble.orchestrator import reclassify_consensus

    team_a_pred = make_prediction(moneyline={"value_side": "team_a"})
    team_b_pred = make_prediction(moneyline={"value_side": "team_b"})

    # kimi: 1 team_a + 2 team_b -> majority = team_b
    # rest: all team_a
    results = [
        _make_run_result("kimi", team_a_pred),
        _make_run_result("kimi", team_b_pred),
        _make_run_result("kimi", team_b_pred),
        _make_run_result("claude", team_a_pred),
        _make_run_result("gpt4o", team_a_pred),
        _make_run_result("gemini", team_a_pred),
        _make_run_result("deepseek", team_a_pred),
        _make_run_result("maverick", team_a_pred),
    ]
    classification = reclassify_consensus(results, MOCK_ODDS,
                                          bet_slots=BET_SLOTS,
                                          bet_slot_fields=BET_SLOT_FIELDS)
    # 5 team_a (claude, gpt4o, gemini, deepseek, maverick) + 1 team_b (kimi) = strong
    assert classification["moneyline"]["level"] == "strong"
    assert classification["moneyline"]["count"] == 5


@patch("ensemble.orchestrator.log_model_prediction")
@patch("ensemble.orchestrator.run_challenge", return_value=({slot: "approve" for slot in ["moneyline", "map_handicap", "total_maps"]}, 0.01))
@patch("ensemble.orchestrator.get_panel_models", return_value=PANEL_MODELS)
@patch("ensemble.orchestrator.run_single_model", side_effect=_mock_run_single_model)
def test_run_ensemble_returns_predictions(mock_runner, mock_models, mock_challenge, mock_log):
    from ensemble.orchestrator import run_ensemble
    result = run_ensemble("test briefing", odds=MOCK_ODDS, game_config=MOCK_GAME_CONFIG)
    assert result is not None
    assert "predictions" in result
    assert "ensemble_meta" in result
    assert result["ensemble_meta"]["phase_reached"] >= 1
    assert result.get("ensemble_runs") == 1


@patch("ensemble.orchestrator.get_panel_models", return_value=PANEL_MODELS[:2])
@patch("ensemble.orchestrator.run_single_model", return_value=None)
def test_run_ensemble_fewer_than_3_models_returns_none(mock_runner, mock_models):
    from ensemble.orchestrator import run_ensemble
    result = run_ensemble("test briefing", odds=MOCK_ODDS, game_config=MOCK_GAME_CONFIG)
    assert result is None


def test_run_ensemble_requires_game_config():
    """run_ensemble should raise ValueError without game_config."""
    from ensemble.orchestrator import run_ensemble
    import pytest
    with pytest.raises(ValueError, match="game_config"):
        run_ensemble("test briefing", odds=MOCK_ODDS)


def test_build_ensemble_result_majority_vote_predicted_result():
    """predicted_result should use majority vote across models."""
    from ensemble.orchestrator import build_ensemble_result

    gc = MOCK_GAME_CONFIG.config

    navi_pred = make_prediction(predicted_result={"winner": "NAVI", "score": "2-1"})
    faze_pred = make_prediction(predicted_result={"winner": "FaZe", "score": "2-0"})

    results = [
        _make_run_result("kimi", navi_pred),
        _make_run_result("claude", navi_pred),
        _make_run_result("gpt4o", navi_pred),
        _make_run_result("gemini", faze_pred),
        _make_run_result("deepseek", navi_pred),
        _make_run_result("maverick", faze_pred),
    ]
    classification = {
        slot: {"level": "strong", "count": 6, "side": "team_a", "votes": {}}
        for slot in BET_SLOTS
    }
    weights = {mk: {s: 1.0 for s in BET_SLOTS} for mk in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]}

    final = build_ensemble_result(results, classification, weights, [],
                                  bet_slots=gc.BET_SLOTS,
                                  prob_fields=gc.PROB_FIELDS,
                                  slot_section=gc.SLOT_SECTION)
    assert final is not None
    pr = final["predictions"]["predicted_result"]
    assert pr["winner"] == "NAVI"  # 4 out of 6
    assert pr["score"] == "2-1"   # 4 out of 6
