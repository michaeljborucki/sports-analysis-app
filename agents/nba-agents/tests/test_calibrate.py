from unittest.mock import patch
import pandas as pd
from calibrate import calibration_report


@patch("calibrate.load_bets")
def test_calibration_report_insufficient_data(mock_load):
    mock_load.return_value = pd.DataFrame(columns=["result", "bet_type", "edge"])
    result = calibration_report()
    assert result["status"] == "insufficient_data"
