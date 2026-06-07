# Multi-Model Ensemble Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `run_mirofish()` stub with a multi-model ensemble that dispatches predictions across 6 LLMs via OpenRouter, applies adaptive dispatch, consensus gating, weighted averaging, and adversarial challenge.

**Architecture:** New `ensemble/` package alongside existing `simulate.py`. Plan B screen pass is untouched. `run_mirofish()` delegates to `ensemble.run_ensemble()` with fallback to Plan B on failure. 6 models, 3 phases (quick pass → temperature expansion → adversarial challenge), consensus gate (3/6 minimum), per-model weights evolving via Brier scores.

**Tech Stack:** Python 3.11+, openai SDK (OpenRouter-compatible), concurrent.futures for parallelization, pandas for prediction logging, pytest for tests.

**Spec:** `docs/superpowers/specs/2026-03-18-multi-model-ensemble-design.md`

---

## File Map

### New Files (ensemble package)

| File | Responsibility |
|---|---|
| `ensemble/__init__.py` | Exports `run_ensemble()` |
| `ensemble/models.py` | Model registry: IDs, pricing, timeouts, roles |
| `ensemble/runner.py` | Single LLM call via OpenRouter + response parsing |
| `ensemble/orchestrator.py` | Adaptive 3-phase dispatch logic |
| `ensemble/consensus.py` | Consensus gate, weighted averaging, vote normalization |
| `ensemble/challenger.py` | Adversarial pass via Claude Sonnet 4 |
| `ensemble/weights.py` | Load/save/default model weights from JSON |
| `ensemble/logger.py` | Per-model prediction CSV logging |

### New Test Files

| File | Tests |
|---|---|
| `tests/test_ensemble_models.py` | Model registry validation |
| `tests/test_ensemble_runner.py` | Single call + DeepSeek parsing |
| `tests/test_ensemble_weights.py` | Weight load/save/default/update |
| `tests/test_ensemble_consensus.py` | Vote counting, averaging, stability bonus, kill logic |
| `tests/test_ensemble_challenger.py` | Challenge parsing, kill/approve, guardrail |
| `tests/test_ensemble_orchestrator.py` | Phase flow, adaptive expansion, fallback |
| `tests/test_ensemble_logger.py` | CSV creation and append |
| `tests/test_ensemble_integration.py` | End-to-end `run_ensemble()` with mocked API calls |

### Modified Files

| File | Change |
|---|---|
| `config.py:17-31` | Add ensemble config, split F5 thresholds |
| `simulate.py:127-134` | Delegate `run_mirofish()` to ensemble with fallback, add `odds` param |
| `main.py:155,248` | Pass `odds=game_data["odds"]` to `run_mirofish()` calls |
| `edge.py:190-262` | Split `check_f5_edge()` into ML + total, update `analyze_all_edges()` |
| `tests/test_edge.py` | Add F5 total tests, update `analyze_all_edges` test |
| `agents/self_optimizer.py` | Add model weight update + challenger guardrail |
| `tests/test_self_optimizer.py` | Test weight update logic |

---

## Shared Test Fixtures

Several tasks need the same mock data. Create this first so all tests can import it.

---

### Task 1: Shared Test Fixtures + Config Updates + F5 Edge Split

**Files:**
- Create: `tests/ensemble_fixtures.py`
- Modify: `config.py:17-31`
- Modify: `edge.py:190-262`
- Modify: `tests/test_edge.py`

> **Important:** The config change and edge.py refactor MUST be done atomically in the same task. Changing `EDGE_THRESHOLDS` without updating `edge.py` will break existing tests.

- [ ] **Step 1: Write shared test fixtures file**

```python
# tests/ensemble_fixtures.py
"""Shared mock data for ensemble tests."""
import json

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "pitching", "game_winner": "NYY", "reasoning": "Cole is elite"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.58,
            "away_win_prob": 0.42,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "run_line": {
            "favorite_cover_prob": 0.45,
            "value_side": "favorite_rl",
            "edge": 0.04,
            "confidence": "low",
        },
        "total": {
            "projected_total": 8.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "first_5": {
            "f5_home_win_prob": 0.56,
            "f5_away_win_prob": 0.44,
            "f5_projected_total": 4.2,
            "f5_ml_value": "home",
            "f5_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 3, "home": 5},
        "key_factors": ["Cole dominance", "wind blowing in"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"home": -150, "away": 130},
    "run_line": {"home": -1.5, "home_odds": -110, "away": 1.5, "away_odds": -110},
    "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
    "f5_moneyline": {"home": -130, "away": 110},
    "f5_total": {"line": 4.5, "over_odds": -115, "under_odds": -105},
    "implied_probs": {"ml_home": 0.60, "ml_away": 0.40},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides to specific bet slots."""
    import copy
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
```

- [ ] **Step 2: Update config.py with ensemble settings and F5 threshold split**

In `config.py`, after line 20 (`SCREEN_EDGE_THRESHOLD = 0.03`), add:

```python
# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
```

Replace the existing `EDGE_THRESHOLDS` dict (lines 26-31) with:

```python
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "run_line": 0.06,
    "total": 0.05,
    "first_5_ml": 0.05,
    "first_5_total": 0.05,
}
```

- [ ] **Step 3: Refactor edge.py — split F5 into ML + total**

In `edge.py`:
- Rename `check_f5_edge()` to `check_f5_ml_edge()`, change threshold to `EDGE_THRESHOLDS["first_5_ml"]`, return `"bet_type": "first_5_ml"`
- Add new `check_f5_total_edge()` that checks F5 over/under using `f5_projected_total` vs F5 total line, uses threshold `EDGE_THRESHOLDS["first_5_total"]`, returns `"bet_type": "first_5_total"`
- Update `analyze_all_edges()` to call both, docstring says "Returns 0-5 bet signals"

- [ ] **Step 4: Add F5 edge tests to tests/test_edge.py**

Add:

```python
from edge import check_f5_ml_edge, check_f5_total_edge


def test_check_f5_ml_edge_found():
    sim = {
        "predictions": {
            "first_5": {"f5_home_win_prob": 0.62, "f5_away_win_prob": 0.38}
        }
    }
    odds = {
        "f5_moneyline": {"home": -130, "away": 110},
        "implied_probs": {"ml_home": 0.565, "ml_away": 0.435},
    }
    result = check_f5_ml_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "first_5_ml"


def test_check_f5_total_edge_runs():
    sim = {"predictions": {"first_5": {"f5_projected_total": 4.8}}}
    odds = {"f5_total": {"line": 4.5, "over_odds": -110, "under_odds": -110}}
    result = check_f5_total_edge(sim, odds)
    assert result is None or result["bet_type"] == "first_5_total"


def test_analyze_all_edges_returns_up_to_five():
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.70, "away_win_prob": 0.30},
            "run_line": {"favorite_cover_prob": 0.55},
            "total": {"over_prob": 0.65, "under_prob": 0.35, "projected_total": 9.5},
            "first_5": {"f5_home_win_prob": 0.65, "f5_away_win_prob": 0.35, "f5_projected_total": 5.5},
        }
    }
    odds = {
        "moneyline": {"home": -140, "away": 120},
        "run_line": {"home": -1.5, "home_odds": 145, "away": 1.5, "away_odds": -170},
        "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
        "f5_moneyline": {"home": -130, "away": 110},
        "f5_total": {"line": 4.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"ml_home": 0.583, "ml_away": 0.417},
    }
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    assert len(bets) <= 5
    bet_types = [b["bet_type"] for b in bets]
    assert len(bet_types) == len(set(bet_types))
```

- [ ] **Step 5: Run ALL existing tests to verify nothing broke**

