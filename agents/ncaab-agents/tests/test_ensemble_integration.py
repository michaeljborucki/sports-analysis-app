import copy
from unittest.mock import patch, MagicMock
from simulate import run_mirofish
from tests.ensemble_fixtures import MOCK_PREDICTION

@patch("ensemble.run_ensemble")
def test_run_mirofish_uses_ensemble(mock_ensemble):
    ensemble_result = copy.deepcopy(MOCK_PREDICTION)
    ensemble_result["ensemble_meta"] = {"phase_reached": 3, "total_calls": 7, "cost_usd": 0.10}
    ensemble_result["ensemble_runs"] = 1
    mock_ensemble.return_value = ensemble_result
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
