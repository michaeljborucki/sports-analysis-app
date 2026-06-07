"""Tests for ensemble orchestrator — adaptive 3-phase ensemble."""
import copy
from unittest.mock import patch, MagicMock
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS, make_prediction
from ensemble.weights import BET_SLOTS


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
    """All 6 models agree on player_a for moneyline → strong."""
    from ensemble.orchestrator import classify_consensus
    results = [_make_run_result(m) for m in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]]
    classification = classify_consensus(results, MOCK_ODDS)
    # All predict home for moneyline, so should be strong (6 agree >= 5)
    assert classification["moneyline"]["level"] == "strong"


def test_classify_consensus_no_consensus():
    """2v2 split with 2 None → none."""
    from ensemble.orchestrator import classify_consensus

    home_pred = make_prediction(moneyline={"value_side": "player_a"})
    away_pred = make_prediction(moneyline={"value_side": "player_b"})
    none_pred = make_prediction(moneyline={"value_side": "none"})

    results = [
        _make_run_result("kimi", home_pred),
        _make_run_result("claude", away_pred),
        _make_run_result("gpt4o", home_pred),
        _make_run_result("gemini", away_pred),
        _make_run_result("deepseek", none_pred),
        _make_run_result("maverick", none_pred),
    ]
    classification = classify_consensus(results, MOCK_ODDS)
    assert classification["moneyline"]["level"] == "none"


def test_reclassify_consensus_uses_majority_of_runs():
    """Model with 1 home + 2 away votes → away majority."""
    from ensemble.orchestrator import reclassify_consensus

    home_pred = make_prediction(moneyline={"value_side": "player_a"})
    away_pred = make_prediction(moneyline={"value_side": "player_b"})

    # kimi: 1 home + 2 away → majority = away
    # rest: all home
    results = [
        _make_run_result("kimi", home_pred),
        _make_run_result("kimi", away_pred),
        _make_run_result("kimi", away_pred),
        _make_run_result("claude", home_pred),
        _make_run_result("gpt4o", home_pred),
        _make_run_result("gemini", home_pred),
        _make_run_result("deepseek", home_pred),
        _make_run_result("maverick", home_pred),
    ]
    classification = reclassify_consensus(results, MOCK_ODDS)
    # 5 player_a (claude, gpt4o, gemini, deepseek, maverick) + 1 player_b (kimi) = strong
    assert classification["moneyline"]["level"] == "strong"
    assert classification["moneyline"]["count"] == 5


@patch("ensemble.orchestrator.log_model_prediction")
@patch("ensemble.orchestrator.run_challenge", return_value=({slot: "approve" for slot in BET_SLOTS}, 0.01))
@patch("ensemble.orchestrator.get_panel_models", return_value=PANEL_MODELS)
@patch("ensemble.orchestrator.run_single_model", side_effect=_mock_run_single_model)
def test_run_ensemble_returns_predictions(mock_runner, mock_models, mock_challenge, mock_log):
    from ensemble.orchestrator import run_ensemble
    result = run_ensemble("test briefing", odds=MOCK_ODDS)
    assert result is not None
    assert "predictions" in result
    assert "ensemble_meta" in result
    assert result["ensemble_meta"]["phase_reached"] >= 1
    assert result.get("ensemble_runs") == 1


@patch("ensemble.orchestrator.get_panel_models", return_value=PANEL_MODELS[:2])
@patch("ensemble.orchestrator.run_single_model", return_value=None)
def test_run_ensemble_fewer_than_3_models_returns_none(mock_runner, mock_models):
    from ensemble.orchestrator import run_ensemble
    result = run_ensemble("test briefing", odds=MOCK_ODDS)
    assert result is None
