# Calibration + CLV Measurement Loop

**Date:** 2026-04-17
**Status:** Draft — Spec 1 of 4 in sequenced pipeline upgrade
**Scope:** Probability calibration, closing-line-value aggregation, skipped-signal logging,
per-model Brier/log-loss tracking, and hardened `self_optimizer.py` recommendations.

This spec is the **prerequisite for Specs 2-4**. Nothing downstream (Kelly shrinkage,
handedness-aware simulation, Statcast/umpire enrichment) can be validated without the
measurement + calibration infrastructure described here.

---

## 1. Overview

### Problem

The MiroFish MLB pipeline has three measurement gaps that make it impossible to tell
which changes actually help:

1. **Calibration is a stub.** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/calibrate.py:14-16`
   — `apply_calibration(prob, bet_type)` returns the probability unchanged. The docstring
   promises "isotonic regression once 200+ bets available" but that was never built.
   Meanwhile `edge.py` *already calls* `apply_calibration()` at 20 sites (see
   `/Users/mikeborucki/personal_workspace/agents/baseball-agents/edge.py` lines
   55, 61, 115, 205-206, 275-276, 344-345, 428-429, 493-496, 574-575, 643-644, 700-701).
   Every call is a no-op.

2. **CLV is computed but never aggregated.** `tracker.compute_clv()` (lines 25-45) and
   `tracker.lookup_clv()` (lines 48-68) run at settle time in `update_result`. The 13,788
   rows in `data/bets.csv` have `clv_cents` and `clv_pct` columns populated wherever a
   closing line exists in `data/closing_lines.csv`. But there is NO reporting CLI, NO
   bet-type breakdown, NO statistical test of whether CLV_pct is significantly above
   zero, and NO counterfactual analysis of skipped bets.

3. **Self-optimizer ranks by ROI, not CLV, with a tiny sample floor.** `agents/self_optimizer.py:287`
   defaults to `min_bets=30`, which is far below the threshold where sample ROI is
   informative. ROI at 30 bets has a ~10-percentage-point standard error — we routinely
   see recommendations that flip sign at 60 bets. CLV is orders of magnitude more
   informative per bet.

### Why this unblocks Specs 2-4

- **Spec 2 (Kelly shrinkage)** needs per-model Brier/log-loss to know what uncertainty
  means in practice, and CLV breakdown to validate that shrunken bets still beat the
  close.
- **Spec 3 (handedness-aware simulation)** changes probabilities. Without calibration
  curves and Brier delta tracking we can't tell whether new probabilities are closer
  to truth or just differently miscalibrated.
- **Spec 4 (Statcast/umpire/catcher enrichment)** adds features. Same problem — we
  need calibration diagnostics and CLV as the A/B metric, not ROI which is
  variance-dominated at our sample sizes.

The deliverable is the **measurement substrate** — nothing is tuned or changed based on
it yet. Spec 2 is the first to consume calibration outputs.

---

## 2. Goals / Non-goals

### Goals

- Build a real, per-bet-type probability calibration that reads `bets.csv` and writes
  monotone calibration curves to `data/calibration_curves.json`.
- Make `apply_calibration(prob, bet_type)` a proper transform (isotonic / beta / identity
  fallback) based on per-bet-type sample size.
- Add a CLV-aggregation CLI that breaks down closing-line value by bet_type × edge-bucket
  × confidence × model over rolling 7/30/90-day windows, with a t-test on CLV_pct.
- Log every signal that *fell below* the edge threshold (or was killed by the worst-case
  filter / correlated-cluster dedupe) into `data/skipped_signals.csv` so we can ask
  counterfactually "would lowering the threshold have produced +CLV bets?"
- Move per-model Brier/log-loss tracking out of `self_optimizer.py` into a clean
  `ensemble/calibration_metrics.py` module, callable from a CLI subcommand.
- Tighten `self_optimizer.py` to use CLV as the primary metric, require ≥200 bets per
  type before emitting a recommendation, and require p<0.05 on a CLV t-test.

### Non-goals

- **Auto-writing to `config.py`.** Threshold/Kelly adjustments stay manual; the tool
  prints recommendations and the user edits `config.py`.
- **Changing the ensemble or any model weights in response to calibration.** Weights
  live in `data/model_weights.json` and their update logic will be moved but not
  triggered automatically here.
- **Changing Kelly sizing.** That's Spec 2.
- **New data sources.** That's Spec 4. Everything here reads existing CSVs.
- **Modifying how bets are placed or graded.** Pipeline/grader are untouched.

---

## 3. Components

Five deliverables. Each lists the file, public signatures, and data shapes.

### 3.1 Per-bet-type probability calibration

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/calibrate.py`
(replace the current 40-line stub).

