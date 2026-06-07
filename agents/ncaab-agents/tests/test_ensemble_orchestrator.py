"""Tests for ensemble orchestrator — adaptive 3-phase ensemble."""
import copy
from unittest.mock import patch, MagicMock
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS, make_prediction
from ensemble.weights import BET_SLOTS
import copy as copy_module


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
    """All 6 models agree on home for moneyline → strong."""
    from ensemble.orchestrator import classify_consensus
    results = [_make_run_result(m) for m in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]]
    classification = classify_consensus(results, MOCK_ODDS)
    # All predict home for moneyline, so should be strong (6 agree >= 5)
    assert classification["moneyline"]["level"] == "strong"


def test_classify_consensus_no_consensus():
    """2v2 split with 2 None → none."""
    from ensemble.orchestrator import classify_consensus

    home_pred = make_prediction(moneyline={"value_side": "home"})
    away_pred = make_prediction(moneyline={"value_side": "away"})
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

    home_pred = make_prediction(moneyline={"value_side": "home"})
    away_pred = make_prediction(moneyline={"value_side": "away"})

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
    # 5 home (claude, gpt4o, gemini, deepseek, maverick) + 1 away (kimi) = strong
    assert classification["moneyline"]["level"] == "strong"
    assert classification["moneyline"]["count"] == 5


@patch("ensemble.orchestrator.log_model_prediction")
@patch("ensemble.orchestrator.run_challenge", return_value=(
    {slot: {"verdict": "approve", "reasoning": "", "flaw_found": None} for slot in BET_SLOTS}, 0.01))
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


def test_ensemble_result_probabilities_sum_to_one():
    """After weighted averaging, ML probs should sum to ~1.0."""
    from ensemble.orchestrator import build_ensemble_result
    from ensemble.weights import BET_SLOTS
    from tests.ensemble_fixtures import MOCK_PREDICTION

    pred1 = copy_module.deepcopy(MOCK_PREDICTION)
    pred1["predictions"]["moneyline"]["home_win_prob"] = 0.62
    pred1["predictions"]["moneyline"]["away_win_prob"] = 0.40
    pred2 = copy_module.deepcopy(MOCK_PREDICTION)
    pred2["predictions"]["moneyline"]["home_win_prob"] = 0.58
    pred2["predictions"]["moneyline"]["away_win_prob"] = 0.44

    results = [
        {"model_key": "kimi", "parsed": pred1, "temperature": 0.7, "cost": 0.01},
        {"model_key": "claude", "parsed": pred2, "temperature": 0.7, "cost": 0.01},
        {"model_key": "gpt4o", "parsed": pred1, "temperature": 0.7, "cost": 0.01},
    ]
    classification = {s: {"level": "strong", "count": 3, "side": "home", "votes": {}}
                      for s in BET_SLOTS}
    weights = {mk: {s: 1.0 for s in BET_SLOTS} for mk in ["kimi", "claude", "gpt4o"]}

    final = build_ensemble_result(results, classification, weights, [])
    ml = final["predictions"]["moneyline"]
    total = ml["home_win_prob"] + ml["away_win_prob"]
    assert abs(total - 1.0) < 0.01, f"ML probs sum to {total}, expected ~1.0"


def test_detect_shared_bias_downgrades_strong_total():
    """Unanimous total with high deviation from market should downgrade to soft."""
    from ensemble.orchestrator import detect_shared_bias

    # All 6 models predict over with 0.70 probability (market is ~0.50)
    over_pred = make_prediction(total={"over_prob": 0.70, "under_prob": 0.30, "value_side": "over"})
    results = [_make_run_result(m, over_pred) for m in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]]

    classification = {
        slot: {"level": "strong", "count": 6, "side": "home", "votes": {}}
        for slot in BET_SLOTS
    }
    classification["total"]["side"] = "over"

    classification = detect_shared_bias(classification, results, MOCK_ODDS)
    # Total should be downgraded because avg_prob=0.70 deviates >8% from market ~0.50
    assert classification["total"]["level"] == "soft"
    # Spread should remain strong (no bias check on spreads)
    assert classification["spread"]["level"] == "strong"


def test_detect_shared_bias_keeps_strong_when_no_deviation():
    """Unanimous total near market probability should remain strong."""
    from ensemble.orchestrator import detect_shared_bias

    # All 6 models predict over with 0.53 probability (close to market ~0.50)
    pred = make_prediction(total={"over_prob": 0.53, "under_prob": 0.47, "value_side": "over"})
    results = [_make_run_result(m, pred) for m in ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]]

    classification = {
        slot: {"level": "strong", "count": 6, "side": "home", "votes": {}}
        for slot in BET_SLOTS
    }
    classification["total"]["side"] = "over"

    classification = detect_shared_bias(classification, results, MOCK_ODDS)
    # 0.53 vs ~0.50 = 3% deviation, well below 8% threshold
    assert classification["total"]["level"] == "strong"
