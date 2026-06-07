"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "efficiency", "pick": "Duke", "reasoning": "Superior AdjEM (+28.5 vs +15.2)"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.65,
            "away_win_prob": 0.35,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "spread": {
            "favorite_cover_prob": 0.55,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "medium",
        },
        "total": {
            "projected_total": 142.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "first_half": {
            "h1_home_win_prob": 0.60,
            "h1_away_win_prob": 0.40,
            "h1_projected_total": 68.5,
            "h1_ml_value": "home",
            "h1_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 65, "home": 78},
        "key_factors": ["Efficiency gap", "Home court advantage"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"home": -200, "away": 170},
    "spread": {"home": -6.5, "home_odds": -110, "away": 6.5, "away_odds": -110},
    "total": {"line": 142.5, "over_odds": -110, "under_odds": -110},
    "h1_moneyline": {"home": -160, "away": 140},
    "h1_total": {"line": 68.5, "over_odds": -115, "under_odds": -105},
    "h1_spread": {"home": -3.5, "home_odds": -110, "away": 3.5, "away_odds": -110},
    "implied_probs": {"ml_home": 0.67, "ml_away": 0.33},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