Run: `pytest tests/test_config.py tests/test_edge.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tests/ensemble_fixtures.py config.py edge.py tests/test_edge.py
git commit -m "feat: add ensemble config, shared fixtures, split F5 edge into ML + total"
```

---

### Task 2: Model Registry (`ensemble/models.py`)

**Files:**
- Create: `ensemble/__init__.py`
- Create: `ensemble/models.py`
- Create: `tests/test_ensemble_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_models.py
from ensemble.models import MODEL_REGISTRY, get_model, get_panel_models, get_challenger_model


def test_registry_has_six_models():
    assert len(MODEL_REGISTRY) == 6


def test_all_models_have_required_fields():
    required = {"id", "role", "default_temp", "max_tokens", "timeout", "input_price", "output_price"}
    for key, model in MODEL_REGISTRY.items():
        missing = required - set(model.keys())
        assert not missing, f"Model {key} missing fields: {missing}"


def test_get_model_valid():
    m = get_model("kimi")
    assert m["id"] == "moonshotai/kimi-k2.5"


def test_get_model_invalid():
    assert get_model("nonexistent") is None


def test_panel_models_excludes_challenger_only():
    panels = get_panel_models()
    # All 6 are panel members (claude has dual role)
    assert len(panels) == 6


def test_challenger_model():
    c = get_challenger_model()
    assert c is not None
    assert "claude" in c["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ensemble'`

- [ ] **Step 3: Write implementation**

```python
# ensemble/__init__.py
"""Multi-model ensemble prediction engine."""
```

```python
# ensemble/models.py
"""Model registry for the ensemble panel."""
from config import ENSEMBLE_MODELS, ENSEMBLE_CHALLENGER

MODEL_REGISTRY = {
    "kimi": {
        "id": "moonshotai/kimi-k2.5",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 4096,
        "timeout": 45,
        "input_price": 0.45,
        "output_price": 2.25,
    },
    "claude": {
        "id": "anthropic/claude-sonnet-4",
        "role": "panel+challenger",
        "default_temp": 0.7,
        "max_tokens": 4096,
        "timeout": 45,
        "input_price": 3.00,
        "output_price": 15.00,
    },
    "gpt4o": {
        "id": "openai/gpt-4o",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 4096,
        "timeout": 45,
        "input_price": 2.50,
        "output_price": 10.00,
    },
    "gemini": {
        "id": "google/gemini-2.5-flash",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 4096,
        "timeout": 30,
        "input_price": 0.30,
        "output_price": 2.50,
    },
    "deepseek": {
        "id": "deepseek/deepseek-r1",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 4096,
        "timeout": 90,
        "input_price": 0.70,
        "output_price": 2.50,
    },
    "maverick": {
        "id": "meta-llama/llama-4-maverick",
        "role": "panel",
        "default_temp": 0.7,
        "max_tokens": 4096,
        "timeout": 30,
        "input_price": 0.15,
        "output_price": 0.60,
    },
}


def get_model(key: str) -> dict | None:
    """Get model config by key. Returns None if not found."""
    return MODEL_REGISTRY.get(key)


def get_panel_models() -> list[tuple[str, dict]]:
    """Return all models that participate in the prediction panel."""
    return [
        (key, MODEL_REGISTRY[key])
        for key in ENSEMBLE_MODELS
        if key in MODEL_REGISTRY
    ]


def get_challenger_model() -> dict | None:
    """Return the model config for the adversarial challenger."""
    return MODEL_REGISTRY.get(ENSEMBLE_CHALLENGER)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_models.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/__init__.py ensemble/models.py tests/test_ensemble_models.py
git commit -m "feat(ensemble): model registry with 6 OpenRouter models"
```

---

### Task 3: Weight Storage (`ensemble/weights.py`)

**Files:**
- Create: `ensemble/weights.py`
- Create: `tests/test_ensemble_weights.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_weights.py
import json
import os
import tempfile
from ensemble.weights import load_weights, save_weights, default_weights, BET_SLOTS


def test_bet_slots():
    assert BET_SLOTS == ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]


def test_default_weights():
    w = default_weights()
    assert len(w) == 6  # 6 models
    for model, slots in w.items():
        assert len(slots) == 5  # 5 bet slots
        for val in slots.values():
            assert val == 1.0


def test_load_weights_creates_file_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        w = load_weights(path)
        assert os.path.exists(path)
        assert w == default_weights()


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        w = default_weights()
        w["kimi"]["moneyline"] = 1.5
        save_weights(w, path)
        loaded = load_weights(path)
        assert loaded["kimi"]["moneyline"] == 1.5


def test_load_weights_corrupt_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        with open(path, "w") as f:
            f.write("not json")
        w = load_weights(path)
        assert w == default_weights()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_weights.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# ensemble/weights.py
"""Model weight storage and management."""
import json
import os
from config import ENSEMBLE_MODELS, MODEL_WEIGHTS_FILE

BET_SLOTS = ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]


def default_weights() -> dict:
    """Return default weights (1.0 for all models and bet slots)."""
    return {model: {slot: 1.0 for slot in BET_SLOTS} for model in ENSEMBLE_MODELS}


def load_weights(path: str = None) -> dict:
    """Load model weights from JSON. Creates with defaults if missing or corrupt."""
    path = path or MODEL_WEIGHTS_FILE
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    # Create with defaults
    w = default_weights()
    save_weights(w, path)
    return w


def save_weights(weights: dict, path: str = None) -> None:
    """Save model weights to JSON."""
    path = path or MODEL_WEIGHTS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(weights, f, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_weights.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/weights.py tests/test_ensemble_weights.py
git commit -m "feat(ensemble): weight storage with create-if-not-exists"
```

---

### Task 4: LLM Runner (`ensemble/runner.py`)

