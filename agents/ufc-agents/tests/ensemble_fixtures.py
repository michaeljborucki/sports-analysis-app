"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "striking", "pick": "Fighter A", "reasoning": "Superior striking"},
    ],
    "predictions": {
        "moneyline": {
            "fighter_a_win_prob": 0.62,
            "fighter_b_win_prob": 0.38,
            "value_side": "fighter_a",
            "edge": 0.07,
            "confidence": "medium",
        },
        "total_rounds": {
            "projected_rounds": 2.8,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.06,
            "confidence": "medium",
        },
        "method": {
            "ko_tko_prob": 0.35,
            "submission_prob": 0.30,
            "decision_prob": 0.35,
            "most_likely": "Decision",
            "value_method": "dec",
            "confidence": "medium",
        },
        "predicted_result": {"winner": "Fighter A", "method": "Decision", "round": 3},
        "key_factors": ["wrestling control", "cardio advantage"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"fighter_a": -150, "fighter_b": 130},
    "total_rounds": {"line": 2.5, "over_odds": -110, "under_odds": -110},
    "implied_probs": {"fighter_a": 0.60, "fighter_b": 0.40},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
