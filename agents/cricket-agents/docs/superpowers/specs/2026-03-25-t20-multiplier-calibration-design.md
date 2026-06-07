# T20 Cricket Multiplier Calibration Design

## Problem

The current `edge.py` detects edges by comparing LLM-simulated probabilities against
odds-implied probabilities using Kelly criterion. This couples edge detection to the
specific odds the system sees, but the user may bet at different odds at their own book.

The generalized edge framework instead derives edge from **projected values vs lines**:
the model predicts what will actually happen, compares to the line, and outputs a
probability and edge. The user brings their own odds.

## Goal

Calibrate stat-specific parameters for T20 cricket that convert the delta between a
projected value and a betting line into an accurate probability estimate. Three
probability engines (linear, exponential, Poisson) match each stat's distribution.
Expand from 2 bet types (moneyline + total_runs) to 15 across 4 tiers.

## Architecture

### Three Probability Engines

### Side Selection: Probability-Based, Not Delta-Based

All three engines select the side ("over" or "under") based on **which probability
exceeds 0.50**, not on the sign of `projected - line`. This is critical because for
non-symmetric distributions (exponential, Poisson), the median differs from the mean.
For example, an exponential distribution's median is `mean * ln(2) ≈ 0.693 * mean`,
so `projected > line` does NOT imply P(over) > 0.50.

The edge is always non-negative: `edge = max(P(over), P(under)) - 0.50`. The threshold
check is simply `edge >= threshold` (no `abs()` needed).

**Engine 1 — Linear Multiplier** (for continuous/near-normal distributions):

```python
def calculate_linear_edge(projected: float, line: float, multiplier: float):
    delta = projected - line
    prob_over = max(0.01, min(0.99, 0.50 + delta * multiplier))
    prob_under = 1.0 - prob_over
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = prob - 0.50
    return side, projected, prob, edge
```

Used when the stat's distribution is approximately normal or has a high enough mean
(>5) that the normal approximation holds. For the linear engine, probability-based
and delta-based side selection are equivalent (the formula is symmetric around 0.50).
The multiplier is derived from:

```
multiplier = 1 / (2 * typical_std_dev)
```

This means a **0.5-std-dev delta maps to 75% confidence**, and the model saturates
(hits the 0.99 clamp) at ~1 std dev. This is intentionally aggressive — in betting
markets, useful projection deltas are typically in the 0.1-0.5 SD range. A full
standard deviation of edge is rare and should produce near-certainty.

**Engine 2 — Exponential CDF** (for right-skewed stats where mean ~ std_dev):

```python
import math

def calculate_exponential_edge(projected_mean: float, line: float):
    prob_over = math.exp(-line / projected_mean)
    prob_under = 1.0 - prob_over
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = prob - 0.50
    return side, projected_mean, prob, edge
```

Used when the stat follows an exponential/geometric distribution (mean approximately
equals std_dev). Cricket batting runs are the canonical example: scores follow a
memoryless distribution with ~5-10% duck probability. The linear model overestimates
"over" probabilities by 10-15 percentage points on these stats; the exponential CDF
eliminates this systematic error.

Note: because the exponential median is below the mean, the engine will correctly pick
"under" even when `projected > line`, as long as `line` falls between the median and
the mean. For example, with `projected=30, line=25`: `P(over) = exp(-25/30) = 0.434`,
so the engine correctly picks "under" with edge = 0.066.

**Engine 3 — Poisson CDF** (for discrete count stats with typical mean < 5):

```python
import math
from scipy.stats import poisson

def calculate_poisson_edge(projected_mean: float, line: float):
    prob_over = 1.0 - poisson.cdf(math.floor(line), mu=projected_mean)
    prob_under = poisson.cdf(math.floor(line), mu=projected_mean)
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = prob - 0.50
    return side, projected_mean, prob, edge
```

