"""Shared mock data for ensemble tests."""
import json
import copy

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "pitch_conditions", "pick": "MI", "reasoning": "Batting pitch favours MI"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.58,
            "team_b_win_prob": 0.42,
            "value_side": "team_a",
            "edge": 0.06,
            "confidence": "medium",
        },
        "total_runs": {
            "projected": 340.5,
            "confidence": "medium",
        },
        "team_total_runs": {
            "projected": 172.0,
            "confidence": "medium",
        },
        "spread": {
            "projected": 12.5,
            "confidence": "medium",
        },
        "player_runs": [
            {"player": "Rohit Sharma", "projected": 32.5},
        ],
        "player_wickets": [
            {"player": "Jasprit Bumrah", "projected": 1.4},
        ],
        "player_boundaries": [
            {"player": "Rohit Sharma", "projected": 4.2},
        ],
        "player_sixes": [
            {"player": "Rohit Sharma", "projected": 1.8},
        ],
        "powerplay_runs": {
            "projected": 52.0,
            "confidence": "medium",
        },
        "match_total_sixes": {
            "projected": 14.5,
            "confidence": "medium",
        },
        "match_total_fours": {
            "projected": 27.0,
            "confidence": "medium",
        },
        "first_over_runs": {
            "projected": 6.5,
            "confidence": "medium",
        },
        "fall_of_first_wicket": {
            "projected": 28.0,
            "confidence": "medium",
        },
        "runs_conceded": [
            {"player": "Jasprit Bumrah", "projected": 28.0},
        ],
        "dot_balls": [
            {"player": "Jasprit Bumrah", "projected": 10.5},
        ],
        "predicted_result": {
            "winner": "MI",
            "winning_margin": "5 wickets",
            "projected_scores": {
                "batting_first": 178,
                "chasing": 179,
            },
        },
        "key_factors": ["batting pitch", "dew factor", "MI powerplay dominance"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"team_a": -130, "team_b": 110},
    "total_runs": {"line": 340.5, "odds": -110},
    "team_total_runs": {"line": 170.5, "odds": -110},
    "spread": {"line": 10.5, "odds": -110},
    "player_runs": [{"player": "Rohit Sharma", "line": 29.5, "odds": -115}],
    "player_wickets": [{"player": "Jasprit Bumrah", "line": 1.5, "odds": -110}],
    "player_boundaries": [{"player": "Rohit Sharma", "line": 3.5, "odds": -110}],
    "player_sixes": [{"player": "Rohit Sharma", "line": 1.5, "odds": 110}],
    "powerplay_runs": {"line": 50.5, "odds": -110},
    "match_total_sixes": {"line": 13.5, "odds": -110},
    "match_total_fours": {"line": 26.5, "odds": -110},
    "first_over_runs": {"line": 6.5, "odds": -110},
    "fall_of_first_wicket": {"line": 25.5, "odds": -110},
    "runs_conceded": [{"player": "Jasprit Bumrah", "line": 30.5, "odds": -110}],
    "dot_balls": [{"player": "Jasprit Bumrah", "line": 9.5, "odds": -110}],
    "implied_probs": {"team_a": 0.565, "team_b": 0.435},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            if isinstance(pred["predictions"][key], dict):
                pred["predictions"][key].update(val)
            else:
                pred["predictions"][key] = val
    return pred
