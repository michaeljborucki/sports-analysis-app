"""Model weight storage and management."""
import json
import os
from config import ENSEMBLE_MODELS, MODEL_WEIGHTS_FILE

from config import BET_SLOTS


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


def shrink_weights(weights: dict, n_settled: int, full_confidence_n: int = 100) -> dict:
    """Shrink model weights toward uniform (1.0) based on sample size.

    With few settled bets, Brier-derived weights are noisy. This blends
    toward uniform = 1.0 proportional to how much data we have:

        effective_weight = 1.0 + (brier_weight - 1.0) * min(n_settled / full_confidence_n, 1.0)

    At 22 bets: only 22% of the Brier signal is used.
    At 100+ bets: full Brier weights are used.

    Also caps any single weight at MAX_WEIGHT to prevent one model from
    dominating (especially important for totals where maverick had 1.25 weight
    while systematically voting over).
    """
    MAX_WEIGHT = 1.5
    blend_factor = min(n_settled / full_confidence_n, 1.0)

    shrunk = {}
    for model, slot_weights in weights.items():
        shrunk[model] = {}
        for slot, w in slot_weights.items():
            effective = 1.0 + (w - 1.0) * blend_factor
            effective = min(effective, MAX_WEIGHT)
            shrunk[model][slot] = round(effective, 4)

    return shrunk