**Files:**
- Create: `ensemble/runner.py`
- Create: `tests/test_ensemble_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_runner.py
import json
from unittest.mock import patch, MagicMock
from ensemble.runner import run_single_model, strip_thinking, estimate_cost
from tests.ensemble_fixtures import MOCK_PREDICTION_JSON


def test_strip_thinking_removes_think_blocks():
    raw = '<think>Some reasoning here\nmore thinking</think>{"predictions": {}}'
    assert strip_thinking(raw).startswith("{")


def test_strip_thinking_fallback_finds_json():
    raw = "Some preamble text {\"predictions\": {}}"
    result = strip_thinking(raw)
    assert result.startswith("{")


def test_strip_thinking_clean_input():
    raw = '{"predictions": {}}'
    assert strip_thinking(raw) == '{"predictions": {}}'


def test_estimate_cost():
    cost = estimate_cost(1000, 500, 2.50, 10.00)
    # (1000 * 2.50 + 500 * 10.00) / 1_000_000 = 0.0075
    assert abs(cost - 0.0075) < 0.0001


@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_success(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_PREDICTION_JSON
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 500
    mock_response.usage.completion_tokens = 300
    mock_client.chat.completions.create.return_value = mock_response

    result = run_single_model(
        model_key="kimi",
        model_id="moonshotai/kimi-k2.5",
        briefing="Test briefing",
        temperature=0.7,
        max_tokens=4096,
        timeout=45,
        input_price=0.45,
        output_price=2.25,
    )
    assert result is not None
    assert result["parsed"]["predictions"]["moneyline"]["home_win_prob"] == 0.58
    assert result["cost"] > 0
    assert result["model_key"] == "kimi"


@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_api_error_returns_none(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API error")

    result = run_single_model(
        model_key="kimi",
        model_id="moonshotai/kimi-k2.5",
        briefing="Test briefing",
        temperature=0.7,
        max_tokens=4096,
        timeout=45,
        input_price=0.45,
        output_price=2.25,
    )
    assert result is None


@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_invalid_json_returns_none(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = "not valid json at all"
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 500
    mock_response.usage.completion_tokens = 300
    mock_client.chat.completions.create.return_value = mock_response

    result = run_single_model(
        model_key="kimi",
        model_id="moonshotai/kimi-k2.5",
        briefing="Test briefing",
        temperature=0.7,
        max_tokens=4096,
        timeout=45,
        input_price=0.45,
        output_price=2.25,
    )
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_runner.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# ensemble/runner.py
"""Fire individual LLM calls via OpenRouter."""
import re
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from simulate import MLB_SYSTEM_PROMPT, parse_simulation_result


def strip_thinking(raw: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek R1) and find JSON."""
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    if text and not text.startswith('{'):
        idx = text.find('{')
        if idx != -1:
            text = text[idx:]
    return text


def estimate_cost(input_tokens: int, output_tokens: int,
                  input_price: float, output_price: float) -> float:
    """Estimate cost in USD from token counts and per-million-token prices."""
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def run_single_model(
    model_key: str,
    model_id: str,
    briefing: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    input_price: float,
    output_price: float,
    system_prompt: str = None,
) -> dict | None:
    """Run a single LLM call. Returns parsed result dict or None on failure.

    Args:
        system_prompt: Override the default MLB_SYSTEM_PROMPT (used by challenger).

    Returns:
        {
            "model_key": str,
            "parsed": dict,       # the parsed prediction/response
            "temperature": float,
            "cost": float,        # estimated USD
        }
        or None on any failure.
    """
    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=timeout,
    )

    sys_prompt = system_prompt or MLB_SYSTEM_PROMPT

    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": briefing},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except openai.RateLimitError:
        # 429 retry: wait 2s and try once more
        import time
        print(f"[ensemble] {model_key} rate limited, retrying in 2s...")
        time.sleep(2)
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": briefing},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            print(f"[ensemble] {model_key} retry failed: {e}")
            return None
    except Exception as e:
        print(f"[ensemble] {model_key} API error: {e}")
        return None

    choice = response.choices[0]
    if choice.finish_reason == "length":
        print(f"[ensemble] {model_key} warning: response truncated")

    raw = choice.message.content
    if not raw:
        return None

    # Strip thinking blocks for DeepSeek R1
    if model_key == "deepseek":
        raw = strip_thinking(raw)

    parsed = parse_simulation_result(raw)
    if not parsed:
        print(f"[ensemble] {model_key} failed to parse JSON response")
        return None

    input_tokens = getattr(response.usage, 'prompt_tokens', 0)
    output_tokens = getattr(response.usage, 'completion_tokens', 0)
    cost = estimate_cost(input_tokens, output_tokens, input_price, output_price)

    return {
        "model_key": model_key,
        "parsed": parsed,
        "temperature": temperature,
        "cost": cost,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_runner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/runner.py tests/test_ensemble_runner.py
git commit -m "feat(ensemble): LLM runner with DeepSeek thinking block parser"
```

---

### Task 5: Prediction Logger (`ensemble/logger.py`)

**Files:**
- Create: `ensemble/logger.py`
- Create: `tests/test_ensemble_logger.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_logger.py
import os
import tempfile
import pandas as pd
from ensemble.logger import log_model_prediction, load_model_predictions, PREDICTION_COLUMNS


def test_log_creates_csv_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        log_model_prediction(
            date="2026-03-28",
            game="NYY@BOS",
            model="kimi",
            bet_type="moneyline",
            side="home",
            sim_prob=0.58,
            market_prob=0.52,
            edge=0.06,
            temperature=0.7,
            run_index=1,
            csv_path=path,
        )
        assert os.path.exists(path)
        df = pd.read_csv(path)
        assert len(df) == 1
        assert df.iloc[0]["model"] == "kimi"


def test_log_appends_to_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        for i in range(3):
            log_model_prediction(
                date="2026-03-28",
                game="NYY@BOS",
                model="kimi",
                bet_type="moneyline",
                side="home",
                sim_prob=0.58,
                market_prob=0.52,
                edge=0.06,
                temperature=0.7,
                run_index=i,
                csv_path=path,
            )
        df = pd.read_csv(path)
        assert len(df) == 3


def test_load_predictions_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        df = load_model_predictions(path)
        assert len(df) == 0
        assert list(df.columns) == PREDICTION_COLUMNS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_logger.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# ensemble/logger.py
"""Per-model prediction logging to CSV."""
import os
import pandas as pd
from config import MODEL_PREDICTIONS_CSV

PREDICTION_COLUMNS = [
    "date", "game", "model", "bet_type", "side",
    "sim_prob", "market_prob", "edge", "temperature", "run_index",
]


def _ensure_csv(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(path):
        pd.DataFrame(columns=PREDICTION_COLUMNS).to_csv(path, index=False)


def log_model_prediction(
    date: str, game: str, model: str, bet_type: str, side: str,
    sim_prob: float, market_prob: float, edge: float,
    temperature: float, run_index: int,
    csv_path: str = None,
) -> None:
    """Append a single model prediction to the CSV log."""
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    _ensure_csv(csv_path)

    row = {
        "date": date, "game": game, "model": model,
        "bet_type": bet_type, "side": side,
        "sim_prob": round(sim_prob, 4), "market_prob": round(market_prob, 4),
        "edge": round(edge, 4), "temperature": temperature,
        "run_index": run_index,
    }
    df = pd.read_csv(csv_path)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def load_model_predictions(csv_path: str = None) -> pd.DataFrame:
    """Load all model predictions from CSV."""
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    _ensure_csv(csv_path)
    return pd.read_csv(csv_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_logger.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/logger.py tests/test_ensemble_logger.py
git commit -m "feat(ensemble): per-model prediction CSV logger"
```

---

### Task 6: Consensus Gate (`ensemble/consensus.py`)

