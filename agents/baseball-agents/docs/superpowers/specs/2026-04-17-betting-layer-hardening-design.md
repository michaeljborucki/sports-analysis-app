# Betting-Layer Hardening

**Date:** 2026-04-17
**Status:** Draft
**Sequence:** Spec 2 of 4 (follows `2026-04-17-calibration-clv-loop-design.md`)
**Scope:** De-vigging, consensus construction, correlation-aware Kelly, best-line metadata, quarantine gating.

---

## 1. Overview

Spec 1 (Calibration + CLV Loop) makes `apply_calibration()` the single source of truth for turning model output into probabilities the betting layer trusts. Everything downstream of that — how vig is removed, how the consensus is built, how a trusted probability is converted into stake, how correlated exposures are capped, and what "best line" means at log time — is still a mix of pessimistic heuristics, equal-weight averages, and per-bet independent Kelly with one small run-cluster patch.

This spec hardens the betting layer *without* touching the prediction stack. All changes live in:

- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/odds.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/edge.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tracker.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/config.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/sizing.py` (new)

Dependence on Spec 1:

- Shin-devig comparisons must be done against *calibrated* sim probabilities. `edge.py` already calls `apply_calibration(...)` before computing edge for every market (see `edge.py:55`, `:61`, `:115`, `:205-206`, `:275-276`, `:344-345`, `:428-429`, `:493-496`, `:574-575`, `:643-644`, `:700-701`). Spec 2 leaves those calls exactly where they are and only changes what happens *after* the calibrated prob is compared to the market.
- Shrinkage Kelly consumes `prob_std` emitted by the ensemble runner. Spec 1 already surfaces per-slot calibration confidence; Spec 2 adds a small extension to `ensemble/orchestrator.py` that stdevs the *primary* probability field across runs.

If Spec 1 is not live, Spec 2 still compiles and runs — calibrated probs just fall through to raw probs — but the quarantine thresholds will trip more often on uncalibrated outputs. Flag-gate accordingly (§7).

---

## 2. Goals / Non-Goals

### Goals

1. Replace worst-case-devig gating (a belt-and-suspenders remnant inconsistent across bet types) with a principled, symmetric Shin + power-devig comparison.
2. Weight Pinnacle (and other sharp books) in the market consensus used for `implied_probs`.
3. Capture best-line metadata at snapshot time (which book, what price) so downstream CLV becomes meaningful.
4. Cap same-game correlated exposure to a multiple of the best single-leg Kelly, rather than summing N independent bets.
5. Scale Kelly by cross-run probability uncertainty — a smooth replacement for the current flat 0.25 fraction.
6. Quarantine suspicious edges (>15%) rather than silently capping and firing them.
7. Ship all of the above behind a `BETTING_V2_ENABLED` flag so we can A/B for two weeks against today's behavior.

### Non-Goals

- Real-time line-shopping automation. We record *which* book had the best price; we do not place or migrate bets.
- Any change to calibration (Spec 1's domain).
- Any change to the simulation engine or the probability estimates (Spec 3's domain).
- New data sources (Spec 4's domain).
- Re-tuning `EDGE_THRESHOLDS` — orthogonal work, handled by the calibration loop in Spec 1.

---

## 3. Components

### 3.1 Shin De-Vig for 2-Way Markets

**File:** `scrapers/odds.py`
**New public functions:**

```python
def shin_devig(prob_a: float, prob_b: float) -> tuple[float, float, float]:
    """Shin (1993) de-vig for a 2-way market.

    Returns (p_a, p_b, z) where z in [0, 1) is the estimated insider
    fraction. Larger z => sharper, more insider-driven book.

    For a 2-way market with raw implied probabilities pi_a and pi_b:
        Sigma_pi = pi_a + pi_b   (= 1 + overround)

        p_i = ( sqrt( z^2 + 4*(1 - z) * pi_i^2 / Sigma_pi ) - z )
              / ( 2 * (1 - z) )

    z is chosen so that p_a + p_b = 1. In the 2-way case this has a
    closed-form, but numerically we solve by bisection on z in [0, 0.2]
    which is plenty of headroom for any real sportsbook.
    """

def shin_devig_many(raw_probs: list[float]) -> tuple[list[float], float]:
    """N-way generalization. Not wired in today; exists for 3-way
    markets (e.g. soccer MW3, draw-no-bet decompositions). Returns
    (probs, z) with sum(probs) == 1."""
