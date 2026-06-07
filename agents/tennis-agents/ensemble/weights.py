"""Model weight storage and management."""
import json
import os
from config import ENSEMBLE_MODELS, MODEL_WEIGHTS_FILE

BET_SLOTS = ["moneyline", "game_handicap", "total_games"]


def default_weights() -> dict:
    return {model: {slot: 1.0 for slot in BET_SLOTS} for model in ENSEMBLE_MODELS}


def load_weights(path: str = None) -> dict:
    path = path or MODEL_WEIGHTS_FILE
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    w = default_weights()
    save_weights(w, path)
    return w


def save_weights(weights: dict, path: str = None) -> None:
    path = path or MODEL_WEIGHTS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(weights, f, indent=2)