**Files:**
- Create: `ensemble/consensus.py`
- Create: `tests/test_ensemble_consensus.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_consensus.py
import copy
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS


def test_bet_slot_fields_has_five_slots():
    assert len(BET_SLOT_FIELDS) == 5


def test_extract_vote_moneyline():
    vote = extract_vote(MOCK_PREDICTION, "moneyline", MOCK_ODDS)
    assert vote == "home"


def test_extract_vote_run_line_normalizes_to_absolute():
    # Home has -1.5 spread, so home is favorite
    # Model says "favorite_rl" → normalized to "home_rl"
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["run_line"]["value_side"] = "favorite_rl"
    vote = extract_vote(pred, "run_line", MOCK_ODDS)
    assert vote == "home_rl"


def test_extract_vote_run_line_underdog():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["run_line"]["value_side"] = "underdog_rl"
    vote = extract_vote(pred, "run_line", MOCK_ODDS)
    assert vote == "away_rl"


def test_extract_vote_none():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["moneyline"]["value_side"] = "none"
    vote = extract_vote(pred, "moneyline", MOCK_ODDS)
    assert vote is None


def test_extract_vote_first_5_ml():
    vote = extract_vote(MOCK_PREDICTION, "first_5_ml", MOCK_ODDS)
    assert vote == "home"


def test_extract_vote_first_5_total():
    vote = extract_vote(MOCK_PREDICTION, "first_5_total", MOCK_ODDS)
    assert vote == "under"


def test_count_votes_strong_consensus():
    votes = {"kimi": "home", "claude": "home", "gpt4o": "home",
             "gemini": "home", "deepseek": "away", "maverick": "home"}
    side, count = count_votes(votes)
    assert side == "home"
    assert count == 5


def test_count_votes_no_consensus():
    votes = {"kimi": "home", "claude": "away", "gpt4o": "home",
             "gemini": "away", "deepseek": None, "maverick": None}
    side, count = count_votes(votes)
    assert count == 2  # 2 home, 2 away — no majority


def test_check_consensus_passes():
    votes = {"kimi": "home", "claude": "home", "gpt4o": "home",
             "gemini": "away", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is True


def test_check_consensus_fails():
    votes = {"kimi": "home", "claude": "away", "gpt4o": "home",
             "gemini": "away", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is False


def test_weighted_average_prob():
    # 3 runs: kimi (weight 1.0, prob 0.55), gpt4o (weight 2.0, prob 0.60), gemini (weight 1.0, prob 0.50)
    runs = [
        {"model_key": "kimi", "prob": 0.55},
        {"model_key": "gpt4o", "prob": 0.60},
        {"model_key": "gemini", "prob": 0.50},
    ]
    weights = {"kimi": 1.0, "gpt4o": 2.0, "gemini": 1.0}
    avg = weighted_average_prob(runs, weights)
    # (1.0*0.55 + 2.0*0.60 + 1.0*0.50) / (1.0 + 2.0 + 1.0) = 2.25/4.0 = 0.5625
    assert abs(avg - 0.5625) < 0.001


def test_apply_stability_bonus_tight():
    # std dev 0.02 < 0.03 → 1.2x
    assert apply_stability_bonus(1.0, 0.02) == 1.2


def test_apply_stability_bonus_noisy():
    # std dev 0.15 > 0.10 → 0.8x
    assert apply_stability_bonus(1.0, 0.15) == 0.8


def test_apply_stability_bonus_normal():
    # std dev 0.05 → no change
    assert apply_stability_bonus(1.0, 0.05) == 1.0


def test_majority_vote_clear_winner():
    assert majority_vote(["high", "high", "medium"]) == "high"


def test_majority_vote_tie_breaks_to_default():
    assert majority_vote(["high", "low", "medium"], default="medium") == "medium"


def test_majority_vote_empty():
    assert majority_vote([], default="medium") == "medium"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_consensus.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# ensemble/consensus.py
"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES

# Maps bet slot name → (predictions sub-key, value field name)
BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "run_line": ("run_line", "value_side"),
    "total": ("total", "value_side"),
    "first_5_ml": ("first_5", "f5_ml_value"),
    "first_5_total": ("first_5", "f5_total_value"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot. Returns None for 'none' votes."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    # Normalize run_line from relative (favorite/underdog) to absolute (home/away)
    if bet_slot == "run_line":
        rl_odds = odds.get("run_line", {})
        home_point = rl_odds.get("home", -1.5)
        home_is_fav = home_point < 0
        if raw_vote == "favorite_rl":
            return "home_rl" if home_is_fav else "away_rl"
        elif raw_vote == "underdog_rl":
            return "away_rl" if home_is_fav else "home_rl"
        return raw_vote

    return raw_vote


def count_votes(votes: dict[str, str | None]) -> tuple[str | None, int]:
    """Count votes and return (winning_side, count). Excludes None votes."""
    counts = {}
    for vote in votes.values():
        if vote is not None:
            counts[vote] = counts.get(vote, 0) + 1

    if not counts:
        return None, 0

    winner = max(counts, key=counts.get)
    return winner, counts[winner]


def check_consensus(votes: dict[str, str | None], min_votes: int = None) -> bool:
    """Check if enough models agree on the same side."""
    min_votes = min_votes or CONSENSUS_MIN_VOTES
    _, count = count_votes(votes)
    return count >= min_votes


def weighted_average_prob(runs: list[dict], weights: dict[str, float]) -> float:
    """Weighted average of probability estimates across runs.

    Each run dict has: {"model_key": str, "prob": float}
    """
    numerator = 0.0
    denominator = 0.0
    for run in runs:
        w = weights.get(run["model_key"], 1.0)
        numerator += w * run["prob"]
        denominator += w
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def apply_stability_bonus(weight: float, std_dev: float) -> float:
    """Apply stability multiplier based on temperature sweep std dev."""
    if std_dev < 0.03:
        return round(weight * 1.2, 4)
    elif std_dev > 0.10:
        return round(weight * 0.8, 4)
    return weight


def majority_vote(values: list[str], default: str = "medium") -> str:
    """Return the most common value. Ties broken toward default."""
    if not values:
        return default
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    winners = [v for v, c in counts.items() if c == max_count]
    if default in winners:
        return default
    return winners[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_consensus.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/consensus.py tests/test_ensemble_consensus.py
git commit -m "feat(ensemble): consensus gate with vote normalization and weighted averaging"
```

---

### Task 7: Adversarial Challenger (`ensemble/challenger.py`)

**Files:**
- Create: `ensemble/challenger.py`
- Create: `tests/test_ensemble_challenger.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_challenger.py
import json
from unittest.mock import patch, MagicMock
from ensemble.challenger import build_challenge_prompt, parse_challenge_response, run_challenge


def test_build_challenge_prompt_includes_briefing():
    prompt = build_challenge_prompt(
        briefing="NYY@BOS game data...",
        ensemble_predictions={"moneyline": {"home_win_prob": 0.58}},
        model_agreement={"moneyline": "5/6 models say home, avg edge 7.2%"},
    )
    assert "NYY@BOS" in prompt
    assert "adversarial" in prompt.lower()


def test_parse_challenge_approve():
    raw = json.dumps({
        "challenges": [
            {"bet_type": "moneyline", "verdict": "approve", "reasoning": "looks solid", "flaw_found": None}
        ]
    })
    result = parse_challenge_response(raw)
    assert result is not None
    assert result["moneyline"] == "approve"


def test_parse_challenge_kill():
    raw = json.dumps({
        "challenges": [
            {"bet_type": "moneyline", "verdict": "kill", "reasoning": "bad reasoning", "flaw_found": "overfit"},
            {"bet_type": "total", "verdict": "approve", "reasoning": "fine", "flaw_found": None},
        ]
    })
    result = parse_challenge_response(raw)
    assert result["moneyline"] == "kill"
    assert result["total"] == "approve"


def test_parse_challenge_invalid_json():
    result = parse_challenge_response("not json")
    assert result is None


@patch("ensemble.challenger.run_single_model")
def test_run_challenge_success(mock_runner):
    mock_runner.return_value = {
        "model_key": "claude",
        "parsed": {
            "challenges": [
                {"bet_type": "moneyline", "verdict": "approve", "reasoning": "ok", "flaw_found": None}
            ]
        },
        "temperature": 0.7,
        "cost": 0.05,
    }
    verdicts, cost = run_challenge(
        briefing="test",
        ensemble_predictions={},
        model_agreement={},
        surviving_slots=["moneyline"],
    )
    assert verdicts["moneyline"] == "approve"
    assert cost > 0


@patch("ensemble.challenger.run_single_model")
def test_run_challenge_failure_approves_all(mock_runner):
    mock_runner.return_value = None
    verdicts, cost = run_challenge(
        briefing="test",
        ensemble_predictions={},
        model_agreement={},
        surviving_slots=["moneyline", "total"],
    )
    # On failure, all slots are approved (challenger can't block)
    assert verdicts["moneyline"] == "approve"
    assert verdicts["total"] == "approve"
    assert cost == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_challenger.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# ensemble/challenger.py
"""Adversarial challenge pass via Claude Sonnet 4."""
import json
from ensemble.models import get_challenger_model
from ensemble.runner import run_single_model
from simulate import parse_simulation_result

CHALLENGER_SYSTEM_PROMPT = """You are an adversarial analyst reviewing an MLB betting ensemble's output.
Your job is to find flaws, not confirm. Kill bets that don't hold up.

For each bet that passed consensus, respond in valid JSON only:
{
  "challenges": [
    {
      "bet_type": "moneyline",
      "verdict": "approve" or "kill",
      "reasoning": "...",
      "flaw_found": null or "description of flaw"
    }
  ]
}
No markdown, no backticks, no preamble. JSON only."""


def build_challenge_prompt(briefing: str, ensemble_predictions: dict,
                           model_agreement: dict) -> str:
    """Build the user prompt for the adversarial challenger."""
    agreement_lines = "\n".join(
        f"- {slot}: {desc}" for slot, desc in model_agreement.items()
    )
    return f"""BRIEFING:
{briefing}

ENSEMBLE PREDICTION:
{json.dumps(ensemble_predictions, indent=2)}

MODEL AGREEMENT:
{agreement_lines}

Review each bet that passed consensus. Find the weakest reasoning. Should any bet be killed?"""


def parse_challenge_response(raw: str) -> dict | None:
    """Parse challenger response into {bet_type: "approve"|"kill"} dict."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if "challenges" not in data:
        return None

    return {
        c["bet_type"]: c["verdict"]
        for c in data["challenges"]
        if "bet_type" in c and "verdict" in c
    }


def run_challenge(briefing: str, ensemble_predictions: dict,
                  model_agreement: dict,
                  surviving_slots: list[str]) -> tuple[dict, float]:
    """Run adversarial challenge. Returns (verdicts_dict, cost).

    On failure, all surviving slots are approved (challenger can't block).
    """
    model = get_challenger_model()
    if not model:
        return {slot: "approve" for slot in surviving_slots}, 0

    prompt = build_challenge_prompt(briefing, ensemble_predictions, model_agreement)

    result = run_single_model(
        model_key="claude_challenger",
        model_id=model["id"],
        briefing=prompt,
        temperature=model["default_temp"],
        max_tokens=model["max_tokens"],
        timeout=model["timeout"],
        input_price=model["input_price"],
        output_price=model["output_price"],
        system_prompt=CHALLENGER_SYSTEM_PROMPT,
    )

    if not result:
        print("[ensemble] Challenger failed, approving all bets")
        return {slot: "approve" for slot in surviving_slots}, 0

    # The challenger's parsed response is the challenge JSON (it went through
    # parse_simulation_result which is just json.loads with fence stripping)
    raw_content = json.dumps(result["parsed"]) if isinstance(result["parsed"], dict) else str(result["parsed"])
    verdicts = parse_challenge_response(raw_content)

    if not verdicts:
        print("[ensemble] Challenger response unparseable, approving all bets")
        return {slot: "approve" for slot in surviving_slots}, result["cost"]

    # Fill in any missing slots as approved
    for slot in surviving_slots:
        if slot not in verdicts:
            verdicts[slot] = "approve"

    return verdicts, result["cost"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_challenger.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/challenger.py tests/test_ensemble_challenger.py
git commit -m "feat(ensemble): adversarial challenger with Claude Sonnet 4"
```