**Dependencies:** `scikit-learn>=1.4` (for `sklearn.isotonic.IsotonicRegression`),
`betacal>=0.5.0` (for `betacal.BetaCalibration`).

**Algorithm (per bet_type):**

```
n = count of settled (W/L) bets in bets.csv for this bet_type
  if n >= 500:  method = "isotonic"   # nonparametric, monotone, best when data-rich
  elif 100 <= n < 500:  method = "beta"       # 3-parameter parametric (a, b, c)
  else (n < 100):  method = "identity"   # too little data; no transform
```

**Curve storage shape** (`data/calibration_curves.json`):

```json
{
  "version": 1,
  "rebuilt_at": "2026-04-17T10:00:00Z",
  "curves": {
    "moneyline": {
      "method": "isotonic",
      "n_samples": 1823,
      "brier": 0.2412,
      "log_loss": 0.6781,
      "brier_uncalibrated": 0.2498,
      "log_loss_uncalibrated": 0.6902,
      "x_thresholds": [0.01, 0.05, 0.10, ...],   // input probs
      "y_thresholds": [0.03, 0.06, 0.11, ...]    // calibrated probs
    },
    "run_line": {
      "method": "beta",
      "n_samples": 412,
      "a": 0.94, "b": 1.02, "c": -0.03,
      "brier": 0.2501, "log_loss": 0.6899,
      "brier_uncalibrated": 0.2541, "log_loss_uncalibrated": 0.6988
    },
    "batter_strikeouts": {
      "method": "identity",
      "n_samples": 62
    }
  }
}
```

For isotonic curves we persist `x_thresholds` / `y_thresholds` (the fitted step points)
rather than pickling the sklearn model, so the JSON stays human-inspectable and portable.
At load time we reconstruct the `IsotonicRegression` via `IsotonicRegression(out_of_bounds="clip").fit(x, y)`
or we do a direct piecewise-linear interp (simpler, avoids hard sklearn dep at inference
time — see `_apply_isotonic()` below).

**Public functions (replacing the stub):**

```python
def apply_calibration(prob: float, bet_type: str) -> float:
    """Look up curve, transform, clamp to [0.01, 0.99]. Identity on any error."""

def build_calibration_curves(bets_df: pd.DataFrame | None = None,
                             min_isotonic_samples: int = 500,
                             min_beta_samples: int = 100,
                             output_path: str | None = None) -> dict:
    """Fit curves per bet_type from settled bets, write JSON, return the dict.
       Pure function if bets_df is provided; else loads from BETS_CSV."""

def calibration_report(bets_df: pd.DataFrame | None = None) -> dict:
    """Per-bet-type reliability diagram + Brier + log-loss, comparing
       uncalibrated sim_prob to calibrated output of current curves.
       Returns:
       {
         "status": "ok",
         "total_settled": 9,142,
         "by_type": {
           "moneyline": {
             "n": 1823,
             "method": "isotonic",
             "bins": [{"lo": 0.0, "hi": 0.1, "pred_avg": 0.06, "actual_rate": 0.05, "n": 231}, ...],
             "brier_before": 0.2498, "brier_after": 0.2412,
             "log_loss_before": 0.6902, "log_loss_after": 0.6781
           }, ...
         }
       }
    """

def _apply_isotonic(prob: float, x_thresh: list[float], y_thresh: list[float]) -> float:
    """Piecewise-linear interpolation; no sklearn dep at inference."""

def _apply_beta(prob: float, a: float, b: float, c: float) -> float:
    """Beta calibration transform: sigmoid(a*log(p) - b*log(1-p) + c)."""

def _clamp(prob: float, lo: float = 0.01, hi: float = 0.99) -> float: ...
```

