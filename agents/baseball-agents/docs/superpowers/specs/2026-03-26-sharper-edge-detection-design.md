# Sharper Edge Detection Design

**Date:** 2026-03-26
**Status:** Approved
**Scope:** 5 surgical improvements to the edge calculation pipeline

## Problem

The edge pipeline has 5 precision leaks that systematically degrade edge accuracy:

1. **Naive vig removal** distributes vig equally across both sides, mispricing favorites by ~1.6%
2. **F5 total heuristic** (`0.5 + delta * 0.10`) has no theoretical basis and underestimates edge at extremes by up to 7.6%
3. **Single-bookmaker selection** ignores better lines available in the same API response
4. **Confidence levels unused** in ensemble probability averaging despite being tracked per model
5. **No calibration injection point** makes future calibration require shotgun surgery across 12 edge checkers

## Fix 1: Power Method Vig Removal

### Current Behavior
```python
total_prob = ml_home + ml_away
ml_home_adjusted = ml_home / total_prob  # Equal vig distribution
```

### New Behavior
Solve for exponent `n` such that `p_home^n + p_away^n = 1` using bisection/Brent's method.

```python
def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method. Solves for n where p_a^n + p_b^n = 1."""
```

### Files Changed
- `scrapers/odds.py` — Add `power_devig()`, replace normalization at lines 258-268
- `edge.py` — Replace all inline vig removal (lines 106-108, 155-159, 208-212, 270-273, 340-344, 401-405, 472-476, 525-528, 582-586) with calls to centralized `devig()` function in `scrapers/odds.py`

### Impact
On a -200/+170 line:
- Naive: home=0.5714, away=0.4286
- Power: home=0.5556, away=0.4444
- **1.6% shift** on favorite side

## Fix 2: Replace F5 Total Heuristic with Poisson

### Current Behavior
```python
delta = projected - line
over_prob = min(max(0.5 + delta * 0.10, 0.01), 0.99)  # Arbitrary
```

### New Behavior
```python
over_prob = _poisson_over_prob(float(projected), line)  # Already exists
```

### Files Changed
- `edge.py` — `check_f5_total_edge()` lines 275-279: replace heuristic with `_poisson_over_prob()` call

### Impact
Projected 6.5 vs line 4.5:
- Heuristic: 70%
- Poisson: 77.6%
- **7.6% edge correction** at extremes

## Fix 3: Best-Line Selection Across Bookmakers

### Current Behavior
```python
for bk in event.get("bookmakers", []):
    # parse markets...
    if odds_data.moneyline:
        break  # Takes first book
```

### New Behavior
Iterate all bookmakers, collect all lines, pick best price per side.

"Best price" = highest decimal odds per side:
- Negative American: closest to 0 (-105 beats -115)
- Positive American: highest value (+175 beats +160)

### Files Changed
- `scrapers/odds.py` — `get_mlb_odds()` lines 207-252: remove early `break`, iterate all books, select best line per side per market
- `scrapers/odds.py` — `get_additional_odds()` line 133-136: same pattern
- `scrapers/odds.py` — Add `book_sources: dict` field to `OddsData` for logging which book provided each line

### Implementation Detail
```python
# For each market side, track best decimal odds seen
best = {}  # {(market, side): (decimal_odds, american_odds, book_name)}
for bk in event.get("bookmakers", []):
    for market in bk.get("markets", []):
        for outcome in market["outcomes"]:
            key = (market["key"], outcome["name"])
            dec = american_to_decimal(outcome["price"])
            if key not in best or dec > best[key][0]:
                best[key] = (dec, outcome["price"], bk["key"])
```

### Impact
Typical 5-15 cent spread between books:
- -110 vs -105 found elsewhere: **1.16% implied probability gain**
- +150 vs +160 found elsewhere: **1.54% gain**

## Fix 4: Confidence Weighting in Ensemble Averaging

### Current Behavior
```python
def weighted_average_prob(runs, weights):
    w = weights.get(run["model_key"], 1.0)  # Ignores confidence
```

### New Behavior
```python
CONFIDENCE_MULTIPLIERS = {"high": 1.3, "medium": 1.0, "low": 0.7}

def weighted_average_prob(runs, weights, confidences=None):
    w = weights.get(run["model_key"], 1.0)
    if confidences:
        conf = confidences.get(run["model_key"], "medium")
        w *= CONFIDENCE_MULTIPLIERS.get(conf, 1.0)
```

### Files Changed
- `ensemble/consensus.py` — Add `CONFIDENCE_MULTIPLIERS`, modify `weighted_average_prob()` signature and loop
- `ensemble/orchestrator.py` — In `build_ensemble_result()`, extract per-model confidence per slot and pass to `weighted_average_prob()`

### Impact
High-confidence models pull average ~8% more toward their estimate. Conservative multipliers (1.3/0.7) prevent single-model domination.

## Fix 5: Calibration Identity Hook

### Current Behavior
Edge checkers read raw ensemble probabilities directly. No injection point for future calibration.

### New Behavior
```python
# calibrate.py
def apply_calibration(prob: float, bet_type: str = "") -> float:
    """Identity today. Isotonic regression once 200+ bets available."""
    return prob
```

### Files Changed
- `calibrate.py` — Add `apply_calibration()` function
- `edge.py` — Import and apply before every edge calculation in all 12 checkers

### Secondary Fix
`orchestrator.py:357` has hardcoded `market_prob = implied.get("ml_home", 0.5)` for all bet types in prediction logging. Fix to look up correct implied prob per slot.

### Impact
Zero behavior change today. Clean injection point for future calibration with no shotgun surgery.

## Testing Strategy

- **Power devig:** Unit test comparing naive vs power method outputs on known odds pairs. Verify probabilities sum to 1.0.
- **F5 Poisson:** Unit test comparing old heuristic vs Poisson at key deltas (0, 0.5, 1.0, 2.0). Verify monotonicity.
- **Best-line:** Unit test with mock API response containing 3 bookmakers with different odds. Verify best price selected per side.
- **Confidence weighting:** Unit test with mixed confidence inputs. Verify high-confidence models shift the average.
- **Calibration hook:** Unit test that `apply_calibration(0.6, "moneyline") == 0.6` (identity).
- **Integration:** Run full `analyze_all_edges()` with known inputs and verify outputs shift in expected direction.

## Non-Goals

- **Dynamic thresholds** — requires historical data, deferred
- **Multi-book arbitrage detection** — out of scope
- **Pinnacle-specific prioritization** — unreliable availability
- **Closing line value tracking** — separate initiative
- **Shin method** — power method is sufficient for two-way markets