```

**Implementation notes:**

- Reuse the existing bisection pattern from `power_devig` (`scrapers/odds.py:45-73`) — same 100-iteration, `1e-10` tolerance loop. Do *not* pull in scipy; it's not a current dependency.
- Bracket `z` on `[0.0, 0.2]`. Empirically, z for US sportsbook 2-way markets is 0.01–0.05; Pinnacle runs ~0.02. 0.2 is "something is wrong with the feed" territory.
- Degenerate input handling mirrors `power_devig`: both-sides-near-zero returns `(prob_a/total, prob_b/total, 0.0)`; `abs(total - 1.0) < 1e-6` short-circuits to `(prob_a, prob_b, 0.0)`.
- Return value rounds `p_a`, `p_b` to 6 decimals (consistent with `power_devig`) and `z` to 4.

**Logging:**

- In `get_mlb_odds()` (around `scrapers/odds.py:392-432`, the current consensus loop), compute per-book Shin `z` and emit one `logger.debug` per market: `shin z=0.031 book_count=7 market=h2h game=LAD@SF`. Aggregate daily mean `z` per market to `data/devig_stats.csv` (schema: `date, market, mean_z, median_z, book_count`). This becomes a sharpness proxy and input to future weighting decisions.

### 3.2 Consistent De-Vig Gate in `edge.py`

**File:** `edge.py`

**What goes away:**

- `_passes_worst_case_filter()` at `edge.py:33-41` is removed from every call site *except* the moneyline path when paired odds are missing (extremely rare with current multi-book coverage, but the guard stays for safety).
- Today's call sites that will drop the gate: `edge.py:71, 87, 144, 160, 220, 236, 281, 297, 351, 367, 441, 457, 524, 540, 587, 603, 649, 665, 713, 729, 838`.

**What replaces it:**

A new helper in `edge.py`:

```python
def _dual_devig_check(
    sim_prob: float,
    raw_own: float,
    raw_other: float,
    threshold: float,
) -> tuple[bool, dict]:
    """Compute both Shin and power de-vig, require both edges >= threshold.

    Returns (passes, info_dict). info_dict always contains:
        shin_implied, shin_edge, shin_z,
        power_implied, power_edge,
        devig_divergence        # |shin_edge - power_edge|
        devig_method            # "agree" | "divergent"
    """
```

Rules encoded in `_dual_devig_check`:

- `passes = min(shin_edge, power_edge) >= threshold` — belt-and-suspenders.
- If `abs(shin_edge - power_edge) > 0.015`, set `devig_method="divergent"` and `logger.warning("devig divergence %s vs %s: shin=%.3f power=%.3f z=%.3f", bet_type, side, shin_edge, power_edge, z)`.
- The bet dict returned by each `check_*_edge` function gains: `shin_edge`, `shin_z`, `power_edge`, `devig_method`. `market_prob` continues to be `power_implied` (keeps tracker/bet-card back-compat; all existing CSV columns untouched).

**Call-site pattern (example for moneyline at `edge.py:70-85`):**

Before:
```python
if home_edge >= threshold and home_edge >= away_edge:
    passes, wc_edge = _passes_worst_case_filter(home_prob, raw_home, raw_away)
    if not passes:
        return None
    ...
```

After:
```python
if home_edge >= threshold and home_edge >= away_edge:
    passes, dv = _dual_devig_check(home_prob, raw_home, raw_away, threshold)
    if not passes:
        return None
    ...
    return {
        ...,
        "edge": round(dv["power_edge"], 4),
        "shin_edge": round(dv["shin_edge"], 4),
        "shin_z": round(dv["shin_z"], 4),
        "devig_method": dv["devig_method"],
    }
```

**ML-with-missing-paired-odds fallback:** keep `_passes_worst_case_filter` *only* as a guard inside `_dual_devig_check` for `raw_other <= 0.001` or `raw_other >= 0.999`. In that case we emit `devig_method="worst_case_fallback"` and fall back to today's behavior.

### 3.3 Pinnacle-Weighted Consensus

**File:** `scrapers/odds.py`, in the consensus construction at `:392-432` (and, symmetrically, in the F5 ML, F5 total, team total, F1 total, F1 spread, F3 ML, F3 total, F3 spread consensus — which today use *only* best-line devig rather than multi-book averaging).

**Config knobs (added to `config.py`):**

```python
SHARP_BOOK_WEIGHT = 0.60            # weight assigned to sharp books in aggregate
SHARP_BOOKS = ["pinnacle", "circa", "betcris"]   # lowercase book keys
BETTING_V2_ENABLED = False          # master flag for this spec
```

**Weighting algorithm** (replaces the current equal-weight averaging at `scrapers/odds.py:397-408, :411-424`):

```
Given per-book devigged probs for a side: [(book_key, p_book), ...]
split into sharp[] and non_sharp[].
if sharp and non_sharp:
    w_sharp = SHARP_BOOK_WEIGHT / len(sharp)
    w_nonsharp = (1 - SHARP_BOOK_WEIGHT) / len(non_sharp)
    consensus = sum(w_sharp * p for p in sharp) + sum(w_nonsharp * p for p in non_sharp)
elif sharp and not non_sharp:
    consensus = mean(sharp)         # collapses to equal weight
elif non_sharp and not sharp:
    consensus = mean(non_sharp)     # graceful fallback