---

### Task 8: Orchestrator (`ensemble/orchestrator.py`)

This is the core — it wires Phase 1, Phase 2, and Phase 3 together.

**Files:**
- Create: `ensemble/orchestrator.py`
- Create: `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ensemble_orchestrator.py
import copy
from unittest.mock import patch, MagicMock
from ensemble.orchestrator import (
    run_phase1, classify_consensus, run_phase2,
    reclassify_consensus, build_ensemble_result, run_ensemble,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS


def _make_phase1_results(overrides=None):
    """Create 6 model results for Phase 1 with optional per-model overrides."""
    models = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
    results = []
    for m in models:
        pred = copy.deepcopy(MOCK_PREDICTION)
        if overrides and m in overrides:
            for section, updates in overrides[m].items():
                if section in pred["predictions"]:
                    pred["predictions"][section].update(updates)
        results.append({
            "model_key": m,
            "parsed": pred,
            "temperature": 0.7,
            "cost": 0.01,
        })
    return results


@patch("ensemble.orchestrator.run_single_model")
def test_run_phase1_returns_results(mock_runner):
    mock_runner.return_value = {
        "model_key": "kimi",
        "parsed": copy.deepcopy(MOCK_PREDICTION),
        "temperature": 0.7,
        "cost": 0.01,
    }
    results, cost = run_phase1("test briefing")
    assert len(results) > 0
    assert cost > 0


def test_classify_consensus_strong():
    results = _make_phase1_results()
    # All 6 say moneyline home → strong consensus
    classification = classify_consensus(results, MOCK_ODDS)
    assert classification["moneyline"]["level"] in ("strong", "soft")


def test_classify_consensus_no_consensus():
    overrides = {
        "kimi": {"moneyline": {"value_side": "home"}},
        "claude": {"moneyline": {"value_side": "away"}},
        "gpt4o": {"moneyline": {"value_side": "home"}},
        "gemini": {"moneyline": {"value_side": "away"}},
        "deepseek": {"moneyline": {"value_side": "none"}},
        "maverick": {"moneyline": {"value_side": "none"}},
    }
    results = _make_phase1_results(overrides)
    classification = classify_consensus(results, MOCK_ODDS)
    assert classification["moneyline"]["level"] == "none"


def test_reclassify_consensus_uses_majority_of_runs():
    """After Phase 2, models with multiple runs get one vote based on majority."""
    base = _make_phase1_results()
    # Add extra runs for kimi that flip to "away" — but kimi's original was "home"
    # 1 home + 2 away = majority is away
    for _ in range(2):
        pred = copy.deepcopy(MOCK_PREDICTION)
        pred["predictions"]["moneyline"]["value_side"] = "away"
        base.append({"model_key": "kimi", "parsed": pred, "temperature": 0.3, "cost": 0.01})
    classification = reclassify_consensus(base, MOCK_ODDS)
    # kimi now votes away (2 away > 1 home), other 5 still vote home → 5 home
    assert classification["moneyline"]["count"] == 5


@patch("ensemble.orchestrator.run_single_model")
@patch("ensemble.orchestrator.run_challenge")
def test_run_ensemble_returns_predictions(mock_challenge, mock_runner):
    mock_runner.return_value = {
        "model_key": "kimi",
        "parsed": copy.deepcopy(MOCK_PREDICTION),
        "temperature": 0.7,
        "cost": 0.01,
    }
    mock_challenge.return_value = ({"moneyline": "approve", "total": "approve"}, 0.05)

    result = run_ensemble("test briefing")
    assert result is not None
    assert "predictions" in result
    assert "ensemble_meta" in result
    assert result["ensemble_runs"] == 1


@patch("ensemble.orchestrator.run_single_model")
def test_run_ensemble_fewer_than_3_models_returns_none(mock_runner):
    # Only 2 models succeed
    call_count = [0]
    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            return {
                "model_key": "kimi",
                "parsed": copy.deepcopy(MOCK_PREDICTION),
                "temperature": 0.7,
                "cost": 0.01,
            }
        return None

    mock_runner.side_effect = side_effect
    result = run_ensemble("test briefing")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# ensemble/orchestrator.py
"""Adaptive 3-phase dispatch: quick pass → expansion → challenge."""
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import CONSENSUS_MIN_VOTES, MAX_CALLS_PER_GAME
from ensemble.models import get_panel_models, MODEL_REGISTRY
from ensemble.runner import run_single_model
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus, majority_vote,
    BET_SLOT_FIELDS,
)
from ensemble.weights import load_weights, BET_SLOTS
from ensemble.challenger import run_challenge
from ensemble.logger import log_model_prediction


def run_phase1(briefing: str) -> tuple[list[dict], float]:
    """Phase 1: Hit all 6 models in parallel at default temp. Returns (results, total_cost)."""
    panel = get_panel_models()
    results = []
    total_cost = 0.0

    with ThreadPoolExecutor(max_workers=len(panel)) as executor:
        futures = {}
        for key, model in panel:
            f = executor.submit(
                run_single_model,
                model_key=key,
                model_id=model["id"],
                briefing=briefing,
                temperature=model["default_temp"],
                max_tokens=model["max_tokens"],
                timeout=model["timeout"],
                input_price=model["input_price"],
                output_price=model["output_price"],
            )
            futures[f] = key

        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
                total_cost += result["cost"]

    return results, total_cost


def classify_consensus(results: list[dict], odds: dict) -> dict:
    """Classify consensus level per bet slot from Phase 1 results.

    Returns: {slot: {"level": "strong"|"soft"|"none", "side": str|None, "count": int, "votes": dict}}
    """
    classification = {}

    for slot in BET_SLOTS:
        votes = {}
        for r in results:
            votes[r["model_key"]] = extract_vote(r["parsed"], slot, odds)

        side, count = count_votes(votes)
        n_voting = sum(1 for v in votes.values() if v is not None)

        if count >= 5:
            level = "strong"
        elif count >= CONSENSUS_MIN_VOTES:
            level = "soft"
        else:
            level = "none"

        classification[slot] = {
            "level": level,
            "side": side,
            "count": count,
            "votes": votes,
        }

    return classification


def run_phase2(briefing: str, results: list[dict], classification: dict,
               odds: dict) -> tuple[list[dict], float]:
    """Phase 2: Temperature expansion on contested bet slots.

    Expands disagreeing models (3 temps × 2 runs) and confirming models (2 more at default).
    """
    soft_slots = [s for s, c in classification.items() if c["level"] == "soft"]
    if not soft_slots:
        return results, 0.0

    # Find which models need expansion for any soft slot
    models_to_expand = set()
    models_to_confirm = set()
    for slot in soft_slots:
        majority_side = classification[slot]["side"]
        for model_key, vote in classification[slot]["votes"].items():
            if vote is None:
                continue
            if vote != majority_side:
                models_to_expand.add(model_key)
            else:
                models_to_confirm.add(model_key)

    # Don't expand models that are already expanded
    models_to_confirm -= models_to_expand

    total_cost = 0.0
    new_results = list(results)  # keep Phase 1 results

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = []

        for model_key in models_to_expand:
            model = MODEL_REGISTRY.get(model_key)
            if not model:
                continue
            for temp in [0.3, 0.7, 1.0]:
                for run_idx in range(2):
                    f = executor.submit(
                        run_single_model,
                        model_key=model_key,
                        model_id=model["id"],
                        briefing=briefing,
                        temperature=temp,
                        max_tokens=model["max_tokens"],
                        timeout=model["timeout"],
                        input_price=model["input_price"],
                        output_price=model["output_price"],
                    )
                    futures.append(f)

        for model_key in models_to_confirm:
            model = MODEL_REGISTRY.get(model_key)
            if not model:
                continue
            for run_idx in range(2):
                f = executor.submit(
                    run_single_model,
                    model_key=model_key,
                    model_id=model["id"],
                    briefing=briefing,
                    temperature=model["default_temp"],
                    max_tokens=model["max_tokens"],
                    timeout=model["timeout"],
                    input_price=model["input_price"],
                    output_price=model["output_price"],
                )
                futures.append(f)

        for future in as_completed(futures):
            result = future.result()
            if result:
                new_results.append(result)
                total_cost += result["cost"]

    return new_results, total_cost


def _get_model_majority_vote(model_key: str, results: list[dict],
                             slot: str, odds: dict) -> str | None:
    """Determine a model's vote from the majority of its runs."""
    votes = []
    for r in results:
        if r["model_key"] == model_key:
            v = extract_vote(r["parsed"], slot, odds)
            if v is not None:
                votes.append(v)
    if not votes:
        return None
    counts = {}
    for v in votes:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get)


def reclassify_consensus(results: list[dict], odds: dict) -> dict:
    """Re-classify consensus after Phase 2 using per-model majority votes."""
    model_keys = list(set(r["model_key"] for r in results))
    classification = {}

    for slot in BET_SLOTS:
        votes = {}
        for mk in model_keys:
            votes[mk] = _get_model_majority_vote(mk, results, slot, odds)

        side, count = count_votes(votes)

        if count >= 5:
            level = "strong"
        elif count >= CONSENSUS_MIN_VOTES:
            level = "soft"
        else:
            level = "none"

        classification[slot] = {
            "level": level,
            "side": side,
            "count": count,
            "votes": votes,
        }

    return classification


def _extract_prob_for_slot(parsed: dict, slot: str) -> float | None:
    """Extract the primary probability field for a bet slot."""
    preds = parsed.get("predictions", {})
    if slot == "moneyline":
        return preds.get("moneyline", {}).get("home_win_prob")
    elif slot == "run_line":
        return preds.get("run_line", {}).get("favorite_cover_prob")
    elif slot == "total":
        return preds.get("total", {}).get("over_prob")
    elif slot == "first_5_ml":
        return preds.get("first_5", {}).get("f5_home_win_prob")
    elif slot == "first_5_total":
        return preds.get("first_5", {}).get("f5_projected_total")
    return None


def build_ensemble_result(results: list[dict], classification: dict,
                          weights: dict, killed_by_challenger: list[str]) -> dict:
    """Build the final ensemble output dict from all runs."""
    # Start from the highest-weighted model's Phase 1 result
    phase1_results = [r for r in results if r["temperature"] == 0.7]
    if not phase1_results:
        phase1_results = results

    best_model = max(
        phase1_results,
        key=lambda r: sum(weights.get(r["model_key"], {}).get(s, 1.0) for s in BET_SLOTS),
    )
    base = best_model["parsed"].copy()
    import copy
    base = copy.deepcopy(best_model["parsed"])

    preds = base.get("predictions", {})

    # Weighted average for probability fields per surviving slot
    prob_fields = {
        "moneyline": [("home_win_prob", "moneyline"), ("away_win_prob", "moneyline")],
        "run_line": [("favorite_cover_prob", "run_line")],
        "total": [("over_prob", "total"), ("under_prob", "total"), ("projected_total", "total")],
        "first_5": [
            ("f5_home_win_prob", "first_5_ml"), ("f5_away_win_prob", "first_5_ml"),
            ("f5_projected_total", "first_5_total"),
        ],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for field_name, weight_slot in fields:
            runs_data = []
            for r in results:
                val = r["parsed"].get("predictions", {}).get(section, {}).get(field_name)
                if val is not None:
                    w = weights.get(r["model_key"], {}).get(weight_slot, 1.0)
                    runs_data.append({"model_key": r["model_key"], "prob": float(val)})
            if runs_data:
                slot_weights = {
                    r["model_key"]: weights.get(r["model_key"], {}).get(weight_slot, 1.0)
                    for r in runs_data
                }
                preds[section][field_name] = weighted_average_prob(runs_data, slot_weights)

    # Weighted average for predicted_score
    for score_key in ["home", "away"]:
        vals = []
        for r in results:
            v = r["parsed"].get("predictions", {}).get("predicted_score", {}).get(score_key)
            if v is not None:
                vals.append(float(v))
        if vals:
            preds.setdefault("predicted_score", {})[score_key] = round(sum(vals) / len(vals))

    # Confidence: majority vote
    for section in ["moneyline", "run_line", "total", "first_5"]:
        if section in preds:
            confs = [
                r["parsed"].get("predictions", {}).get(section, {}).get("confidence")
                for r in results
                if r["parsed"].get("predictions", {}).get(section, {}).get("confidence")
            ]
            if confs:
                preds[section]["confidence"] = majority_vote(confs)

    # Kill slots that didn't pass consensus
    killed_by_consensus = []
    for slot, info in classification.items():
        if info["level"] == "none":
            killed_by_consensus.append(slot)

    # Kill slots killed by challenger
    all_killed = set(killed_by_consensus + killed_by_challenger)

    # Remove killed slots from predictions
    for slot in all_killed:
        if slot == "moneyline":
            preds.pop("moneyline", None)
        elif slot == "run_line":
            preds.pop("run_line", None)
        elif slot == "total":
            preds.pop("total", None)
        elif slot == "first_5_ml":
            for key in ["f5_home_win_prob", "f5_away_win_prob", "f5_ml_value"]:
                preds.get("first_5", {}).pop(key, None)
        elif slot == "first_5_total":
            for key in ["f5_projected_total", "f5_total_value"]:
                preds.get("first_5", {}).pop(key, None)

    # If both F5 sub-bets killed, remove entire first_5
    if "first_5_ml" in all_killed and "first_5_total" in all_killed:
        preds.pop("first_5", None)

    base["predictions"] = preds
    base["ensemble_runs"] = 1

    # Model contributions count
    contributions = {}
    for r in results:
        contributions[r["model_key"]] = contributions.get(r["model_key"], 0) + 1

    total_cost = sum(r["cost"] for r in results)

    base["ensemble_meta"] = {
        "total_calls": len(results),
        "phase_reached": 2 if any(c["level"] == "soft" for c in classification.values()) else 1,
        "consensus": {s: info["count"] for s, info in classification.items()},
        "bets_killed_by_consensus": killed_by_consensus,
        "bets_killed_by_challenger": killed_by_challenger,
        "model_contributions": contributions,
        "cost_usd": round(total_cost, 4),
    }

    return base


def run_ensemble(briefing: str, odds: dict = None) -> dict | None:
    """Run the full adaptive ensemble pipeline. Returns prediction dict or None."""
    print("[ensemble] Phase 1: Quick pass (6 models)...")
    results, phase1_cost = run_phase1(briefing)

    if len(results) < CONSENSUS_MIN_VOTES:
        print(f"[ensemble] Only {len(results)} models succeeded, need {CONSENSUS_MIN_VOTES}")
        return None

    # Load weights (cached for this game)
    weights = load_weights()

    # Use empty odds if not provided (run_line normalization won't work, but won't crash)
    odds = odds or {}

    # Classify consensus
    classification = classify_consensus(results, odds)

    has_soft = any(c["level"] == "soft" for c in classification.values())
    has_surviving = any(c["level"] in ("strong", "soft") for c in classification.values())

    if not has_surviving:
        print("[ensemble] No consensus on any bet slot, no bets")
        return None

    # Phase 2: Expand if any soft consensus
    total_cost = phase1_cost
    if has_soft:
        call_count = len(results)
        remaining_budget = MAX_CALLS_PER_GAME - call_count - 1  # reserve 1 for challenger
        if remaining_budget > 0:
            print(f"[ensemble] Phase 2: Expanding contested models...")
            results, phase2_cost = run_phase2(briefing, results, classification, odds)
            total_cost += phase2_cost
            # Reclassify after expansion
            classification = reclassify_consensus(results, odds)

    # Apply stability bonus to weights for models with multi-temp runs
    for slot in BET_SLOTS:
        model_temps = {}  # model_key -> list of (temp, prob)
        for r in results:
            prob = _extract_prob_for_slot(r["parsed"], slot)
            if prob is not None:
                model_temps.setdefault(r["model_key"], []).append((r["temperature"], prob))
        for mk, temps_probs in model_temps.items():
            unique_temps = set(t for t, _ in temps_probs)
            if len(unique_temps) >= 2:
                probs = [p for _, p in temps_probs]
                std = statistics.stdev(probs) if len(probs) > 1 else 0
                base_w = weights.get(mk, {}).get(slot, 1.0)
                weights.setdefault(mk, {})[slot] = apply_stability_bonus(base_w, std)

    # Log all model predictions to CSV for weight evolution
    for r in results:
        for slot in BET_SLOTS:
            prob = _extract_prob_for_slot(r["parsed"], slot)
            vote = extract_vote(r["parsed"], slot, odds)
            if prob is not None and vote is not None:
                log_model_prediction(
                    date="",  # filled by caller context if available
                    game="",  # filled by caller context if available
                    model=r["model_key"],
                    bet_type=slot,
                    side=vote,
                    sim_prob=prob,
                    market_prob=0.0,  # not available at this layer
                    edge=0.0,
                    temperature=r["temperature"],
                    run_index=0,
                )

    # Determine surviving slots for challenger
    surviving_slots = [
        s for s, c in classification.items()
        if c["level"] in ("strong", "soft")
    ]

    if not surviving_slots:
        print("[ensemble] No consensus after Phase 2")
        return None

    # Phase 3: Adversarial challenge
    print(f"[ensemble] Phase 3: Adversarial challenge on {len(surviving_slots)} slots...")
    model_agreement = {}
    for slot in surviving_slots:
        info = classification[slot]
        model_agreement[slot] = f"{info['count']}/{len(info['votes'])} models say {info['side']}"

    # Build preliminary predictions for the challenger to review
    prelim = build_ensemble_result(results, classification, weights, [])

    verdicts, challenge_cost = run_challenge(
        briefing=briefing,
        ensemble_predictions=prelim.get("predictions", {}),
        model_agreement=model_agreement,
        surviving_slots=surviving_slots,
    )
    total_cost += challenge_cost

    killed_by_challenger = [s for s, v in verdicts.items() if v == "kill"]
    if killed_by_challenger:
        print(f"[ensemble] Challenger killed: {killed_by_challenger}")

    # Build final result
    result = build_ensemble_result(results, classification, weights, killed_by_challenger)
    result["ensemble_meta"]["cost_usd"] = round(total_cost, 4)

    surviving_after = [s for s in surviving_slots if s not in killed_by_challenger]
    if not surviving_after:
        print("[ensemble] All bets killed by challenger")
        return None

    print(f"[ensemble] Done. {len(surviving_after)} bet slots surviving. Cost: ${total_cost:.4f}")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ensemble_orchestrator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/orchestrator.py tests/test_ensemble_orchestrator.py
git commit -m "feat(ensemble): adaptive 3-phase orchestrator"
```

