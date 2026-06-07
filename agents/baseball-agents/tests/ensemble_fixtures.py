"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "pitching", "game_winner": "NYY", "reasoning": "Cole is elite"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.58,
            "away_win_prob": 0.42,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "run_line": {
            "favorite_cover_prob": 0.45,
            "value_side": "favorite_rl",
            "edge": 0.04,
            "confidence": "low",
        },
        "total": {
            "projected_total": 8.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "first_5": {
            "f5_home_win_prob": 0.56,
            "f5_away_win_prob": 0.44,
            "f5_projected_total": 4.2,
            "f5_ml_value": "home",
            "f5_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 3, "home": 5},
        "key_factors": ["Cole dominance", "wind blowing in"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"home": -150, "away": 130},
    "run_line": {"home": -1.5, "home_odds": -110, "away": 1.5, "away_odds": -110},
    "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
    "f5_moneyline": {"home": -130, "away": 110},
    "f5_total": {"line": 4.5, "over_odds": -115, "under_odds": -105},
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
