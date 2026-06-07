import copy
from unittest.mock import patch, MagicMock
from tests.ensemble_fixtures import MOCK_PREDICTION


@patch("ensemble.orchestrator.run_challenge")
@patch("ensemble.orchestrator.run_single_model")
def test_run_mirofish_uses_ensemble(mock_runner, mock_challenge):
    mock_runner.return_value = {
        "model_key": "kimi",
        "parsed": copy.deepcopy(MOCK_PREDICTION),
        "temperature": 0.7,
        "cost": 0.01,
    }
    mock_challenge.return_value = ({"moneyline": "approve", "total_rounds": "approve", "method": "approve"}, 0.05)
    from simulate import run_mirofish
    result = run_mirofish("test briefing")
    assert result is not None
    assert "predictions" in result


@patch("ensemble.orchestrator.run_ensemble", return_value=None)
@patch("simulate.run_plan_b")
def test_run_mirofish_falls_back_to_plan_b(mock_plan_b, mock_ensemble):
    mock_plan_b.return_value = copy.deepcopy(MOCK_PREDICTION)
    from simulate import run_mirofish
    result = run_mirofish("test briefing")
    assert result is not None
    mock_plan_b.assert_called_once()


@patch("ensemble.orchestrator.run_ensemble", side_effect=Exception("boom"))
@patch("simulate.run_plan_b")
def test_run_mirofish_catches_ensemble_exception(mock_plan_b, mock_ensemble):
    mock_plan_b.return_value = copy.deepcopy(MOCK_PREDICTION)
    from simulate import run_mirofish
    result = run_mirofish("test briefing")
    assert result is not None
    mock_plan_b.assert_called_once()