---

### Task 9: Wire `run_ensemble` Export + `simulate.py` + `main.py` Integration

**Files:**
- Modify: `ensemble/__init__.py`
- Modify: `simulate.py:127-134`
- Create: `tests/test_ensemble_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_ensemble_integration.py
import copy
from unittest.mock import patch, MagicMock
from simulate import run_mirofish
from tests.ensemble_fixtures import MOCK_PREDICTION


@patch("ensemble.orchestrator.run_single_model")
@patch("ensemble.orchestrator.run_challenge")
def test_run_mirofish_uses_ensemble(mock_challenge, mock_runner):
    mock_runner.return_value = {
        "model_key": "kimi",
        "parsed": copy.deepcopy(MOCK_PREDICTION),
        "temperature": 0.7,
        "cost": 0.01,
    }
    mock_challenge.return_value = ({"moneyline": "approve", "total": "approve"}, 0.05)

    result = run_mirofish("test briefing")
    assert result is not None
    assert "predictions" in result


@patch("ensemble.orchestrator.run_ensemble", return_value=None)
@patch("simulate.run_plan_b")
def test_run_mirofish_falls_back_to_plan_b(mock_plan_b, mock_ensemble):
    mock_plan_b.return_value = copy.deepcopy(MOCK_PREDICTION)
    result = run_mirofish("test briefing")
    assert result is not None
    mock_plan_b.assert_called_once()


@patch("ensemble.orchestrator.run_ensemble", side_effect=Exception("boom"))
@patch("simulate.run_plan_b")
def test_run_mirofish_catches_ensemble_exception(mock_plan_b, mock_ensemble):
    mock_plan_b.return_value = copy.deepcopy(MOCK_PREDICTION)
    result = run_mirofish("test briefing")
    assert result is not None
    mock_plan_b.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ensemble_integration.py -v`
