"""Model registry for the ensemble panel."""
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
        "role": "panel+challenger",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 45,
        "input_price": 3.00,
        "output_price": 15.00,
    },
    "gpt4o": {
        "id": "openai/gpt-4o",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 12288,
        "timeout": 45,
        "input_price": 2.50,
        "output_price": 10.00,
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
    "stat_anchor": {
        "id": "local/stat_model",
        "role": "panel",
        "default_temp": 0.0,
        "max_tokens": 0,
        "timeout": 1,
        "input_price": 0.0,
        "output_price": 0.0,
    },
}


def get_model(key: str) -> dict | None:
    return MODEL_REGISTRY.get(key)


def get_panel_models() -> list[tuple[str, dict]]:
    return [(key, MODEL_REGISTRY[key]) for key in ENSEMBLE_MODELS if key in MODEL_REGISTRY]


def get_challenger_model() -> dict | None:
    return MODEL_REGISTRY.get(ENSEMBLE_CHALLENGER)
