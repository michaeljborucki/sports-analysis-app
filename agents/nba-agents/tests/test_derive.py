"""Tests for derive.py."""
from derive import derive_quarter_projections


def test_q2_total_derived_from_h1_minus_q1():
    preds = {
        "total": {"projected_total": 220.0},
        "first_half": {"h1_projected_total": 112.0},
        "q1": {"q1_projected_total": 57.0},
    }
    derived = derive_quarter_projections(preds)
    assert derived["q2_projected_total"] == 55.0  # 112 - 57


def test_h2_total_derived_from_game_minus_h1():
    preds = {
        "total": {"projected_total": 220.0},
        "first_half": {"h1_projected_total": 112.0},
        "q1": {"q1_projected_total": 57.0},
    }
    derived = derive_quarter_projections(preds)
    assert derived["h2_projected_total"] == 108.0  # 220 - 112


def test_q3_q4_split():
    preds = {
        "total": {"projected_total": 220.0},
        "first_half": {"h1_projected_total": 112.0},
        "q1": {"q1_projected_total": 57.0},
    }
    derived = derive_quarter_projections(preds)
    # H2 = 108. Q3 = 108 * 0.52 = 56.16, Q4 = 108 * 0.48 = 51.84
    assert abs(derived["q3_projected_total"] - 56.16) < 0.01
    assert abs(derived["q4_projected_total"] - 51.84) < 0.01


def test_missing_predictions_returns_empty():
    derived = derive_quarter_projections({})
    assert derived == {}


def test_partial_predictions_returns_empty():
    preds = {"total": {"projected_total": 220.0}}
    derived = derive_quarter_projections(preds)
    assert derived == {}