Expected: FAIL (ensemble not wired up yet)

- [ ] **Step 3: Wire up ensemble/__init__.py**

```python
# ensemble/__init__.py
"""Multi-model ensemble prediction engine."""
from ensemble.orchestrator import run_ensemble

__all__ = ["run_ensemble"]
```

- [ ] **Step 4: Update simulate.py:run_mirofish()**

Replace `run_mirofish` function (lines 127-134) with:

```python
def run_mirofish(briefing: str, runs: int = 3, odds: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    Args:
        odds: Game odds dict for run_line consensus normalization.
              Passed through to ensemble for vote normalization.
    """
    try:
        from ensemble import run_ensemble
        result = run_ensemble(briefing, odds=odds)
        if result:
            return result
        print("[simulate] Ensemble returned no result, falling back to Plan B")
    except Exception as e:
        print(f"[simulate] Ensemble failed ({e}), falling back to Plan B")
    return run_plan_b(briefing, runs=runs)
```

- [ ] **Step 4b: Update main.py call sites to pass odds**

In `main.py`, update the two `run_mirofish` calls:

Line 155: `result = run_mirofish(brief, runs=3)` → `result = run_mirofish(brief, runs=3, odds=game_data["odds"])`

Line 248: `result = run_mirofish(brief, runs=3)` → `result = run_mirofish(brief, runs=3, odds=game_data["odds"])`

