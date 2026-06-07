"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "offensive", "pick": "BOS", "reasoning": "Elite offensive rating and 3PT shooting"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.58,
            "away_win_prob": 0.42,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "spread": {
            "favorite_cover_prob": 0.45,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "low",
        },
        "total": {
            "projected_total": 218.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "first_half": {
            "h1_home_win_prob": 0.56,
            "h1_away_win_prob": 0.44,
            "h1_projected_total": 108.5,
            "h1_ml_value": "home",
            "h1_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 105, "home": 112},
        "key_factors": ["Home court advantage", "B2B fatigue for away team"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"home": -150, "away": 130},
    "spread": {"home": -4.5, "home_odds": -110, "away": 4.5, "away_odds": -110},
    "total": {"line": 218.5, "over_odds": -110, "under_odds": -110},
    "h1_moneyline": {"home": -130, "away": 110},
    "h1_total": {"line": 108.5, "over_odds": -115, "under_odds": -105},
    "implied_probs": {"ml_home": 0.60, "ml_away": 0.40},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
