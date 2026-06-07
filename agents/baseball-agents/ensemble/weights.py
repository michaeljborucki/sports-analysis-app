"""Model weight storage and management."""
import json
import os
import threading
from config import ENSEMBLE_MODELS, MODEL_WEIGHTS_FILE

_weights_lock = threading.Lock()

BET_SLOTS = [
    "moneyline", "run_line", "total", "first_5_ml", "first_5_total",
    "team_total_home", "team_total_away", "first_5_rl", "nrfi",
    "first_1_rl", "first_3_ml", "first_3_total", "first_3_rl",
]


def default_weights() -> dict:
    return {model: {slot: 1.0 for slot in BET_SLOTS} for model in ENSEMBLE_MODELS}


def load_weights(path: str = None) -> dict:
    path = path or MODEL_WEIGHTS_FILE
    with _weights_lock:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        w = default_weights()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(w, f, indent=2)
        return w


def save_weights(weights: dict, path: str = None) -> None:
    path = path or MODEL_WEIGHTS_FILE
    with _weights_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(weights, f, indent=2)
