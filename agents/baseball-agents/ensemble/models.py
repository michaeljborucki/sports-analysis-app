"""Model registry for the ensemble panel.

2026-05-07 changes:
  - `gpt4o` slot bumped from openai/gpt-4o → openai/gpt-5.4 (key name kept
    for stability; many tests reference 'gpt4o').
  - Challenger separated: `claude` (Sonnet 4) stays on panel for diversity;
    new `claude_opus` entry (Opus 4.7) becomes the dedicated challenger
    (per ENSEMBLE_CHALLENGER in config.py).
"""
from config import ENSEMBLE_MODELS, ENSEMBLE_CHALLENGER

MODEL_REGISTRY = {
    "kimi": {
        "id": "moonshotai/kimi-k2.5",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 45,
        "input_price": 0.45,
        "output_price": 2.25,
    },
    "claude": {
        "id": "anthropic/claude-sonnet-4",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 45,
        "input_price": 3.00,
        "output_price": 15.00,
    },
    "gpt4o": {
        # Legacy key name; bumped 2026-05-07 to GPT-5.4 (~$2.50/$15, 1M ctx).
        "id": "openai/gpt-5.4",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 45,
        "input_price": 2.50,
        "output_price": 15.00,
    },
    "gemini": {
        "id": "google/gemini-2.5-flash",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 30,
        "input_price": 0.30,
        "output_price": 2.50,
    },
    "deepseek": {
        "id": "deepseek/deepseek-r1",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 90,
        "input_price": 0.70,
        "output_price": 2.50,
    },
    "maverick": {
        "id": "meta-llama/llama-4-maverick",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 30,
        "input_price": 0.15,
        "output_price": 0.60,
    },
    "claude_opus": {
        # Dedicated challenger (added 2026-05-07). Stronger reasoning catches
        # data-quality issues (rookie pitchers, wrong starter assignments)
        # that the panel sometimes builds predictions on top of.
        "id": "anthropic/claude-opus-4.7",
        "role": "challenger",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 60,
        "input_price": 5.00,
        "output_price": 25.00,
    },
}


def get_model(key: str) -> dict | None:
    return MODEL_REGISTRY.get(key)


def get_panel_models() -> list[tuple[str, dict]]:
    return [(key, MODEL_REGISTRY[key]) for key in ENSEMBLE_MODELS if key in MODEL_REGISTRY]


def get_challenger_model() -> dict | None:
    return MODEL_REGISTRY.get(ENSEMBLE_CHALLENGER)
