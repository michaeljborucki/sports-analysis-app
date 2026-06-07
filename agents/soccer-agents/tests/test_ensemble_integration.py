import copy
from unittest.mock import patch, MagicMock
from simulate import run_mirofish
from tests.ensemble_fixtures import MOCK_PREDICTION

PANEL_MODELS = [
    ("kimi", {"id": "m1", "default_temp": 0.7, "max_tokens": 12288, "timeout": 45, "input_price": 0.45, "output_price": 2.25}),
    ("claude", {"id": "m2", "default_temp": 0.7, "max_tokens": 12288, "timeout": 45, "input_price": 3.0, "output_price": 15.0}),
    ("gpt4o", {"id": "m3", "default_temp": 0.7, "max_tokens": 12288, "timeout": 45, "input_price": 2.5, "output_price": 10.0}),
    ("gemini", {"id": "m4", "default_temp": 0.7, "max_tokens": 12288, "timeout": 30, "input_price": 0.3, "output_price": 2.5}),
    ("deepseek", {"id": "m5", "default_temp": 0.7, "max_tokens": 12288, "timeout": 90, "input_price": 0.7, "output_price": 2.5}),
    ("maverick", {"id": "m6", "default_temp": 0.7, "max_tokens": 12288, "timeout": 30, "input_price": 0.15, "output_price": 0.6}),
]


def _mock_runner(model_key, model_id, briefing, temperature,
                 max_tokens, timeout, input_price, output_price,
                 system_prompt=None):
    return {
        "model_key": model_key,
        "parsed": copy.deepcopy(MOCK_PREDICTION),
        "temperature": temperature,
        "cost": 0.01,
    }


@patch("ensemble.orchestrator.log_model_prediction")
@patch("ensemble.orchestrator.run_challenge", return_value=({"asian_handicap": "approve", "total": "approve", "btts": "approve"}, 0.05))
@patch("ensemble.orchestrator.get_panel_models", return_value=PANEL_MODELS)
@patch("ensemble.orchestrator.run_single_model", side_effect=_mock_runner)
def test_run_mirofish_uses_ensemble(mock_runner, mock_models, mock_challenge, mock_log):
    result = run_mirofish("test briefing")
    assert result is not None
    assert "predictions" in result


@patch("ensemble.run_ensemble", return_value=None)
@patch("simulate.run_plan_b")
def test_run_mirofish_falls_back_to_plan_b(mock_plan_b, mock_ensemble):
    mock_plan_b.return_value = copy.deepcopy(MOCK_PREDICTION)
    result = run_mirofish("test briefing")
    assert result is not None
    mock_plan_b.assert_called_once()

@patch("ensemble.run_ensemble", side_effect=Exception("boom"))
@patch("simulate.run_plan_b")
def test_run_mirofish_catches_ensemble_exception(mock_plan_b, mock_ensemble):
    mock_plan_b.return_value = copy.deepcopy(MOCK_PREDICTION)
    result = run_mirofish("test briefing")
    assert result is not None
    mock_plan_b.assert_called_once()