```

Fallback semantics: if no sharp book is present in the `all_book_odds` dict, we log once per snapshot: `logger.info("no sharp books in consensus for %s", market_key)`. Today's equal-weight behavior is preserved exactly.

**Per-market refactor target:** extract a single `_weighted_consensus(book_entries: list[tuple[str, float, float]]) -> tuple[float, float, int]` helper (home_prob, away_prob, n_books) so the ML and RL paths share code. Wire it in for ML and RL first; the Phase-1 markets (F5/F3/team_total) currently just use best-line power-devig and will migrate to this helper as part of this spec.

**Snapshot log line:**

```
[odds] LAD@SF h2h: sharp=[pinnacle, circa] non_sharp=[fanduel, draftkings, betmgm] z=0.027
```

### 3.4 Best-Line Execution Metadata

**File:** `scrapers/odds.py`, `tracker.py`.

**`OddsData` additions** (appended to the existing dataclass at `scrapers/odds.py:76-97`):

```python
best_line_book: dict[str, str] = field(default_factory=dict)
# keys: {market}_{side}, e.g. "h2h_home", "totals_over",
#       "spreads_home", "f5_total_over", "team_total_home_over", ...
# values: book key ("pinnacle", "draftkings", ...)

best_line_odds: dict[str, int] = field(default_factory=dict)
# same keys, values: the American odds actually offered by that book
```

**Where they're filled:** the existing `best = {}` dict at `scrapers/odds.py:303` already tracks `(decimal, american, book_name)` per `(market_key, side_id)`. The new fields are a direct rename/expose of that data. Populate right after `odds_data.book_sources` is set in each block (`:353-390`), e.g.:

```python
if ("h2h", home) in best:
    odds_data.moneyline["home"] = best[("h2h", home)][1]
    odds_data.book_sources["h2h_home"] = best[("h2h", home)][2]
    odds_data.best_line_book["h2h_home"] = best[("h2h", home)][2]
    odds_data.best_line_odds["h2h_home"] = best[("h2h", home)][1]
```

(`book_sources` stays — tracker.py relies on it today.)

**`tracker.py` schema change** (`tracker.py:15-19` COLUMNS):

Add two columns: `best_book`, `best_odds`. Full new ordering:

```python
COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "market_prob", "edge", "kelly_pct",
    "best_book", "best_odds",                 # <- NEW
    "result", "profit",
    "close_odds", "close_prob", "clv_cents", "clv_pct",
    "shin_edge", "shin_z", "devig_method",    # <- NEW (§3.2 pass-through)
]
```

Migration: `_ensure_csv_has_columns()` helper that reads `data/bets.csv`, adds missing columns with empty values, writes back. Run once on module import. Idempotent.

**`log_bet()` changes:** accept `odds_data: OddsData` (optional, keyword). Map `(bet_type, side)` → best-line key using the same mapping `_parse_bet_for_clv` already encodes (`tracker.py:71-~150`). If match, pull `best_line_book` / `best_line_odds` onto the row; otherwise leave blank. CLV stays driven by closing lines; best-line fields let us later compute "CLV vs best available" as a separate column.

### 3.5 Correlated-Bet Kelly Cap

**New file:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/sizing.py`

**Public API:**

```python
from typing import TypedDict

class Bet(TypedDict, total=False):
    bet_type: str
    side: str
    edge: float
    kelly_pct: float
    # ... other fields flow through unchanged

CORRELATION_MULTIPLIER = 1.4   # read from config.MAX_SAME_GAME_EXPOSURE

def compute_correlation_groups(bets: list[Bet]) -> dict[str, list[Bet]]:
    """Cluster bets on the same game by empirical correlation.

    Group keys (deterministic):
        "A_run_home" : {ML home, RL home, total over, team_total_home over}
        "A_run_away" : {ML away, RL away, total under, team_total_away over}
                       + total under (symmetric)
        "B_f5"       : {F5 ML any side, F5 total over/under, F5 RL any side}
        "C_first_inn": {NRFI/YRFI, F1 RL any side}
        "D_tt_home"  : {team_total_home (either side), total (either side)}
        "D_tt_away"  : {team_total_away (either side), total (either side)}

    A bet may belong to multiple groups (e.g. total-over is in A_run_home
    if we also hold ML home; that's correct — it stacks correlation).
    Assignment rules are documented below.
    """

def cap_same_game_exposure(bets: list[Bet]) -> list[Bet]:
    """Cap summed kelly_pct across each correlation group to:

        best_leg_kelly * CORRELATION_MULTIPLIER

    Where best_leg_kelly = max(b.kelly_pct for b in group).

    Proportional scaling: if the group has legs [0.02, 0.015, 0.01]
    (sum 0.045) and the cap is 0.02 * 1.4 = 0.028, scale every leg by
    0.028/0.045 = 0.622, giving [0.01244, 0.00933, 0.00622].

    A bet that appears in multiple groups is capped by the tightest cap.
    Returns a new list; input is not mutated.
    """
```

