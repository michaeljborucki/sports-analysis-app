# Multi-Model Ensemble Simulation — Design Spec

**Date:** 2026-03-18
**Status:** Approved
**Goal:** Replace the `run_mirofish()` stub with a multi-model ensemble that fans predictions across 6 LLMs, applies adaptive dispatch, consensus gating, weighted averaging, and adversarial challenge to produce higher-quality probability estimates for MLB bet edge detection.

---

## 1. Package Structure

```
ensemble/
├── __init__.py          # exports run_ensemble()
├── models.py            # model registry (IDs, temps, cost, roles)
├── runner.py            # fires individual LLM calls via OpenRouter
├── orchestrator.py      # adaptive dispatch: quick pass → expand if split
├── consensus.py         # consensus gate + weighted averaging
├── challenger.py        # adversarial pass (Claude Sonnet 4)
└── weights.py           # model weight storage + update logic
```

`simulate.py` stays untouched except `run_mirofish()` delegates to `ensemble.run_ensemble()`. Plan B screen pass is unaffected.

---

## 2. Model Roster

| Key | OpenRouter ID | Role | Input/1M | Output/1M | Context |
|---|---|---|---|---|---|
| `kimi` | `moonshotai/kimi-k2.5` | panel | $0.45 | $2.25 | 262K |
| `claude` | `anthropic/claude-sonnet-4` | panel + challenger | $3.00 | $15.00 | 200K |
| `gpt4o` | `openai/gpt-4o` | panel | $2.50 | $10.00 | 128K |
| `gemini` | `google/gemini-2.5-flash` | panel | $0.30 | $2.50 | 1M |
| `deepseek` | `deepseek/deepseek-r1` | panel | $0.70 | $2.50 | 64K |
| `maverick` | `meta-llama/llama-4-maverick` | panel | $0.15 | $0.60 | 1M |

All models accessed through OpenRouter using the existing `OPENROUTER_API_KEY` and `OPENROUTER_BASE_URL`.

Claude Sonnet 4 has dual role: participates in Phase 1 as a panel member, then acts as adversarial challenger in Phase 3.

---

## 3. Panel Model Prompts

All 6 panel models receive the same `MLB_SYSTEM_PROMPT` from `simulate.py` (lines 7-63) and the same briefing string. No per-model prompt variations. The diversity comes from different model architectures, training data, and temperature settings.

### DeepSeek R1 Handling

DeepSeek R1 produces chain-of-thought `<think>...</think>` blocks before its JSON output. The `runner.py` parser must strip thinking blocks before passing to `parse_simulation_result()`:

```python
def strip_thinking(raw: str) -> str:
    """Remove <think>...</think> blocks from DeepSeek R1 output."""
    import re
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    # Fallback: if no valid JSON after stripping, find first '{' character
    if text and not text.startswith('{'):
        idx = text.find('{')
        if idx != -1:
            text = text[idx:]
    return text
```

This is applied before the existing `parse_simulation_result()` which already handles markdown fences.

---

## 4. Adaptive Dispatch Flow

### Phase 1: Quick Pass (6 calls)

- Hit all 6 models once at temperature 0.7
- Parse predictions into the standard `predictions` dict shape
- For each of the **5 bet slots** independently, count how many models agree on the value side (excluding "none" votes)

Decision per bet slot:
- **5-6 agree → Strong consensus** → Weighted average → Phase 3
- **3-4 agree → Soft consensus** → Phase 2 (expand contested models)
- **0-2 agree → No consensus** → No bet on this slot. Stop.

### Phase 2: Temperature Expansion (~12-18 calls)