- [ ] **Step 5: Run integration tests**

Run: `pytest tests/test_ensemble_integration.py -v`
Expected: All PASS

- [ ] **Step 6: Run ALL tests to verify nothing broke**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add ensemble/__init__.py simulate.py tests/test_ensemble_integration.py
git commit -m "feat: wire ensemble into run_mirofish() with Plan B fallback"
```

---

### Task 10: Self-Optimizer Model Weight Updates

**Files:**
- Modify: `agents/self_optimizer.py`
- Modify: `tests/test_self_optimizer.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_self_optimizer.py`:

```python
import json
import os
import tempfile
import pandas as pd
from agents.self_optimizer import compute_model_brier_scores, update_model_weights


def test_compute_model_brier_scores():
    preds_df = pd.DataFrame([
        {"model": "kimi", "bet_type": "moneyline", "sim_prob": 0.60, "side": "home"},
        {"model": "kimi", "bet_type": "moneyline", "sim_prob": 0.55, "side": "home"},
        {"model": "gpt4o", "bet_type": "moneyline", "sim_prob": 0.70, "side": "home"},
    ])
    bets_df = pd.DataFrame([
        {"bet_type": "moneyline", "result": "W", "date": "2026-03-28", "game": "NYY@BOS"},
        {"bet_type": "moneyline", "result": "L", "date": "2026-03-29", "game": "LAD@SF"},
    ])
    scores = compute_model_brier_scores(preds_df, bets_df)
    assert "kimi" in scores
    assert "moneyline" in scores["kimi"]


def test_update_model_weights_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights_path = os.path.join(tmpdir, "weights.json")
        brier_scores = {
            "kimi": {"moneyline": 0.20, "run_line": 0.25},
            "gpt4o": {"moneyline": 0.15, "run_line": 0.30},
        }
        update_model_weights(brier_scores, weights_path)
        assert os.path.exists(weights_path)
        with open(weights_path) as f:
            weights = json.load(f)
        # Lower brier score → higher weight
        assert weights["gpt4o"]["moneyline"] > weights["kimi"]["moneyline"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_self_optimizer.py::test_compute_model_brier_scores -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add weight update functions to self_optimizer.py**

At the end of `agents/self_optimizer.py` (before `@click.command`), add:

```python
def compute_model_brier_scores(preds_df: pd.DataFrame, bets_df: pd.DataFrame) -> dict:
    """Compute per-model, per-bet-type Brier scores from prediction logs and results."""
    if preds_df.empty or bets_df.empty:
        return {}

    scores = {}
    for model in preds_df["model"].unique():
        model_preds = preds_df[preds_df["model"] == model]
        scores[model] = {}
        for bt in model_preds["bet_type"].unique():
            bt_preds = model_preds[model_preds["bet_type"] == bt]
            # Match predictions to actual results
            # Brier score = mean((predicted_prob - actual_outcome)^2)
            brier_values = []
            for _, pred in bt_preds.iterrows():
                # Find matching settled bet
                matching = bets_df[
                    (bets_df["bet_type"] == bt) &
                    (bets_df["result"].isin(["W", "L"]))
                ]
                if matching.empty:
                    continue
                # Use average outcome for this bet type as proxy
                outcome = 1.0 if matching.iloc[0]["result"] == "W" else 0.0
                brier_values.append((pred["sim_prob"] - outcome) ** 2)

            if brier_values:
                scores[model][bt] = round(sum(brier_values) / len(brier_values), 4)

    return scores


def update_model_weights(brier_scores: dict, weights_path: str = None) -> None:
    """Update model weights based on Brier scores. Lower Brier = higher weight."""
    from ensemble.weights import load_weights, save_weights, BET_SLOTS

    weights = load_weights(weights_path)

    for slot in BET_SLOTS:
        slot_scores = {}
        for model, scores in brier_scores.items():
            if slot in scores:
                slot_scores[model] = max(scores[slot], 0.01)  # floor at 0.01

        if not slot_scores:
            continue

        # Raw weights = 1/brier, normalized to sum to num_models
        raw = {m: 1.0 / s for m, s in slot_scores.items()}
        total = sum(raw.values())
        n = len(raw)
        for model, raw_w in raw.items():
            weights.setdefault(model, {})[slot] = round(raw_w / total * n, 4)

    save_weights(weights, weights_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_self_optimizer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/self_optimizer.py tests/test_self_optimizer.py
git commit -m "feat(optimizer): model weight updates based on Brier scores"
```

---

### Task 11: Final Integration Test + Cleanup

**Files:**
- All files

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 2: Verify the ensemble package structure**

Run: `find ensemble/ -name "*.py" | sort`

Expected:
```
ensemble/__init__.py
ensemble/challenger.py
ensemble/consensus.py
ensemble/logger.py
ensemble/models.py
ensemble/orchestrator.py
ensemble/runner.py
ensemble/weights.py
```

- [ ] **Step 3: Verify config.py has all ensemble settings**

Run: `grep -n "ENSEMBLE\|CONSENSUS\|MAX_CALLS\|MODEL_WEIGHTS\|MODEL_PREDICTIONS\|first_5_ml\|first_5_total" config.py`

Expected to see all new config values.

- [ ] **Step 4: Verify simulate.py delegates correctly**

Run: `grep -A 10 "def run_mirofish" simulate.py`

Expected to see ensemble import with try/except fallback.

- [ ] **Step 5: Remove the now-unused MIROFISH_AGENTS config**

In `config.py`, remove:
```python
MIROFISH_AGENTS = 512
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: complete multi-model ensemble integration

6-model ensemble (Kimi, Claude, GPT-4o, Gemini, DeepSeek R1, Llama 4 Maverick)
with adaptive dispatch, consensus gating, weighted averaging, adversarial
challenge, and per-model weight evolution via Brier scores."
```