**Assignment rules (deterministic, side-aware):**

- Group A_run_home fires iff there's a bet on any of: `{moneyline home, run_line home, total over, team_total_home over}`. All such bets join.
- Group A_run_away is the mirror: `{moneyline away, run_line away, total under, team_total_away over}`.
- Group B_f5: any bet in `{first_5_ml, first_5_total, first_5_rl}`.
- Group C_first_inn: any bet in `{nrfi, first_1_rl}`.
- Group D_tt_home: `{team_total_home (over or under), total (over or under)}` — regardless of direction, since the game total mechanically includes team totals.
- Group D_tt_away: `{team_total_away (...), total (...)}`.

Why the asymmetry between A (side-matched) and D (direction-agnostic)? A captures *outcome correlation* (home wins → scores a lot → over); D captures *decomposition* (team totals literally sum to the game total, so stacking both is double-exposure to the same statistic).

**Config (`config.py`):**

```python
MAX_SAME_GAME_EXPOSURE = 1.4   # multiple of best-leg kelly within a group
```

**Integration in `edge.py`:**

- After the edge-cap / derived-ML block (`edge.py:854-876`), replace the current "keep best 2 of run cluster" with:
  ```python
  from sizing import cap_same_game_exposure
  bets = cap_same_game_exposure(bets)
  ```