Used when the stat is discrete, low-mean, and zero-inflated (e.g., wickets where ~40%
of spells yield 0). The Poisson CDF naturally handles the asymmetry and discreteness
that breaks the linear model. Uses `math.floor()` (not `int()`) for correct behavior
with all numeric inputs. Note: for half-integer lines (0.5, 1.5, 2.5), which are the
standard in cricket betting, there is no push case. If integer lines are encountered,
the push probability is absorbed into the "under" side.

**Why the cutoff at mean < 5:** By the CLT, Poisson(lambda) approximates
Normal(lambda, sqrt(lambda)) when lambda > ~10. Below ~5, the discrete jumps and
zero-inflation create meaningful errors in the linear model. Between 5-10 is a gray
zone where either works — we use 5 as the conservative cutoff.

### All Three Engines Produce Identical Output

```python
{
    "bet_type": "player_wickets",
    "side": "over 1.5",
    "player": "Jasprit Bumrah",
    "projected": 1.8,
    "probability": 0.537,
    "edge": 0.037
}
```

The rest of the pipeline (Kelly sizing, ensemble consensus, bet tracking) does not need
to know which engine produced the numbers.

## Calibrated Multipliers

### Derivation Method

For each stat type, the typical standard deviation was estimated from:

1. **IPL historical data** (2018-2025) via ESPNcricinfo and SweepCricket
2. **T20 International distributions** from academic research (Monte Carlo simulations,
   PMC batting simulation papers, arXiv bowling analysis)
3. **Cross-league validation** across BBL, CPL, PSL, SA20, The Hundred
4. **Betting market data** from DraftKings, bet365, Betfair for line availability

The multiplier formula `1 / (2 * std_dev)` produces a probability shift such that a
0.5-std-dev delta maps to 75% confidence and the model saturates near 1 std dev. In
betting markets, useful projection deltas are typically 0.1-0.5 SD, making this range
the active zone for edge detection.

### Tier 1 — Core Markets

High liquidity, available via the Odds API. Edge threshold: **6%** (sharp markets
require strong signal).

| Stat Key | Engine | Std Dev | Multiplier | Threshold | Distribution Notes |
|----------|--------|---------|------------|-----------|-------------------|
| `moneyline` | direct | — | — | 0.06 | Direct win probability from ensemble; edge = prob - 0.50 |
| `match_total_runs` | linear | 60 | 0.008 | 0.06 | Both innings combined. ~Normal, slight right skew. IPL mean 340-355, BBL 290-310 |
| `team_total_runs` | linear | 30 | 0.017 | 0.06 | Single innings. 1st innings SD ~28, 2nd innings SD ~33 (bimodal from chase dynamics). Use 30 as blend |
| `spread` | linear | 20 | 0.025 | 0.06 | Victory margin in runs. Right-skewed (log-normal). Most margins 5-30, occasional 80+ blowouts |

### Tier 2 — Player Props

Available on major sportsbooks (bet365, DraftKings, Betfair). Edge threshold: **5%**
(moderately soft markets).

| Stat Key | Engine | Std Dev | Multiplier | Threshold | Distribution Notes |
|----------|--------|---------|------------|-----------|-------------------|
| `player_runs` | exponential | — | — | 0.05 | Exponential/geometric distribution (mean ~ std_dev). Lines typically 19.5-34.5 for top order. Heavily right-skewed with ~5-10% duck probability. Exponential CDF used because linear model overestimates "over" by 10-15 ppts |
| `player_wickets` | poisson | — | — | 0.05 | Mean ~1.1 per 4-over spell. ~40% zero probability. Lines at 0.5 or 1.5. Poisson CDF handles discreteness |
| `player_boundaries` | poisson | — | — | 0.05 | 4s + 6s combined. Mean ~4 per innings. Lines at 3.5 or 4.5. Zero-inflated when dismissed early |
| `player_sixes` | poisson | — | — | 0.05 | Mean ~1.5 (power hitters) to ~0.8 (accumulators). Lines at 0.5 or 1.5. Highly zero-inflated |

### Tier 3 — Phase & Specialty Markets

Available on select sportsbooks. Edge threshold: **4%** (softest markets, smaller edges
still profitable).