**Curve file location:** `data/calibration_curves.json`. Loaded once on first
`apply_calibration()` call via a module-level cache; reloaded if mtime changes (so a
rebuild is picked up by the next-day pipeline run without restart).

**CLI:** `python main.py calibrate [--rebuild] [--report]`
- `--rebuild` runs `build_calibration_curves()` and writes the JSON.
- `--report` runs `calibration_report()` and prints bins + Brier before/after.
- Default (no flag): prints status (version, rebuilt_at, per-type method + n).

**Edge-detection integration:** no code changes required. `edge.py` already calls
`apply_calibration()` everywhere. The first pipeline run after this spec lands will pass
calibrated probs through Kelly automatically.

### 3.2 CLV aggregation module

**File (new):** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/agents/clv_tracker.py`

**Data source:** `data/bets.csv` (settled rows, `clv_cents`/`clv_pct` already populated
where `data/closing_lines.csv` had a match). Rows with `clv_cents` NaN or `close_odds`
NaN are excluded from CLV aggregates but counted in the "coverage" denominator.

**Public functions:**

```python
def load_clv_bets(date_from: str | None = None,
                  date_to: str | None = None,
                  include_props: bool = True) -> pd.DataFrame:
    """Settled bets with a matched closing line, as a DataFrame with cols:
       date, game, bet_type, side, odds, close_odds, clv_cents, clv_pct,
       edge, kelly_pct, result, profit, sim_prob, market_prob."""