- For each model that **disagrees** with majority: run at temps 0.3, 0.7, 1.0 × 2 runs each (6 calls per model)
- For each model that **agrees** with majority: run 2 more at temp 0.7 (confirmation)
- Recalculate weighted average with all runs
- Re-check consensus gate: **each model gets one vote** (determined by the majority of that model's own runs). Per-run voting is NOT used — a model expanded to 7 runs still gets 1 vote.

### Phase 3: Adversarial Challenge (1 call)

- Only fires on bet slots that survived the consensus gate
- Claude Sonnet 4 receives: original briefing + ensemble predictions + per-model breakdown
- Tasked with finding flaws and issuing approve/kill per bet slot
- Challenger can only kill, never add bets

**Total calls:** 6 (easy games with strong consensus or no consensus) to ~25 (contested games) + 1 challenger. Max budget: 50 calls per game.

---

## 5. Consensus Gate & Weighted Averaging

### Bet Slots and Value Side Vocabulary

The consensus gate operates on **5 independent bet slots**, not 4. The existing JSON schema defines these value fields:

| Bet Slot | Schema Field | Possible Votes | Normalized To |
|---|---|---|---|
| `moneyline` | `predictions.moneyline.value_side` | `home`, `away`, `none` | `home`, `away` |
| `run_line` | `predictions.run_line.value_side` | `favorite_rl`, `underdog_rl`, `none` | **Normalized to absolute side**: `home_rl`, `away_rl` based on which team has the negative spread in the odds data |
| `total` | `predictions.total.value_side` | `over`, `under`, `none` | `over`, `under` |
| `first_5_ml` | `predictions.first_5.f5_ml_value` | `home`, `away`, `none` | `home`, `away` |
| `first_5_total` | `predictions.first_5.f5_total_value` | `over`, `under`, `none` | `over`, `under` |

**Run line normalization:** The consensus module receives the game odds data to determine which team is the favorite (negative spread). If a model says `favorite_rl` and home has -1.5, the normalized vote is `home_rl`. This prevents two models from appearing to agree when they've identified different teams as the favorite.

**First 5 split:** `first_5` contains two independent sub-bets (moneyline and total). Each is gated independently. A game can have an F5 ML bet without an F5 total bet or vice versa.

### Consensus Determination

Per bet slot independently:
1. Each model gets **one vote** (in Phase 1, from its single run; after Phase 2, from the majority across its runs)
2. "none" votes are excluded from the count
3. Threshold: 3+ voting models must agree on the same normalized side
4. If threshold not met, bet slot is killed — its **entire key/sub-key is removed** from the `predictions` dict so `edge.py` returns `None` for that bet type

### Weighted Probability Averaging

```
ensemble_prob = Σ(model_weight × model_prob × num_runs) / Σ(model_weight × num_runs)
```

Each run counts independently, weighted by its model's weight. Models with more runs in Phase 2 contribute more samples but each sample carries the same per-model weight. This is intentional — expanded models (which disagreed with consensus) get more influence in the average, which pulls the ensemble toward a more considered estimate on contested games rather than simply rubber-stamping the initial majority.

### Stability Bonus

Only applies to models that completed a **full temperature sweep** (runs at 2+ distinct temperatures). Models that only ran at a single temperature get no adjustment.

For qualifying models, per bet slot:
- std dev < 0.03 across temperatures → 1.2x weight multiplier (strong conviction)
- std dev > 0.10 across temperatures → 0.8x weight penalty (noisy)
- Between 0.03-0.10 → no adjustment

### Non-Probability Field Aggregation

| Field | Aggregation Method |
|---|---|
| `predicted_score.home` / `predicted_score.away` | Weighted average (same formula as probabilities), rounded to nearest integer |
| `key_factors` | Take from the highest-weighted model in Phase 1 |
| `analyst_assessments` | Take from the highest-weighted model in Phase 1 (not merged across models) |
| `confidence` per bet type | Majority vote across models. Ties broken toward `medium`. |

---

## 6. Adversarial Challenger

### Prompt Structure

```
You are an adversarial analyst reviewing an MLB betting ensemble's output.
Your job is to find flaws, not confirm. Kill bets that don't hold up.

BRIEFING:
{original game briefing}

ENSEMBLE PREDICTION:
{consensus predictions with per-model breakdown}

MODEL AGREEMENT:
- Moneyline: 5/6 models say home, avg edge 7.2%
- Total: 3/6 models say over, avg edge 4.1%
- F5 ML: 4/6 models say away, avg edge 5.3%

For each bet that passed consensus, respond in valid JSON only:
{
  "challenges": [
    {
      "bet_type": "moneyline",
      "verdict": "approve" | "kill",
      "reasoning": "...",
      "flaw_found": null | "description of flaw"
    }
  ]
}
No markdown, no backticks, no preamble. JSON only.
```

### Rules

- Challenger can only kill, never add bets
- Kill = bet slot's key/sub-key is removed from `predictions`. Approve = bet proceeds to edge detection.
- No recursive debate. One shot.

### Guardrail

If the challenger kills >75% of bets over a rolling 7-day window, the challenge prompt is likely miscalibrated. System falls back to consensus-only until reviewed. The self-optimizer flags this condition.

---

## 7. Model Weight Evolution

### Initial State

All models start with weight 1.0 across all 5 bet slots.

### Storage

`data/model_weights.json`:
```json
{
    "kimi": {"moneyline": 1.0, "run_line": 1.0, "total": 1.0, "first_5_ml": 1.0, "first_5_total": 1.0},
    "claude": {"moneyline": 1.0, "run_line": 1.0, "total": 1.0, "first_5_ml": 1.0, "first_5_total": 1.0},
    "gpt4o": {"moneyline": 1.0, "run_line": 1.0, "total": 1.0, "first_5_ml": 1.0, "first_5_total": 1.0},
    "gemini": {"moneyline": 1.0, "run_line": 1.0, "total": 1.0, "first_5_ml": 1.0, "first_5_total": 1.0},
    "deepseek": {"moneyline": 1.0, "run_line": 1.0, "total": 1.0, "first_5_ml": 1.0, "first_5_total": 1.0},
    "maverick": {"moneyline": 1.0, "run_line": 1.0, "total": 1.0, "first_5_ml": 1.0, "first_5_total": 1.0}
}
```

File is created with default weights on first access if it doesn't exist (create-if-not-exists in `weights.py`).

### Update Logic

After each grading cycle (run by `agents/self_optimizer.py`):
1. Read `data/model_predictions.csv` for settled bets
2. Calculate per-model, per-bet-slot Brier score
3. Floor the Brier score at 0.01 to prevent division-by-zero on perfect predictions
4. New weight = `1 / max(brier_score, 0.01)`, normalized so weights sum to 6 (number of models) per bet slot
5. If a model has no settled bets for a given bet slot, it keeps weight 1.0 (neutral)
6. Write updated weights to `data/model_weights.json`

### Concurrent Access

The ensemble reads `model_weights.json` once at the start of `run_ensemble()` and caches it for the duration of that game's analysis. The self-optimizer writes to it only during grading cycles (a separate CLI command). No file locking needed — optimistic read is sufficient since the daily pipeline and grading never run simultaneously on the same game.

---

## 8. Per-Model Prediction Logging

### New File: `data/model_predictions.csv`

```csv
date,game,model,bet_type,side,sim_prob,market_prob,edge,temperature,run_index
```

Every individual model run gets a row. This enables:
- Per-model accuracy tracking
- Per-model calibration (Brier scores)
- Per-model stability analysis (variance across temps/runs)
- Per-bet-slot granular weight updates

File is created with header row on first write if it doesn't exist (create-if-not-exists in the prediction logger).

---

## 9. Integration Points

### 9.1 `simulate.py:run_mirofish()`

Changes from:
```python
def run_mirofish(briefing: str, runs: int = 3) -> dict | None:
    print(f"[simulate] MiroFish: running {runs}-run ensemble")
    return run_plan_b(briefing, runs=runs)
```

To:
```python
def run_mirofish(briefing: str, runs: int = 3) -> dict | None:
    try:
        from ensemble import run_ensemble
        result = run_ensemble(briefing)
        if result:
            return result
        print("[simulate] Ensemble returned no result, falling back to Plan B")
    except Exception as e:
        print(f"[simulate] Ensemble failed ({e}), falling back to Plan B")
    return run_plan_b(briefing, runs=runs)
```

The `runs` parameter is ignored by the ensemble (it manages its own call count adaptively) but stays in the signature so callers don't break. The try/except ensures any ensemble failure falls back gracefully.

### 9.2 `config.py`

Add:
```python
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
```

### 9.3 `agents/self_optimizer.py`

Extend to:
- Read `data/model_predictions.csv` alongside `data/bets.csv`
- Calculate per-model Brier scores after grading
- Update `data/model_weights.json`
- Flag challenger kill rate >75% over 7-day window

### 9.4 `edge.py` — F5 Total Edge Detection

The existing `check_f5_edge()` only checks F5 moneyline and returns early, never checking F5 total. The ensemble's consensus gate treats `first_5_ml` and `first_5_total` as independent bet slots. To surface F5 total bets:

- Split `check_f5_edge()` into `check_f5_ml_edge()` and `check_f5_total_edge()`
- Update `analyze_all_edges()` to call both (returns 0-5 bet signals, not 0-4)

### 9.5 `config.py` — F5 Threshold Split

The existing `EDGE_THRESHOLDS` has a single `"first_5": 0.05` entry. Update to:

```python
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "run_line": 0.06,
    "total": 0.05,
    "first_5_ml": 0.05,
    "first_5_total": 0.05,
}
```

### 9.6 No Changes Required

- `main.py` — calls `run_mirofish()` with same signature, gets same output shape
- `briefing.py` — produces briefing string, unaware of ensemble
- `tracker.py` — logs bets, unaware of source
- All scrapers — no changes
- All other agents — no changes

---

## 10. Output Format

The ensemble returns the exact same dict shape as `run_plan_b()`:

```python
{
    "analyst_assessments": [...],       # from highest-weighted model
    "predictions": {
        "moneyline": {"home_win_prob": ..., "away_win_prob": ..., ...},
        "run_line": {"favorite_cover_prob": ..., ...},
        "total": {"projected_total": ..., "over_prob": ..., "under_prob": ..., ...},
        "first_5": {"f5_home_win_prob": ..., ...},
        "predicted_score": {"away": X, "home": X},
        "key_factors": [...]
    },
    "ensemble_runs": 1,                 # always 1 — the ensemble is one composite run
    "ensemble_meta": {
        "total_calls": 19,
        "phase_reached": 2,
        "consensus": {"moneyline": 5, "total": 3, "run_line": 2, "first_5_ml": 4, "first_5_total": 3},
        "bets_killed_by_consensus": ["run_line"],
        "bets_killed_by_challenger": [],
        "model_contributions": {"kimi": 6, "gpt4o": 1, ...},
        "cost_usd": 0.42
    }
}
```

**`ensemble_runs`** is always 1 to maintain backward compatibility. The existing `_average_results()` uses this field to indicate "number of independent full-simulation runs" — the ensemble is one composite run from the caller's perspective. The actual call count lives in `ensemble_meta.total_calls`.

**Killed bet slots:** If consensus or challenger kills a bet slot, its key is **removed entirely** from `predictions`. For first_5 sub-bets, if only one sub-bet is killed, the surviving fields remain in `predictions.first_5` but the killed fields are removed. If both F5 sub-bets are killed, the entire `first_5` key is removed.

`edge.py` reads only `predictions` (unchanged shape). `ensemble_meta` is extra metadata for debugging and the self-optimizer.

---

## 11. Cost Tracking

Cost per call is estimated from token counts in the OpenRouter response:

```python
cost = (input_tokens * model_input_price + output_tokens * model_output_price) / 1_000_000
```

Input/output prices are stored in the model registry (`models.py`). Token counts come from the `usage` field in the OpenRouter response (OpenAI-compatible format). The running total is accumulated in the orchestrator and written to `ensemble_meta.cost_usd`.

This is for logging/debugging only — not used for budget enforcement. The 50-call-per-game max is enforced by counting calls in the orchestrator, not by dollar amount.

---

## 12. Parallelization & Rate Limiting

### Phase 1 Parallelization

Phase 1 fires 6 independent model calls. These are parallelized using `concurrent.futures.ThreadPoolExecutor(max_workers=6)`. Each call has a per-model timeout:

| Model | Timeout |
|---|---|
| `gemini`, `maverick` | 30s |
| `kimi`, `gpt4o`, `claude` | 45s |
| `deepseek` | 90s (chain-of-thought is slow) |

If a model times out, it counts as a failed run (skipped, not retried).

### Phase 2 Parallelization

Phase 2 expansion calls for each model are parallelized across models (not within a single model's temperature sweep). Max workers = number of models being expanded.

### Rate Limit Handling

OpenRouter handles per-model rate limits upstream. If a 429 is returned, the runner retries once after 2 seconds. If it fails again, the run is skipped.

### Daily Call Volume

Worst case: 15 games × 50 calls = 750 calls/day. OpenRouter's default rate limits are well above this for all listed models. No additional throttling needed.

---

## 13. Error Handling & Fallbacks

- If a single model call fails (timeout, API error, invalid JSON): skip that run, proceed with remaining models
- If fewer than 3 models return valid results in Phase 1: fall back to Plan B
- If ensemble produces a result but adversarial challenge call fails: proceed without challenge (consensus-only)
- If `model_weights.json` doesn't exist or is corrupt: create with default weights (all 1.0)
- If `model_predictions.csv` doesn't exist: create with header row
- If `run_ensemble()` raises any unhandled exception: `run_mirofish()` catches it via try/except and falls back to Plan B
- **Partial failure:** `run_ensemble()` either returns a complete `predictions` dict or `None` — never a partial dict. If the orchestrator cannot produce a complete result (e.g., crash mid-Phase 2), it returns `None`, triggering Plan B fallback.