| Stat Key | Engine | Std Dev | Multiplier | Threshold | Distribution Notes |
|----------|--------|---------|------------|-----------|-------------------|
| `powerplay_runs` | linear | 16 | 0.031 | 0.04 | First 6 overs. ~Normal. IPL mean 50-61, BBL 40-52. Lines at 45.5-55.5 |
| `match_total_sixes` | linear | 6 | 0.083 | 0.04 | Right-skewed but mean ~13 (IPL) justifies linear. Range 2-42 |
| `match_total_fours` | linear | 6 | 0.083 | 0.04 | Remarkably stable at ~27 per match (IPL). More normal than sixes |
| `first_over_runs` | linear | 4 | 0.125 | 0.04 | Micro-market. Very soft lines. Mean 5.5-6.5. Low limits but high edge potential |
| `fall_of_first_wicket` | exponential | — | — | 0.04 | Opening partnership runs. Exponential distribution (mean ~ std_dev). Lines at 23.5-25.5. Soft market. Same rationale as player_runs |

### Tier 4 — Bowling Props

Limited availability, mainly Asian sportsbooks. Edge threshold: **5%**.

| Stat Key | Engine | Std Dev | Multiplier | Threshold | Distribution Notes |
|----------|--------|---------|------------|-----------|-------------------|
| `runs_conceded` | linear | 11 | 0.045 | 0.05 | Per 4-over spell. ~Normal, slight right skew. Mean 30-34. Lines at 28.5-34.5 |
| `dot_balls` | linear | 3.5 | 0.143 | 0.05 | Per 4-over spell. Binomial-like (24 Bernoulli trials). Mean 8-10. Rare market |

## Stat Types NOT Included

| Stat | Reason |
|------|--------|
| Death overs runs | Bimodal distribution (depends on wickets in hand at over 16). Cannot model pre-match |
| Middle overs runs | Very low liquidity. Rarely available as a market |
| Balls faced | Rarely offered as a betting line |
| Strike rate | Noisy ratio stat, heteroscedastic variance. Not a direct market |
| Economy rate | Derived from runs conceded, not a direct market |
| Maidens | Too rare (~3-5% probability per spell). Not a viable market |
| Fantasy points | DFS-only, not sportsbook. Different ecosystem |

## Configuration Structure

```python
# In config.py

BET_TYPES = {
    # Tier 1 — Core
    "moneyline": {
        "engine": "direct",
        "threshold": 0.06,
        "tier": 1,
    },
    "match_total_runs": {
        "engine": "linear",
        "std_dev": 60,
        "multiplier": 0.008,
        "threshold": 0.06,
        "tier": 1,
    },
    "team_total_runs": {
        "engine": "linear",
        "std_dev": 30,
        "multiplier": 0.017,
        "threshold": 0.06,
        "tier": 1,
    },
    "spread": {
        "engine": "linear",
        "std_dev": 20,
        "multiplier": 0.025,
        "threshold": 0.06,
        "tier": 1,
    },
    # Tier 2 — Player Props
    "player_runs": {
        "engine": "exponential",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_wickets": {
        "engine": "poisson",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_boundaries": {
        "engine": "poisson",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_sixes": {
        "engine": "poisson",
        "threshold": 0.05,
        "tier": 2,
    },
    # Tier 3 — Phase & Specialty
    "powerplay_runs": {
        "engine": "linear",
        "std_dev": 16,
        "multiplier": 0.031,
        "threshold": 0.04,
        "tier": 3,
    },
    "match_total_sixes": {
        "engine": "linear",
        "std_dev": 6,
        "multiplier": 0.083,
        "threshold": 0.04,
        "tier": 3,
    },
    "match_total_fours": {
        "engine": "linear",
        "std_dev": 6,
        "multiplier": 0.083,
        "threshold": 0.04,
        "tier": 3,
    },
    "first_over_runs": {
        "engine": "linear",
        "std_dev": 4,
        "multiplier": 0.125,
        "threshold": 0.04,
        "tier": 3,
    },
    "fall_of_first_wicket": {
        "engine": "exponential",
        "threshold": 0.04,
        "tier": 3,
    },
    # Tier 4 — Bowling Props
    "runs_conceded": {
        "engine": "linear",
        "std_dev": 11,
        "multiplier": 0.045,
        "threshold": 0.05,
        "tier": 4,
    },
    "dot_balls": {
        "engine": "linear",
        "std_dev": 3.5,
        "multiplier": 0.143,
        "threshold": 0.05,
        "tier": 4,
    },
}

# Which tiers are active (user can enable/disable)
ACTIVE_TIERS = [1, 2, 3, 4]
```