def aggregate_clv(df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame:
    """Group and compute per-group:
         n, clv_pct_mean, clv_pct_median, clv_cents_mean,
         beat_close_rate, t_stat, p_value, roi, win_rate."""

def clv_by_bet_type(df: pd.DataFrame) -> pd.DataFrame:  # group_by=["bet_type"]
def clv_by_edge_bucket(df: pd.DataFrame) -> pd.DataFrame:
    """Buckets: 3-5%, 5-8%, 8-12%, 12%+ — matches self_optimizer buckets."""
def clv_by_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """Confidence = ensemble agreement score if logged, else kelly_pct
       quartile as a fallback proxy."""
def clv_by_model(df: pd.DataFrame,
                 preds_df: pd.DataFrame) -> pd.DataFrame:
    """Join bets to model_predictions.csv on (date, game, bet_type, side);
       compute CLV per model where that model 'voted' for the chosen side."""
def clv_rolling(df: pd.DataFrame,
                windows: tuple[int, ...] = (7, 30, 90)) -> pd.DataFrame:
    """Rolling CLV_pct mean over last N calendar days ending today."""

def clv_skipped_counterfactual(
    skipped_df: pd.DataFrame,
    closing_df: pd.DataFrame,
) -> pd.DataFrame:
    """For each row in skipped_signals.csv, look up the closing line
       and compute what CLV_pct would have been. Output columns:
       date, game, bet_type, side, sim_prob, edge, skip_reason,
       hypothetical_close_odds, hypothetical_clv_pct."""

def print_report(date_from: str | None = None, date_to: str | None = None) -> None:
    """Full CLV dashboard to stdout."""
```

**t-test:** one-sample t-test of `clv_pct` vs 0 (`scipy.stats.ttest_1samp` if scipy is
already available, else hand-rolled: `t = mean / (std / sqrt(n))`, p-value from student-t
CDF). Flag `"stat_sig": True` when `p < 0.05` AND `n >= 30`.

**CLI:** `python main.py clv [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--model]`
Prints, in order:
1. Coverage: X of Y settled bets have closing lines (Z%)
2. Overall CLV_pct mean, median, beat-close rate, t-stat, p-value
3. Per bet_type: same columns + stat-sig flag
4. Per edge bucket
5. Per confidence/kelly quartile
6. Rolling 7/30/90-day CLV_pct
7. (If `--model`) per ensemble-model CLV
8. Skipped-signal counterfactual: % of skipped signals that would have been +CLV

### 3.3 Hardened `self_optimizer.py`

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/agents/self_optimizer.py`

**Changes:**

1. Default `min_bets=30` → `min_bets=200` on both the CLI (`main.py:658`) and the
   `self_optimizer.main` decorator at line 287. Applies **per-bet-type** (currently
   it's applied to the global settled-row count; change to per-type check before
   emitting any recommendation for that type).

2. Add `--metric=[roi|clv]` flag, default `clv`. Branch in
   `analyze_by_bet_type`, `analyze_by_edge_bucket`, `analyze_by_odds_range` to compute
   either profit/ROI (current) or CLV_pct mean + t-test. Both are printed; only the
   metric passed via `--metric` drives the recommendation text.

3. **Recommendation gate:** `recommend_adjustments()` only emits a threshold change
   for a bet type when:
   - `n >= 200` for that type, AND
   - (if `metric=clv`) `p_value < 0.05` on the CLV_pct t-test, OR
   - (if `metric=roi`) `|roi|` is at least 2× the ROI standard error.

4. Keep ROI breakdown printed as secondary diagnostic (under a `--- ROI (secondary) ---`
   header) — it's still useful for sanity-checking and for comparing against historical
   reports.

5. **Move** `compute_model_brier_scores()` (lines 234-259) and `update_model_weights()`
   (lines 262-283) to `ensemble/calibration_metrics.py` (see 3.5). Leave a thin
   re-export shim in `self_optimizer.py` for one release cycle, then delete.

No changes to `config.py` from this module. Ever. (Explicit non-goal.)

### 3.4 Counterfactual skipped-signal log

**File (new):** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/skipped_signals.csv`

**Columns:**

| column            | type  | notes                                                             |
|-------------------|-------|-------------------------------------------------------------------|
| `date`            | str   | YYYY-MM-DD (game date)                                            |
| `game`            | str   | "AWAY@HOME" team abbreviations                                     |
| `bet_type`        | str   | from `EDGE_THRESHOLDS` keys                                       |
| `side`            | str   | same format as `bets.csv.side`                                    |
| `odds`            | int   | American odds at signal time                                      |
| `sim_prob`        | float | post-calibration probability                                      |
| `market_prob`     | float | power-devigged consensus                                          |
| `edge`            | float | `sim_prob - market_prob`                                          |
| `calibrated_prob` | float | value returned by `apply_calibration()`; equals `sim_prob` currently |
| `threshold`       | float | `EDGE_THRESHOLDS[bet_type]` at signal time                        |
| `skip_reason`     | str   | `below_threshold` \| `failed_worst_case` \| `capped_edge` \| `correlated_cluster_dropped` |
| `logged_at`       | str   | ISO timestamp                                                     |

**Insertion points in `edge.py`:** every edge-checker that can *reject* a signal needs a
logging branch. We'll add a single helper:

```python
def _log_skipped(date: str, game: str, bet_type: str, side: str,
                 odds: int, sim_prob: float, market_prob: float,
                 edge: float, calibrated_prob: float,
                 threshold: float, skip_reason: str) -> None: ...
```

defined in a new `edge_logging.py` (or at the top of `edge.py`). It's called from:

- Every `if edge < EDGE_THRESHOLDS[bet_type]` branch that currently `return None`s or
  drops a side. **Constraint:** only log when `edge >= 0.01` (i.e. we're within 4 points
  of threshold) to avoid flooding the CSV with thousands of noise rows per game.
- `_passes_worst_case_filter()` failures (`edge.py:33-41`) — `skip_reason="failed_worst_case"`.
- Any edge-cap logic (search for `min(edge, ...)` applications — I don't see one today
  but the spec leaves room for Spec 2 to add one).
- Correlated-cluster dedupe — where team-total + total + moneyline triples are pruned.
  (This happens in `simulate.py` / `agents/bet_card.py`; add a log-hook there.)

**Dedup key:** same as `bets.csv`: `(date, game, bet_type, side)`. Enforced at write
time by checking the last-N-rows buffer.

**Thread safety:** same `threading.Lock()` + buffered append pattern as
`tracker.log_bet()`.

**Loaded by:** `clv_tracker.clv_skipped_counterfactual()` (see 3.2).

### 3.5 Per-model Brier/log-loss metrics

**File (new):** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/ensemble/calibration_metrics.py`

This is the relocation of the already-existing (but poorly-wired) functions in
`self_optimizer.py:234-283`. The new module has:

```python
def compute_model_brier_scores(
    preds_df: pd.DataFrame,
    bets_df: pd.DataFrame,
) -> dict[str, dict[str, dict]]:
    """Returns {model_key: {bet_type: {"brier": float, "log_loss": float, "n": int}}}.

    Join keys: (date, game, bet_type, side). Outcome comes from bets_df.result
    (W=1, L=0, P excluded). Probability comes from preds_df.sim_prob (per-model
    per-run); if a model ran >1 run for the slot, we average sim_prob across runs
    before scoring."""

def compute_model_log_loss(
    preds_df: pd.DataFrame,
    bets_df: pd.DataFrame,
) -> dict[str, dict[str, float]]: ...

def update_model_weights(
    brier_scores: dict,
    weights_path: str | None = None,
) -> None:
    """Same semantics as today (lower Brier → higher weight, normalized).
       Not auto-called — triggered only by `python main.py model-scores --update-weights`."""

def model_scores_report(
    preds_df: pd.DataFrame | None = None,
    bets_df: pd.DataFrame | None = None,
) -> dict:
    """Per-model × per-bet_type: n, brier, log_loss, calibration_gap.
       calibration_gap = mean(sim_prob) - mean(outcome) — positive = model
       over-confident."""
```

**CLI:** `python main.py model-scores [--update-weights]`
Prints a table: rows = bet_type, columns = one block per model with
`brier / log_loss / n / gap`.

The bug in the current implementation is the inner loop at
`self_optimizer.py:246-254` — it scores every prediction against `matching.iloc[0]`
regardless of which game/date that prediction came from. The new module joins
`preds_df` to `bets_df` on `(date, game, bet_type, side)` before scoring, which is
the actual correct behavior. **Do not ship the old version — it has been producing
garbage scores since it was written.** This is called out here so whoever implements
the spec doesn't accidentally copy the broken inner loop.

---

## 4. Data flow

Three CSVs are the source of truth; four consumers read them.

**Sources:**
- `data/bets.csv` (13,788 rows) — settled bets with `clv_cents`/`clv_pct` populated by
  `tracker.update_result` via `tracker.lookup_clv()`.
- `data/closing_lines.csv` — consensus close, captured T-15..T-5.
- `data/model_predictions.csv` (13,848 rows) — per-model, per-run probabilities.

**Consumers:**
- `calibrate.py` reads `bets.csv`, writes `data/calibration_curves.json`. `edge.py`
  lazy-loads the JSON at its 20 existing `apply_calibration()` call sites.
- `agents/clv_tracker.py` reads `bets.csv` + `model_predictions.csv` + `skipped_signals.csv`,
  surfaces aggregates via `main.py clv`.
- `ensemble/calibration_metrics.py` joins `model_predictions.csv` to `bets.csv` on
  `(date, game, bet_type, side)`, surfaces per-model Brier/log-loss via
  `main.py model-scores`.
- `edge.py` writes rejected signals to `data/skipped_signals.csv` via `_log_skipped()`.

**Join keys in detail:**

- `bets.csv × closing_lines.csv` (already implemented in `tracker.lookup_clv`):
  - `(date, game)` direct
  - market derived via `_parse_bet_for_clv(bet_type, side)` at `tracker.py:71`
  - for totals/team-totals/run-lines: also match on `line`
- `bets.csv × model_predictions.csv` (new, used by `calibration_metrics.py` and by
  `clv_tracker.clv_by_model`):
  - `(date, game, bet_type, side)` exact match
  - multiple prediction rows per bet (one per model × run_index) — aggregate by
    mean `sim_prob` before scoring, or compute per-model scores separately
- `skipped_signals.csv × closing_lines.csv` (new, counterfactual):
  - same market/side derivation as `bets.csv × closing_lines.csv`

---

## 5. New dependencies

Edit `/Users/mikeborucki/personal_workspace/agents/baseball-agents/requirements.txt`:

```diff
 pybaseball>=2.3.0
 requests>=2.31.0
 openai>=1.12.0
 python-dotenv>=1.0.0
 click>=8.1.0
 pandas>=2.1.0
 pytest>=7.4.0
+scikit-learn>=1.4.0   # isotonic regression for calibration
+betacal>=0.5.0         # beta calibration (Kull/Silva Filho/Flach 2017)
+scipy>=1.11.0          # t-test, student-t CDF for CLV significance
```

`scipy` is already a transitive dep of pybaseball and pandas but we pin it explicitly
because `clv_tracker.py` imports `scipy.stats.ttest_1samp` directly.

`scikit-learn` is not currently in the dep tree. It's a sizable install (~30MB wheel)
but justified for a known-good isotonic implementation. We keep the *inference* path
(`_apply_isotonic`) free of sklearn via stored thresholds + piecewise linear interp,
so if we ever want to trim deps in production we can drop sklearn from the runtime
image and keep it only in the weekly-rebuild path.

`betacal` is a small pure-Python package that wraps the beta calibration method. Not
load-bearing — if we ever want to drop it, we can inline the ~40-line fit (logistic
regression on transformed features). Keeping it as a dep for now.

---

## 6. Migration / backfill

### 6.1 Seeding `calibration_curves.json`

On the **first run** of `python main.py calibrate --rebuild` after this lands:

1. `build_calibration_curves()` loads all 13,788 rows of `bets.csv`.
2. Filters to `result in {"W","L"}`. P (push) excluded.
3. Groups by `bet_type`. For each:
   - `n >= 500`: fit `IsotonicRegression(out_of_bounds="clip").fit(X, y)` where
     `X = sim_prob`, `y = 1.0 if result=="W" else 0.0`. Extract `X_thresholds_` and
     `y_thresholds_` for storage.
   - `100 <= n < 500`: fit `BetaCalibration().fit(X.reshape(-1,1), y)`. Extract
     `a`, `b`, `c` (the three scalar coefficients the library exposes on the fitted
     object). Note: the precise attribute names on `betacal` 0.5 are
     `lr_.coef_[0]`, `lr_.coef_[1]`, `lr_.intercept_`; wrap in a helper.
   - `n < 100`: method = "identity".
4. Compute Brier + log-loss before and after for the report.
5. Write `data/calibration_curves.json` atomically (write tmp, rename).

### 6.2 Expected bet-type coverage at first run

Rough a-priori guess given 13,788 historical bets: mainline markets (`moneyline`,
`total`, likely `run_line`) fall in the isotonic bucket (≥500); `first_5_*`,
`team_total_*`, `nrfi` fall in the beta bucket (100-500); `first_3_*` and props fall
mostly to identity. The spec does not depend on the exact distribution — the first
rebuild logs actual counts and methods.

### 6.3 Lazy creation of `skipped_signals.csv`

`_log_skipped()` creates the file with headers on first write (mirror the pattern in
`tracker._ensure_csv()` and `closing_lines._ensure_csv()`). No backfill — we start
logging from pipeline run 1 post-deploy.

### 6.4 Weekly rebuild

Add a cron-friendly CLI: `python main.py calibrate --rebuild`. Recommend the user
schedule this on Monday morning (bet volume is highest over weekends; a Monday rebuild
captures the freshest sample). No automatic scheduler is configured as part of this
spec — just the CLI. Setting up the cron/launchd job is a follow-up.

---

## 7. Testing strategy

All tests live under `tests/`. New test files:

### 7.1 `tests/test_calibrate.py`

- `test_isotonic_monotone_on_known_fixture`: give the fitter 500 synthetic
  (sim_prob, result) pairs drawn from a known miscalibrated distribution
  (e.g. sim_prob ~ Beta(2,2), true_prob = 0.3 + 0.4*sim_prob, outcome ~
  Bernoulli(true_prob)). Fit. Assert `calibrated_prob` is weakly monotone in
  `sim_prob` across a 100-point grid.
- `test_beta_fit_recovers_identity_on_already_calibrated_data`: if we feed
  well-calibrated inputs (outcome ~ Bernoulli(sim_prob)), the fit should be
  near-identity. Assert `|calibrated(p) - p| < 0.05` across grid.
- `test_below_100_samples_falls_back_to_identity`: feed 50 rows, assert
  method == "identity" and `apply_calibration(p, bt) == p`.
- `test_apply_calibration_clamps_to_[0.01,0.99]`.
- `test_curves_json_roundtrip`: build → write → load → apply; same output.
- `test_unknown_bet_type_returns_identity`: `apply_calibration(0.5, "xyz") == 0.5`.
- `test_curve_file_missing_is_identity`: rename file, all calls pass through.

### 7.2 `tests/test_clv_tracker.py`

Fixture: a small hand-constructed `bets_df` with 40 rows, mix of W/L, known
`clv_pct` values.

- `test_load_clv_bets_excludes_pending`: rows with `result=""` or `result=="P"` are
  excluded from the CLV-mean numerator but included in coverage denominator.
- `test_aggregate_clv_computes_correct_ttest`: one-sample t-test against a
  hand-calculated fixture. Assert p-value within 1e-4 of scipy's value.
- `test_beat_close_rate_counts_clv_cents_gt_0`.
- `test_clv_rolling_windows_trim_by_date`: rows older than 90 days excluded
  from the 90-day window.
- `test_clv_by_model_joins_predictions`: fixture with 3 models voting; per-model
  CLV matches manual join.
- `test_clv_skipped_counterfactual_matches_closing_lines`.

### 7.3 `tests/test_skipped_signals.py`

- `test_log_skipped_creates_file_with_headers`.
- `test_dedup_by_key`: same `(date, game, bet_type, side)` ignored on re-log.
- `test_only_logs_if_edge_ge_0_01`: threshold is 0.05, edge of 0.006 not logged,
  edge of 0.04 logged.
- `test_skip_reason_enum_validation`.

### 7.4 `tests/test_calibration_metrics.py`

- `test_brier_matches_manual_calculation`: 5 (pred, outcome) pairs, known Brier.
- `test_join_on_date_game_type_side`: predictions with mismatched game are not
  scored. This is the regression test for the bug in the old
  `self_optimizer.compute_model_brier_scores` (which used `matching.iloc[0]` and
  scored everything against the first matching row).
- `test_update_model_weights_normalizes_to_n`: per-slot weights sum to n_models.

### 7.5 Golden tests

- `tests/golden/calibration_moneyline_2026Q1.json`: pin the fitted isotonic
  thresholds for the moneyline bet type against a frozen snapshot of `bets.csv`
  (committed as `tests/fixtures/bets_snapshot_2026-04-17.csv`, ~2k rows).
  CI regenerates and diffs.

---

## 8. Rollout

Four stages, each independently revertible.

**Stage A — Land code, calibration no-op.** New `calibrate.py`, `clv_tracker.py`,
`calibration_metrics.py`, skipped-signal logging, and all three CLIs
(`calibrate|clv|model-scores`) ship. `self_optimizer.py` hardening ships. No
`calibration_curves.json` yet; `apply_calibration()` falls through to identity
on missing file. Risk profile: nil — no edge/sizing behavior change.

**Stage B — Run backfill.** Run `python main.py calibrate --rebuild`. Inspect
the JSON and `--report`. Confirm Brier_after < Brier_before for each ≥100-sample
type. Any type where calibration made in-sample Brier worse by >0.005 is
auto-reverted to identity by the guard in `build_calibration_curves()` (Risk 9.1).

**Stage C — Enable calibration in edge.py.** Commit `data/calibration_curves.json`.
Next pipeline run uses calibrated probs at all 20 call sites. Monitor daily for
7 days via `main.py clv` and `main.py model-scores`. Kill switch: delete the
JSON; next call picks up the miss via the mtime cache-invalidation path.

**Stage D — Parallel validation (1 week).** Run both ROI and CLV self-optimizer
outputs side-by-side. If they diverge sharply, hold off on threshold changes
until 2 weeks of post-calibration data are in hand. After 1 week, ROI becomes
purely diagnostic.

---

## 9. Risks

### 9.1 Overfit on small-sample bet types

Beta calibration at 100-200 samples has meaningful variance in the fitted
`(a, b, c)`. Worst case: the fit mislabels a well-calibrated-but-noisy bet type
as systematically over-confident.

**Mitigation:** 100/500 floors are already conservative. Additional guard in
`build_calibration_curves()`: if in-sample Brier_after > Brier_before + 0.005,
revert that bet type to identity and log a warning.

### 9.2 Calibration flipping a profitable-but-uncalibrated bet type to unprofitable

If a bet type is profitable because the model is *systematically over-confident*
in a way that happens to offset an unmodeled negative factor, honest calibration
will shrink probs, kill edges, and eliminate the stream. CLV is the telltale —
if those pre-calibration bets had negative CLV_pct the profit was variance;
killing the signal is correct. If they had positive CLV_pct we're losing real
edge.

**Mitigation:** Stage C monitoring. If aggregated CLV_pct drops >0.5% absolute
over the first 7 days post-enable (vs the matching pre-enable window), revert
via kill switch and investigate per-bet-type.

### 9.3 p<0.05 t-test gates out slow-but-real signal

Slow-accumulating bet types (e.g. `first_1_rl`, `nrfi`) won't reach stat-sig on
CLV for months. The hardened `self_optimizer.py` refuses recommendations for
them.

**Mitigation:** acceptable. The tool should refuse to recommend on insufficient
evidence — the user still sees the raw CLV_pct and p-value in the diagnostic
table and can judge for themselves. Escape hatch: `--force-recommend` bypasses
the p-value gate (not advertised in help text).

### 9.4 `skipped_signals.csv` growth

We estimate ~20-50 skipped rows per game × ~15 games/day ≈ 450 rows/day, or
~165k rows/year. CSV stays under 20MB at 1 year. Acceptable. Can be trimmed
to trailing 90 days by a future maintenance script if needed.

### 9.5 Closing-line coverage gap

Many of the 13,788 historical bets predate `closing_lines.csv` (which landed in
`2026-04-14-cache-breakeven-clv-design.md`). CLV aggregates will be dominated by
recent bets.

**Mitigation:** `load_clv_bets()` surfaces coverage (N_with_close / N_settled)
prominently at the top of every report so users see the denominator.

### 9.6 Prediction/bet-row mismatch in calibration_metrics

`model_predictions.csv` can diverge from `bets.csv` — grading failures, or
predictions that never became logged bets (edge too small). The join must be
robust: skip rows missing on either side.

**Mitigation:** `compute_model_brier_scores` logs `orphan_preds` and
`orphan_bets` counts so silent data drift is visible.

---

## Appendix A — Files touched

**Modified:** `calibrate.py` (rewrite), `agents/self_optimizer.py` (hardening +
relocation), `main.py` (3 new subcommands: `calibrate`, `clv`, `model-scores`),
`edge.py` (skipped-signal logging at ~12 call sites), `requirements.txt`.

**Created:** `agents/clv_tracker.py`, `ensemble/calibration_metrics.py`,
`data/calibration_curves.json` (first `--rebuild`), `data/skipped_signals.csv`
(first skipped signal), plus test files under `tests/` (`test_calibrate.py`,
`test_clv_tracker.py`, `test_skipped_signals.py`, `test_calibration_metrics.py`)
and fixtures (`tests/fixtures/bets_snapshot_2026-04-17.csv`,
`tests/golden/calibration_moneyline_2026Q1.json`).

**Explicitly unchanged:** `config.py` (no auto-edit ever), `tracker.py` (CLV
lookup at settle time already works), `scrapers/closing_lines.py` (captures +
dedupes today), `ensemble/orchestrator.py` + `ensemble/weights.py` (weight
update exposed, not auto-triggered).

## Appendix B — Follow-up specs

- **Spec 2:** consume `calibration_metrics.py` per-model Brier to shrink Kelly bets
  by model disagreement / per-bet uncertainty.
- **Spec 3:** regenerate calibration curves after handedness-aware simulation lands
  and compare Brier delta as the validation metric.
- **Spec 4:** same, for Statcast/umpire/catcher feature additions.

All three consume the measurement substrate built here. This spec must land and
stabilize (Stages A-D complete) before any of the three is merged.