- Keep the original top-2 run-cluster filter as a **floor** behind a flag `SAFETY_KEEP_TOP_N` default 4 (looser than today's 2, since proportional scaling handles the exposure concern). A bet that gets scaled to `kelly_pct < 0.001` after the cap is dropped entirely.

### 3.6 Uncertainty-Shrinkage Kelly

**File:** `ensemble/orchestrator.py` → expose `prob_std`; `edge.py` → consume.

**`orchestrator.py` change:** after aggregating runs, compute stdev across runs for the *primary* probability field of each slot:

- moneyline → `home_win_prob`
- run_line → `favorite_cover_prob`
- total → derived via `predicted_score` (sum the per-run `home`+`away` stdev — or, simpler, stdev of per-run projected totals)
- first_5 → `f5_home_win_prob`
- team_total_home → `predicted_score.home`
- first_3 → `f3_home_win_prob`
- nrfi → `nrfi_prob`

Emit these as `predictions.<slot>.prob_std`. Downstream consumers that don't know the field just ignore it (dict access with default).

**`edge.py` change — new `_sized_kelly` signature:**

```python
UNCERTAINTY_K = 5.0
KELLY_FLOOR_FRACTION = 0.05 / 0.25   # floor at 5% Kelly; ceiling remains 25%

def _sized_kelly(prob: float, dec: float, prob_std: float = 0.0,
                 edge: float = 0.0) -> tuple[float, float]:
    """Return (raw_kelly_quarter, shrunk_kelly).

    shrink_factor = edge / (edge + UNCERTAINTY_K * prob_std ** 2)
    - edge>0 required; if edge<=0 return (0, 0).
    - shrink_factor clamped to [KELLY_FLOOR_FRACTION, 1.0].
    - raw_kelly_quarter = kelly_criterion(prob, dec) * KELLY_FRACTION
    - shrunk_kelly = raw_kelly_quarter * shrink_factor
    Rounded to 4 decimals.
    """
```

Returning a tuple is a breaking change to a private helper; every call site (all of the `_sized_kelly(home_prob, dec)` lines in `edge.py`) is updated in the same commit. The bet dict adds `kelly_raw` and `kelly_pct` (kelly_pct = shrunk).

**Worked example:** edge = 0.05, prob_std = 0.04 → `shrink = 0.05 / (0.05 + 5*0.0016) = 0.05 / 0.058 = 0.862`. Kelly trimmed ~14%. At prob_std = 0.08 → `shrink = 0.05 / (0.05 + 0.032) = 0.61` — trimmed ~39%. At prob_std = 0.15 → `shrink = 0.05 / (0.05 + 0.1125) = 0.308` — trimmed ~69%. Floor catches us at the 20% mark (= 0.05/0.25).

**Log lines:** one per bet returned:

```
[edge] LAD@SF total over 9.5 edge=0.054 prob_std=0.041 kelly_raw=0.0134 kelly_final=0.0115 shrink=0.859
```

### 3.7 Suspicious-Edge Quarantine

**File:** `edge.py`, replaces the cap block at `:854-866`.

**Config:**

```python
MAX_LEGITIMATE_EDGE = 0.15
```

**Replacement block:**

```python
bets_kept, quarantined = [], []
for bet in bets:
    cap = max(MAX_LEGITIMATE_EDGE,
              2 * EDGE_THRESHOLDS.get(bet["bet_type"], 0.05) + 0.07)
    if bet["edge"] > cap:
        bet["quarantine_reason"] = (
            f"edge {bet['edge']:.3f} > cap {cap:.3f} "
            f"(2*threshold+0.07={2*EDGE_THRESHOLDS.get(bet['bet_type'], 0.05)+0.07:.3f})"
        )
        quarantined.append(bet)
    else:
        bets_kept.append(bet)

if quarantined:
    _append_quarantine_csv(quarantined, game=f"{odds.away}@{odds.home}",
                           date=_today())
    logger.warning("Quarantined %d suspicious edges in %s@%s",
                   len(quarantined), odds.away, odds.home)

bets = bets_kept
```

**New CSV:** `data/quarantined_edges.csv`.

Schema:
```
date, game, bet_type, side, odds, sim_prob, market_prob, edge,
shin_edge, shin_z, kelly_pct, confidence, quarantine_reason,
reviewed, override_allow
```

- `reviewed` / `override_allow`: user-populated post-hoc. If `override_allow=true` is set by hand, a daily-runner helper (out of scope for this spec, tracked in §7 rollout) can re-inject the bet into today's card.

**Why raise to quarantine, not just cap?** An "edge" of 0.22 on a liquid MLB market is almost always a data bug (stale odds, wrong side label, mis-parsed alternate line) and firing it at the capped 0.15 quietly compounds whatever the underlying bug is. Humans review these; the 15% ceiling stops being a silent floor on real wagered exposure.

---

## 4. Math Reference

### 4.1 Shin (1993) De-Vig for 2-Way Markets

For a 2-way market, let:

- `pi_a`, `pi_b` = raw implied probabilities from American odds.
- `Sigma_pi = pi_a + pi_b` (>= 1, equals 1 + overround).
- `z` in `[0, 1)` = insider trader fraction (Shin's parameter).

Shin's identity states that each side's true probability is:

```
p_i = ( sqrt( z^2 + 4 * (1 - z) * pi_i^2 / Sigma_pi ) - z )
      / ( 2 * (1 - z) )
```

We pick `z` such that `p_a + p_b = 1`. For 2-way markets the solution has a closed form but it's messy; bisection on `z in [0, 0.2]` converges in ~30 iterations to `1e-10`.

### 4.2 Worked Example: Home -130 / Away +115

**Raw implied probs:**

- `pi_home = 130 / (130 + 100) = 0.5652`
- `pi_away = 100 / (115 + 100) = 0.4651`
- `Sigma_pi = 1.0303` (overround ~3.0%)

**Power de-vig** (what we ship today):

- Solve `0.5652^n + 0.4651^n = 1`, yields `n ≈ 1.0452`.
- `p_home = 0.5652^1.0452 = 0.5501`
- `p_away = 0.4651^1.0452 = 0.4499`

**Shin de-vig:**

- Try `z = 0.03`:
  - `inside_home = 0.03^2 + 4*0.97*0.5652^2 / 1.0303 = 0.0009 + 1.2010 = 1.2019`
  - `p_home = (sqrt(1.2019) - 0.03) / (2*0.97) = (1.0963 - 0.03) / 1.94 = 0.5496`
  - `inside_away = 0.0009 + 4*0.97*0.4651^2 / 1.0303 = 0.8149`
  - `p_away = (sqrt(0.8149) - 0.03) / 1.94 = (0.9027 - 0.03) / 1.94 = 0.4498`
  - Sum = `0.9994` — slightly low, bisect up.
- At `z ≈ 0.028`, sum hits 1 to `1e-6`. Final: `p_home = 0.5499`, `p_away = 0.4501`.

**Comparison:**

| Method      | p_home | p_away |
|-------------|--------|--------|
| Raw (with vig) | 0.5652 | 0.4651 |
| Power       | 0.5501 | 0.4499 |
| Shin        | 0.5499 | 0.4501 |
| Difference  | 0.0002 | 0.0002 |

For symmetric-overround 2-way markets, Shin and power agree to ~0.02 pp. The divergence alarm (`> 0.015`, i.e. 1.5 pp) is only tripped when raw implied probs are asymmetric (one side much heavier vig than the other), which is itself a sharpness signal worth logging.

### 4.3 Correlation Cap — Property

For any correlation group G with legs `k_1, ..., k_n` (kelly percents) and best `k* = max(k_i)`:

```
sum(k_i_after_cap) <= k* * CORRELATION_MULTIPLIER
```

Proof: `cap_same_game_exposure` scales all `k_i` by `min(1, k*/sum(k_i) * MULT)`. If the group already fits (`sum <= k* * MULT`), the scale factor is 1 and the property holds. Otherwise the scale factor is exactly `k* * MULT / sum`, so the post-scale sum is `k* * MULT` by construction. The max leg post-scale is at most `k*` and at least `KELLY_FLOOR_FRACTION * k*`.

### 4.4 Shrinkage Kelly — Monotonicity

`shrink(prob_std) = edge / (edge + k * prob_std^2)` is monotonically decreasing in `prob_std` for fixed positive `edge` and `k > 0`. As `prob_std → 0`, shrink → 1 (no shrinkage). As `prob_std → ∞`, shrink → 0; we floor at `KELLY_FLOOR_FRACTION = 0.2` to preserve small positions on high-uncertainty high-edge signals.

---

## 5. Data Shape Changes

### 5.1 `OddsData` (scrapers/odds.py:76)

```python
@dataclass
class OddsData:
    # ... existing fields unchanged ...
    # NEW:
    best_line_book: dict = field(default_factory=dict)   # §3.4
    best_line_odds: dict = field(default_factory=dict)   # §3.4
    shin_z: dict = field(default_factory=dict)           # §3.1 per-market {market_key: z}
    consensus_sharp_books: list = field(default_factory=list)  # §3.3 list of book keys used
```

`implied_probs` is unchanged in key names but now contains weighted values (§3.3). Old value keys (`ml_home`, `ml_away`, `rl_home`, `rl_away`, `ml_book_count`, `rl_book_count`) keep their meaning.

### 5.2 `data/bets.csv`

New columns (all default empty string on legacy rows):

- `best_book` — book key with the best available price for this side at bet time.
- `best_odds` — American odds at `best_book`.
- `shin_edge` — Shin-devig edge measurement at bet time.
- `shin_z` — insider fraction from the Shin fit for this market.
- `devig_method` — "agree" | "divergent" | "worst_case_fallback".

Migration helper in `tracker.py` reads the header, adds missing columns, writes back. Idempotent.

### 5.3 `data/quarantined_edges.csv` (NEW)

```
date, game, bet_type, side, odds, sim_prob, market_prob, edge,
shin_edge, shin_z, kelly_pct, confidence, quarantine_reason,
reviewed, override_allow
```

Written to by `edge.py:analyze_all_edges` via `_append_quarantine_csv`.

### 5.4 `data/devig_stats.csv` (NEW)

```
date, market, mean_z, median_z, book_count
```

Written once per daily run after the final odds pull. Read-only artifact for diagnostics.

### 5.5 `data/skipped_signals.csv` Interaction

Today's skipped-signals path (pre-existing in `edge.py` for sub-threshold edges) is not changed. Quarantine is an orthogonal filter: a bet is *either* kept, *or* skipped (sub-threshold), *or* quarantined (super-threshold). These three sets are disjoint. Tests enforce disjointness (§6.3).

---

## 6. Testing Strategy

New test files:

- `tests/test_shin_devig.py`
- `tests/test_weighted_consensus.py`
- `tests/test_best_line_metadata.py`
- `tests/test_sizing_correlation.py`
- `tests/test_uncertainty_shrinkage.py`
- `tests/test_quarantine.py`

Existing test files updated: `test_edge.py`, `test_edge_phase1.py`, `test_ensemble_orchestrator.py`.

### 6.1 Shin Formula Unit Tests (`test_shin_devig.py`)

- **Symmetric two-way**: `pi_a = pi_b = 0.525` (a -110/-110 market). Shin must return `(0.5, 0.5, z≈0.023)`. Power returns `(0.5, 0.5, n≈1.1)`. Agreement to 1e-4.
- **Asymmetric**: `-130/+115` → assert `p_home` within 1e-3 of 0.5499, `p_away` within 1e-3 of 0.4501 (worked example §4.2).
- **Heavy fav**: `-350/+275` → assert `0 < z < 0.05`, `p_home + p_away = 1 ± 1e-6`, `p_home in (0.77, 0.79)`.
- **Degenerate**: both sides 0.01 → returns normalized naive, `z = 0`.
- **Zero vig**: `pi_a + pi_b == 1.0` → returns `(pi_a, pi_b, 0.0)` (no bisection).
- **Published reference**: against [Shin 1993] Table 1 horse-racing values for 3-way (`shin_devig_many`), tolerance 1e-3.

### 6.2 Correlation-Cap Property Tests (`test_sizing_correlation.py`)

Hypothesis-style property tests:

- **Sum never exceeds cap**: for a random bets list on a single game, `sum(kelly_pct after cap) <= best_kelly * 1.4 + 1e-9`. Run 200 randomized cases.
- **Best leg preserved**: the post-cap bet with the largest `kelly_pct` is the same bet (by bet_type+side) as the pre-cap max.
- **Monotone scaling**: if all legs are scaled by factor `s < 1`, all `kelly_pct` fall; none rise.
- **Empty / single-leg**: zero-leg game returns empty; single-leg returns unchanged.
- **Cross-group overlap**: a bet in two groups (e.g. total-over both in A_run_home and D_tt_home) is scaled by the tighter cap.
- **Floor**: a leg scaled below 0.001 kelly is dropped.

### 6.3 Quarantine Golden Tests (`test_quarantine.py`)

- Hand-crafted "obviously bad" edges (`edge = 0.25`) land in quarantine CSV; do not appear in returned bet list.
- Edge at exactly `cap` is kept (`<=` stays, `>` quarantines).
- `2*threshold+0.07` dominates when `threshold > 0.04`: e.g. for `team_total_home` with threshold 0.06, cap = `max(0.15, 0.19) = 0.19`.
- Disjointness: for a synthetic slate, `set(kept) ∩ set(quarantined) = ∅` and `set(kept) ∪ set(quarantined) ∪ set(skipped) = set(all_candidates)`.
- CSV append is atomic / idempotent (run twice with same input → no duplicate rows).

### 6.4 Other Coverage

- `test_weighted_consensus.py`: Pinnacle absent → equal-weight; Pinnacle+FD → weights 0.60/0.40; Pinnacle+FD+DK+MGM → 0.60/0.1333×3; list of sharp books present is logged.
- `test_best_line_metadata.py`: `OddsData.best_line_book["h2h_home"]` matches the book with numerically best decimal odds; tie-break is first-seen.
- `test_uncertainty_shrinkage.py`: `prob_std = 0` → `kelly_shrunk == kelly_raw`; `prob_std >> 0` → floored at `0.2 * kelly_raw`; `edge <= 0` → both zero.
- `test_ensemble_orchestrator.py`: `prob_std` appears for every slot with ≥ 2 runs; is 0.0 when only one run completed.

### 6.5 End-to-End Smoke

One integration test in `tests/test_edge.py` that:

1. Builds a synthetic `OddsData` with Pinnacle + 3 retail books.
2. Builds a synthetic `sim` with calibrated probs and per-slot `prob_std`.
3. Runs `analyze_all_edges`.
4. Asserts: no bet exceeds `MAX_LEGITIMATE_EDGE`; correlation group sums respect cap; quarantine CSV written when input is rigged to produce 0.22 edge; `shin_edge` and `shin_z` present on every returned bet.

---

## 7. Rollout

### Phase 0: Flag Gate

- Land all code behind `config.BETTING_V2_ENABLED = False`.
- `edge.py:analyze_all_edges` runs both pipelines in parallel when the flag is true *and* `config.BETTING_V2_SHADOW_COMPARE = True`, logging any divergence to `data/v2_shadow.csv`. This gives us two weeks of live shadow data before the cutover.
- `tracker.log_bet` always writes the v2 columns; they're blank-default on legacy rows and so tolerate flag flips.

### Phase 1: Shadow Period (2 weeks)

- Flag on for *shadow only*. User continues to bet from v1 card.
- Daily job diffs v1 vs v2 bet cards; `scripts/compare_v1_v2.py` (new) outputs:
  - Bets present in v1 but not v2 (quarantined or scaled below floor).
  - Bets present in v2 but not v1 (shouldn't exist — v2 is strictly more conservative).
  - Kelly deltas per bet.
- Grading is CLV-based per Spec 1. Compare v2-sized hypothetical P&L vs v1 actual.

### Phase 2: Cutover

- Flip `BETTING_V2_ENABLED = True`, keep shadow off. One week of monitored live betting.
- Rollback: flip flag back. All v2 CSV columns remain populated; the v1 path uses the non-v2 columns. No schema reversion required.

### Phase 3: Sunset

- After 30 days of live v2 betting with no regressions, remove the flag and the v1 branches. `_passes_worst_case_filter` deleted. The "keep top 2 of run cluster" safety floor is kept indefinitely.

---

## 8. Risks

### 8.1 Pinnacle Absent for Props / Alt Markets

The Odds API does not universally include Pinnacle on every market (it's more reliably present on h2h / spreads / totals than on F1 RL or team totals). Mitigation:

- Equal-weight fallback is explicit and logged (§3.3). No silent degradation.
- Track per-market "sharp book present" rate in `devig_stats.csv`. If a market's sharp-presence rate falls below 40% over a week, alert and consider adding another sharp book (Betcris, Circa) to `SHARP_BOOKS`.

### 8.2 Shin Math Edge Cases

- **z → 0**: Shin collapses to `pi_i / Sigma_pi` (naive normalization). Covered by the zero-vig early-return.
- **z → 1**: denominator `2 * (1 - z)` → 0. Bisection is bracketed at `z <= 0.2` which leaves 5× headroom; in practice we'll never sit near the upper bound without the book being broken. If bisection returns `z > 0.18`, log a warning and fall back to power de-vig.
- **Negative discriminant**: `z^2 + 4*(1-z)*pi^2/Sigma_pi` can't be negative for real pi in [0,1] and z in [0,1], but guard with `max(0, ...)` before `sqrt` defensively.
- **Numerical drift in bisection**: reuse the same 100-iteration / `1e-10` / `abs(val - 1.0)` short-circuit pattern as `power_devig`; identical convergence guarantees.

### 8.3 Correlation Cap Starving High-Edge Games

If a game produces 5 legs with edges in [0.06, 0.09], the correlation cap can drop each from quarter-Kelly ~0.02 to ~0.008. The concern: we may bet "too little" on a genuinely strong slate.

Mitigations:

- `CORRELATION_MULTIPLIER = 1.4` is conservative by design (not 1.0) — we *do* let correlated bets stack, just not independently.
- The parameter is a single-line config knob. If two weeks of data shows we're systematically under-betting correlated clusters, raise it to 1.6 or 1.8.
- The floor at `kelly_pct < 0.001 → drop` prevents micro-bets; the bet stays on the card as "scaled out" with reason logged.
- A grade report in Spec 1's CLV loop surfaces "v2 reduced Kelly by >50%" cases so we can audit whether the reduction tracked actual correlated losses.

### 8.4 Mixed Bet-Level Semantics During Shadow

During Phase 1, `analyze_all_edges` returns the v1 list while computing v2 shadow data. Care must be taken that:

- The log_bet call writes v1 numbers (since the user is betting v1).
- The v2 shadow CSV is entirely separate (`data/v2_shadow.csv`).
- `prob_std` is emitted by the ensemble regardless — harmless if unused.

Integration test `test_shadow_mode.py` covers this.

### 8.5 Best-Line Metadata Staleness

`best_line_book` captures the best price *at odds-pull time*, not at bet-placement time. If the user bets 30 minutes later, that book may have moved. Mitigations:

- `log_bet()` records a `best_book_snapshot_time` (reuses existing `now()` already written for the bet timestamp).
- Downstream CLV analysis treats best-line as "best available when the pipeline ran" — honest and sufficient for the goal of making CLV more meaningful than raw consensus-close.

---

## Appendix A: Config Diff Summary

```python
# config.py additions
BETTING_V2_ENABLED = False
BETTING_V2_SHADOW_COMPARE = True

SHARP_BOOK_WEIGHT = 0.60
SHARP_BOOKS = ["pinnacle", "circa", "betcris"]

MAX_SAME_GAME_EXPOSURE = 1.4         # aka CORRELATION_MULTIPLIER
MAX_LEGITIMATE_EDGE = 0.15
UNCERTAINTY_K = 5.0
KELLY_FLOOR_FRACTION = 0.20          # fraction of full quarter-Kelly; floor
SAFETY_KEEP_TOP_N = 4                # safety net under correlation cap
```

## Appendix B: File Change Inventory

| File                                    | Change    | Lines touched                    |
|-----------------------------------------|-----------|----------------------------------|
| `scrapers/odds.py`                      | Edit      | +`shin_devig`, +`shin_devig_many`, refactor consensus loop (~ :392-432), extend `OddsData` (~ :76-97), populate best-line fields in each `if ("market", side) in best` block (~ :353-390) |
| `edge.py`                               | Edit      | Remove `_passes_worst_case_filter` usage at ~20 call sites; add `_dual_devig_check`; extend `_sized_kelly` signature; replace edge-cap block at :854-866; swap run-cluster filter for `cap_same_game_exposure` |
| `sizing.py`                             | **NEW**   | `compute_correlation_groups`, `cap_same_game_exposure` |
| `ensemble/orchestrator.py`              | Edit      | Emit `prob_std` per slot         |
| `tracker.py`                            | Edit      | Extend `COLUMNS` at :15-19; add `_ensure_csv_has_columns`; thread `OddsData` into `log_bet` |
| `config.py`                             | Edit      | Add knobs from Appendix A        |
| `tests/test_shin_devig.py`              | **NEW**   | See §6.1                         |
| `tests/test_weighted_consensus.py`      | **NEW**   | See §6.4                         |
| `tests/test_best_line_metadata.py`      | **NEW**   | See §6.4                         |
| `tests/test_sizing_correlation.py`      | **NEW**   | See §6.2                         |
| `tests/test_uncertainty_shrinkage.py`   | **NEW**   | See §6.4                         |
| `tests/test_quarantine.py`              | **NEW**   | See §6.3                         |
| `tests/test_edge.py`                    | Edit      | Add §6.5 smoke                   |
| `tests/test_ensemble_orchestrator.py`   | Edit      | Assert `prob_std` present        |
| `scripts/compare_v1_v2.py`              | **NEW**   | Shadow-period diff tool          |

## Appendix C: Open Questions (for Plan 2 author)

1. Should the correlation cap consider *remaining-bankroll exposure* across games, not just same-game? (Out of scope for this spec; flagged for the Plan author.)
2. When a quarantined bet is manually `override_allow`'d, do we inject it at the capped kelly (0.15 edge) or the raw edge? Default proposal: capped.
3. Is 2 weeks enough shadow? Spec 1's CLV metric takes ~300 bets for 1σ resolution; we'll hit that in 2 weeks of normal slate. Plan author should verify.