## Edge Detection Flow

```
For each bet available from odds/lines:
  1. Look up bet_type in BET_TYPES config
  2. Skip if bet_type's tier not in ACTIVE_TIERS
  3. Get the ensemble's projected value for this stat
  4. If engine == "direct" (moneyline):
       For each team (a, b):
         prob = ensemble_win_prob for that team
         edge = prob - 0.50
         if edge >= threshold: surface
  5. If engine == "linear":
       prob_over = clamp(0.50 + (projected - line) * multiplier, 0.01, 0.99)
       prob_under = 1.0 - prob_over
       side, prob = ("over", prob_over) if prob_over >= prob_under else ("under", prob_under)
       edge = prob - 0.50
  6. If engine == "exponential":
       prob_over = exp(-line / projected)
       prob_under = 1.0 - prob_over
       side, prob = ("over", prob_over) if prob_over >= prob_under else ("under", prob_under)
       edge = prob - 0.50
  7. If engine == "poisson":
       prob_over = 1 - poisson.cdf(floor(line), mu=projected)
       prob_under = poisson.cdf(floor(line), mu=projected)
       side, prob = ("over", prob_over) if prob_over >= prob_under else ("under", prob_under)
       edge = prob - 0.50
  8. If edge >= threshold: surface the bet (edge is always >= 0)
  9. If odds available: kelly_pct = kelly(prob, decimal_odds) * KELLY_FRACTION
  10. Output: {bet_type, side, projected, probability, edge, kelly_pct?}
```

## Integration with Existing System

### What Changes

1. **`edge.py`** — Rewrite. Replace Kelly-based approach with the three-engine framework.
   Keep `american_to_decimal()` and `kelly_criterion()` for optional bet sizing (see
   below). Add `calculate_linear_edge()`, `calculate_exponential_edge()`,
   `calculate_poisson_edge()`, `analyze_all_edges()` dispatcher.

2. **`config.py`** — Add `BET_TYPES` dict (above). Replace `EDGE_THRESHOLDS` and
   `BET_SLOTS`. Keep `KELLY_FRACTION` for bet sizing.

3. **`simulate.py`** — Update system prompt to request projections for all 15+ bet types
   (organized by tier). The 6-analyst panel should output projected values, not just
   probabilities. Define JSON schema for the expanded output.

4. **`tracker.py`** — Expand CSV schema to handle new bet types. Add `tier` and
   `projected` columns.

5. **`simulate.py` `_average_results()`** — Update to handle averaging across all bet
   types, not just the current hard-coded moneyline/total_runs fields.

### Kelly Sizing: Edge vs Sizing Are Separate Concerns

The key semantic change: **edge detection no longer uses odds**. Edge is derived purely
from projected values vs lines. However, **bet sizing still uses odds** via Kelly
criterion. The flow is:

```
1. Edge detection: projected vs line → probability, edge (no odds involved)
2. Threshold filter: edge >= threshold? → surface the bet
3. Bet sizing (optional): kelly(probability, decimal_odds) → kelly_pct
```

When odds are available (from the Odds API), Kelly sizing applies as before. When odds
are not available (manual line entry, Tier 3/4 markets), the system surfaces the bet
with edge but without Kelly sizing — the user decides their own stake.

`american_to_decimal()` and `kelly_criterion()` remain in `edge.py` for step 3.

### What Stays the Same

- Ensemble orchestrator (3-phase voting) — unchanged
- Scrapers — unchanged (already collect necessary data)
- Kelly fraction (0.125) — unchanged, applied in sizing step after edge detection
- Bet card formatting agent — adapts to new bet types
- Results grader agent — adapts to new bet types

