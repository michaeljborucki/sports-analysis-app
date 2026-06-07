"""Regression tests for calibrate.apply_calibration.

Pins the legacy cap behavior for bet types that have NO fitted calibrator.
Tests run with an empty calibrator cache so the fallback-cap path is exercised
in isolation from any production calibration file.
"""
from unittest.mock import patch
import pandas as pd
import pytest
from calibrate import calibration_report, apply_calibration, SIM_PROB_CAP


@pytest.fixture(autouse=True)
def _no_prod_calibration(monkeypatch):
    import calibrate
    monkeypatch.setattr(calibrate, "_CALIBRATORS", {})


def test_sim_prob_cap_value():
    """Pin the cap value. Changing it requires conscious updates everywhere."""
    assert SIM_PROB_CAP == 0.75


def test_apply_calibration_passthrough_below_cap():
    """Probabilities below the cap pass through unchanged."""
    assert apply_calibration(0.6, "moneyline") == 0.6
    assert apply_calibration(0.45, "total") == 0.45
    assert apply_calibration(0.0, "") == 0.0
    assert apply_calibration(0.5, "batter_hits") == 0.5


def test_apply_calibration_caps_at_threshold():
    """Probabilities at or above the cap clip down to SIM_PROB_CAP."""
    assert apply_calibration(0.80, "any") == SIM_PROB_CAP
    assert apply_calibration(0.95, "moneyline") == SIM_PROB_CAP
    assert apply_calibration(1.0, "nrfi") == SIM_PROB_CAP


def test_apply_calibration_at_exact_cap():
    assert apply_calibration(SIM_PROB_CAP, "any") == SIM_PROB_CAP


def test_apply_calibration_just_below_cap():
    assert apply_calibration(0.7499, "any") == 0.7499


def test_apply_calibration_just_above_cap():
    assert apply_calibration(0.7501, "any") == SIM_PROB_CAP


def test_apply_calibration_handles_none():
    """Some upstream paths can return None — function must not crash."""
    assert apply_calibration(None) is None


def test_apply_calibration_handles_string_input():
    """CSV reads can produce string probs — function should coerce to float."""
    assert apply_calibration("0.6", "any") == 0.6
    assert apply_calibration("0.95", "any") == SIM_PROB_CAP


@patch("calibrate.load_bets")
def test_calibration_report_insufficient_data(mock_load):
    mock_load.return_value = pd.DataFrame(columns=["result", "bet_type", "edge"])
    result = calibration_report()
    assert result["status"] == "insufficient_data"
