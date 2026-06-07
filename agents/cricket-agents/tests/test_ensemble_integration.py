import copy
from unittest.mock import patch, MagicMock
from simulate import run_mirofish
from tests.ensemble_fixtures import MOCK_PREDICTION

MOCK_ENSEMBLE_RESULT = {
    "predictions": copy.deepcopy(MOCK_PREDICTION["predictions"]),
    "ensemble_meta": {"phase_reached": 1, "total_calls": 6, "cost_usd": 0.06},
    "ensemble_runs": 1,
}

@patch("ensemble.run_ensemble", return_value=MOCK_ENSEMBLE_RESULT)
def test_run_mirofish_uses_ensemble(mock_ensemble):
    result = run_mirofish("test briefing")
    assert result is not None
    assert "predictions" in result
    mock_ensemble.assert_called_once()

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
