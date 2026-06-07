"""Shared mock data for ensemble tests."""
import json
import copy

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "serve", "pick": "Djokovic", "reasoning": "Elite serve on hard court"},
    ],
    "predictions": {
        "moneyline": {
            "player_a_win_prob": 0.58,
            "player_b_win_prob": 0.42,
            "value_side": "player_a",
            "edge": 0.06,
            "confidence": "medium",
        },
        "game_handicap": {
            "favorite_cover_prob": 0.45,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "low",
        },
        "total_games": {
            "projected_games": 22.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "predicted_result": {"winner": "Djokovic", "score": "6-4 6-3"},
        "key_factors": ["Serve dominance on hard court", "H2H advantage"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"player_a": -150, "player_b": 130},
    "game_handicap": {
        "player_a_point": -4.5, "player_a_odds": -110,
        "player_b_point": 4.5, "player_b_odds": -110,
    },
    "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
    "implied_probs": {"player_a": 0.60, "player_b": 0.40},
}


def make_prediction(**overrides):
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
