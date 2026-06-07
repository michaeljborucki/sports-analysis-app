from unittest.mock import patch
import pandas as pd
from calibrate import apply_calibration, calibration_report, SIM_PROB_CAP


@patch("calibrate.load_bets")
def test_calibration_report_insufficient_data(mock_load):
    mock_load.return_value = pd.DataFrame(columns=["result", "bet_type", "edge"])
    result = calibration_report()
    assert result["status"] == "insufficient_data"


def test_apply_calibration_caps_high_prob():
    assert apply_calibration(0.92, "moneyline") == SIM_PROB_CAP
    assert apply_calibration(0.99, "total_games") == SIM_PROB_CAP


def test_apply_calibration_floors_low_prob():
    floor = round(1.0 - SIM_PROB_CAP, 6)
    assert apply_calibration(0.08, "moneyline") == floor
    assert apply_calibration(0.01, "total_games") == floor


def test_apply_calibration_passes_middle_range_unchanged():
    for p in [0.25, 0.40, 0.50, 0.60, 0.75]:
        assert apply_calibration(p, "moneyline") == p


def test_apply_calibration_boundary_is_inclusive():
    # Values exactly at cap / floor are not modified
    assert apply_calibration(SIM_PROB_CAP, "moneyline") == SIM_PROB_CAP
    floor = round(1.0 - SIM_PROB_CAP, 6)
    assert apply_calibration(floor, "moneyline") == floor


def test_apply_calibration_bet_type_not_yet_used():
    # Same prob → same calibrated value regardless of bet_type (starting policy).
    for p in [0.10, 0.50, 0.95]:
        assert (
            apply_calibration(p, "moneyline")
            == apply_calibration(p, "game_handicap")
            == apply_calibration(p, "total_games")
        )


def test_apply_calibration_handles_non_numeric():
    # Defensive: bad input returns the original value so callers can decide.
    assert apply_calibration(None) is None
    assert apply_calibration("nope") == "nope"
