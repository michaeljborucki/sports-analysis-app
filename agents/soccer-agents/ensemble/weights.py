"""Model weight storage and management."""
import json
import os
from config import ENSEMBLE_MODELS, MODEL_WEIGHTS_FILE

BET_SLOTS = ["asian_handicap", "total", "btts"]

# Synthetic voters (non-LLM) that participate in weighting but aren't dispatched
# by the orchestrator. Start at 1.5x to let xG+Poisson anchor against LLM drift
# on totals and BTTS where the distributional assumptions fit best.
NON_LLM_VOTERS = {
    "quant_poisson": {"asian_handicap": 1.0, "total": 1.5, "btts": 1.5},
}


def default_weights() -> dict:
    weights = {model: {slot: 1.0 for slot in BET_SLOTS} for model in ENSEMBLE_MODELS}
    for voter, slot_weights in NON_LLM_VOTERS.items():
        weights[voter] = dict(slot_weights)
    return weights


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