### New Dependency

`scipy` is required for the Poisson CDF engine. Add to `requirements.txt`.

### Migration Path

The current `total_runs` bet type maps to `match_total_runs`. The current `moneyline`
stays as-is. All other bet types are new additions. No existing bets break.

## Calibration Confidence & Known Limitations

### High Confidence (well-sourced, stable distributions)
- `match_total_runs` — Large sample sizes across leagues, well-studied
- `team_total_runs` — Academic research with explicit std dev measurements
- `player_runs` — Exponential distribution well-characterized in cricket literature
- `match_total_fours` — Remarkably stable across IPL history

### Medium Confidence (reasonable estimates, some uncertainty)
- `player_wickets` — Poisson is a good fit, but overdispersion possible
- `player_boundaries` — Count data with correlation to runs
- `powerplay_runs` — Format/rule changes (Impact Player) shift distributions
- `match_total_sixes` — Rapidly inflating trend (IPL 2024: 17/match vs 10.5 in 2008)

### Lower Confidence (limited data, volatile markets)
- `first_over_runs` — Very small sample per ball, high noise
- `fall_of_first_wicket` — Exponential fit assumed, limited direct measurements
- `dot_balls` — Rare market, limited historical line data
- `runs_conceded` — Phase-of-game effects create high contextual variance

### Limitation: Non-Normal Distributions

The linear multiplier assumes symmetric probability around 0.50. For right-skewed stats
still using the linear engine (match_total_sixes, powerplay_runs), this systematically:
- **Underestimates** the probability of the "over" (right-tail events more likely than
  normal predicts)
- **Overestimates** the probability of the "under"

The most severely affected stats (`player_runs`, `fall_of_first_wicket`) now use the
exponential engine, which eliminates the 10-15 ppt systematic error that the linear
model would produce on these stats. Remaining linear stats have mild skew where the
error is within 2-3 ppts — acceptable given projection uncertainty.

Mitigation: monitor hit rates per side and adjust multipliers if systematic bias appears.

### Limitation: Era Drift

T20 cricket scoring has inflated sharply (IPL 2024 averaged ~191/innings vs ~158 in
2015). The std dev estimates reflect the current era (2022-2025). These multipliers
should be re-calibrated annually or when format rules change (e.g., Impact Player rule).

## Testing Strategy

1. **Unit tests** for all three engines with known inputs/outputs
2. **Property tests**: linear engine probability always in [0.01, 0.99], edge always in
   [0.0, 0.49] (always non-negative). Exponential engine probability always in (0, 1).
3. **Poisson sanity checks**: P(over 0.5 wickets) with mean 1.1 should be ~0.667
4. **Exponential sanity checks**: P(over 25 runs) with mean 30 should be ~0.434
   (= exp(-25/30)). Verify this is more accurate than linear (which gives 0.60).
5. **Integration test**: full edge detection pipeline with mock ensemble output
6. **Config validation**: assert all linear-engine entries satisfy
   `abs(multiplier - 1/(2*std_dev)) < 0.001` at startup
7. **Backtesting**: once 50+ bets are tracked per type, compare predicted probabilities
   vs actual hit rates. Adjust multipliers if calibration is off by >5 percentage points.

## Success Criteria

1. All 15 bet types produce valid (projected, probability, edge) outputs
2. Edge detection correctly identifies "over" vs "under" for each stat
3. Poisson engine produces more accurate probabilities than linear for wickets/sixes
   (validated via synthetic test cases with known Poisson distributions)
4. Exponential engine produces more accurate probabilities than linear for player_runs
   and fall_of_first_wicket (validated against known exponential distributions)
5. Existing moneyline and total_runs edges are preserved (regression test)
6. Tiered thresholds correctly filter: Tier 1 at 6%, Tier 2 at 5%, Tier 3 at 4%,
   Tier 4 at 5%
7. Kelly sizing works when odds are available, gracefully omitted when not
