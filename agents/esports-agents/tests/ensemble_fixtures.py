"""Shared mock data for ensemble tests — CS2 esports format."""
import json
import types

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "fragging", "pick": "NAVI", "reasoning": "s1mple is elite"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.62,
            "team_b_win_prob": 0.38,
            "value_side": "team_a",
            "edge": 0.07,
            "confidence": "medium",
        },
        "map_handicap": {
            "favorite_cover_prob": 0.48,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "low",
        },
        "total_maps": {
            "projected_maps": 2.6,
            "over_prob": 0.57,
            "under_prob": 0.43,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "predicted_result": {"winner": "NAVI", "score": "2-1"},
        "key_factors": ["s1mple AWP dominance", "map pool advantage"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"team_a": -160, "team_b": 140},
    "map_handicap": {"line": -1.5, "favorite_odds": -120, "underdog_odds": 100},
    "total_maps": {"line": 2.5, "over_odds": -115, "under_odds": -105},
    "implied_probs": {"ml_team_a": 0.615, "ml_team_b": 0.385},
}


# Minimal mock game_config that mirrors games.cs2 module structure
_mock_config = types.SimpleNamespace(
    BET_SLOTS=["moneyline", "map_handicap", "total_maps"],
    PROB_FIELDS={
        "moneyline": ["team_a_win_prob", "team_b_win_prob"],
        "map_handicap": ["favorite_cover_prob"],
        "total_maps": ["over_prob", "under_prob", "projected_maps"],
    },
    SLOT_SECTION={
        "moneyline": "moneyline",
        "map_handicap": "map_handicap",
        "total_maps": "total_maps",
    },
    PRIMARY_PROB_FIELD={
        "moneyline": "team_a_win_prob",
        "map_handicap": "favorite_cover_prob",
        "total_maps": "over_prob",
    },
    BET_SLOT_FIELDS={
        "moneyline": ("moneyline", "value_side"),
        "map_handicap": ("map_handicap", "value_side"),
        "total_maps": ("total_maps", "value_side"),
    },
)

_mock_prompt = types.SimpleNamespace(
    SYSTEM_PROMPT="You are a CS2 prediction system. Respond in JSON only.",
)

MOCK_GAME_CONFIG = types.SimpleNamespace(
    config=_mock_config,
    prompt=_mock_prompt,
)


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            if isinstance(pred["predictions"][key], dict) and isinstance(val, dict):
                pred["predictions"][key].update(val)
            else:
                pred["predictions"][key] = val
    return pred
