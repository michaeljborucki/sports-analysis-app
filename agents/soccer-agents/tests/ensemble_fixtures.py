"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "tactical", "game_winner": "home", "reasoning": "Strong home form"},
    ],
    "predictions": {
        "asian_handicap": {
            "home_cover_prob": 0.58,
            "away_cover_prob": 0.42,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "total": {
            "projected_goals": 2.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "btts": {
            "btts_yes_prob": 0.60,
            "btts_no_prob": 0.40,
            "value_side": "yes",
            "edge": 0.04,
            "confidence": "medium",
        },
        "predicted_score": {"away": 1, "home": 2},
        "key_factors": ["Strong home attack", "Away defense injuries"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
    "total": {"line": 2.5, "over_odds": -110, "under_odds": -110},
    "btts": {"yes_odds": -115, "no_odds": -105},
    "implied_probs": {"ah_home": 0.55, "ah_away": 0.45},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
