from ensemble.consensus import validate_prediction_coherence


def test_valid_prediction_passes():
    pred = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.60, "away_win_prob": 0.40},
            "total": {"over_prob": 0.55, "under_prob": 0.45},
        }
    }
    assert validate_prediction_coherence(pred) is True


def test_incoherent_moneyline_fails():
    pred = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.60, "away_win_prob": 0.65},
        }
    }
    assert validate_prediction_coherence(pred) is False


def test_incoherent_total_fails():
    pred = {
        "predictions": {
            "total": {"over_prob": 0.70, "under_prob": 0.60},
        }
    }
    assert validate_prediction_coherence(pred) is False


def test_missing_sections_passes():
    pred = {"predictions": {}}
    assert validate_prediction_coherence(pred) is True
