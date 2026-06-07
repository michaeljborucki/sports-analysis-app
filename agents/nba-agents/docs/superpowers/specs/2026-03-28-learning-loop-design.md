# Learning Loop: Post-Grade Auto-Tuning

## Problem

The MiroFish pipeline has no feedback loop. Model weights are static (all 1.0), edge thresholds are hardcoded, and losing bet types keep firing. Overall ROI is -6.5% across 932 settled bets.

## Solution

Wire a post-grade learning step that automatically updates model weights (via Brier scores) and edge thresholds (via ROI analysis) after every grading run. The next pipeline run picks up the changes automatically.

## Data Flow

```
run_results_grader(date)
  ├── Grade pending bets (existing)
  ├── Print results (existing)
  └── apply_learnings()
        ├── 1. Compute Brier scores (model_predictions.csv + bets.csv)
        ├── 2. Update model weights (data/model_weights.json)
        ├── 3. Adjust edge thresholds (data/edge_overrides.json)
        └── 4. Print summary of changes
```

## Component Design

### 1. Brier Score Computation (self_optimizer.py)

Fix `compute_model_brier_scores()` to properly join predictions with results:

- Join `model_predictions.csv` with `bets.csv` on `(date, game, bet_type)`
- For each matched pair: `brier = (sim_prob - outcome)^2` where outcome is 1.0 for W, 0.0 for L
- Skip pushes (not informative for probability calibration)
- Only compute scores for model/slot combos with 10+ samples
- Return `{model: {slot: brier_score}}`

### 2. Model Weight Update (self_optimizer.py → weights.py)

Fix `update_model_weights()`:

- Inverse Brier scoring: `raw_weight = 1 / brier_score`
- Normalize so mean weight per slot = 1.0
- Clamp to `[0.3, 3.0]` — no model gets zeroed out or dominates
- Write to `data/model_weights.json` with correct NBA slot names
- Fix stale model_weights.json: migrate from MLB slot names to NBA slots

### 3. Edge Threshold Adjustment (self_optimizer.py)

New `compute_threshold_overrides()`:

- Compute ROI per bet type from all settled bets
- Rules (require 30+ settled bets for the type):
  - ROI < -15% → disable (set to `null`)
  - ROI between -15% and -5% → raise threshold by 2 percentage points
  - ROI > +5% → lower threshold by 1 percentage point (floor at 3%)
  - Otherwise → no change (omit from overrides, use config default)
- Write to `data/edge_overrides.json`

### 4. Edge Override System (edge.py)

New `get_edge_threshold(bet_type)`:

- Load `data/edge_overrides.json` if it exists
- If bet_type is in overrides:
  - `null` → return None (disabled)
  - numeric → return that value
- Otherwise → fall through to `EDGE_THRESHOLDS` from config.py
- Each edge-check function uses this instead of `EDGE_THRESHOLDS[...]` directly

`data/edge_overrides.json` example:
```json
{
  "total": 0.07,
  "q1_total": null,
  "player_threes": null,
  "team_total_home": 0.06
}
```

### 5. Integration Point (results_grader.py)

At the end of `run_results_grader()`, after grading and printing summary:
```python
if graded > 0:
    apply_learnings()
```

Only triggers when bets were actually graded (not on "no pending bets" runs).

## Files Changed

| File | Change |
|------|--------|
| `agents/self_optimizer.py` | Fix Brier computation, add `compute_threshold_overrides()`, add `apply_learnings()` |
| `agents/results_grader.py` | Call `apply_learnings()` after grading |
| `edge.py` | Add `get_edge_threshold()`, update all edge-check functions |
| `data/model_weights.json` | Reset with NBA slot names |
| `data/edge_overrides.json` | New file, created by `apply_learnings()` |

## Thresholds & Constants

- Min samples for Brier score: 10 per model/slot
- Min samples for threshold adjustment: 30 per bet type
- Weight clamp range: [0.3, 3.0]
- Disable ROI threshold: -15%
- Raise threshold ROI range: -15% to -5% (raise by 2pp)
- Lower threshold ROI range: > +5% (lower by 1pp, floor 3%)
