# Bankroll Drawdown Protection — Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Source idea:** `docs/improvement-ideas.md` §5

## Overview

Add a **cumulative-drawdown circuit breaker** to the betting layer: when the trailing 7- or 14-day units-P&L drops past configured thresholds, globally scale Kelly sizing (soft brake) or halt new-bet logging (hard brake) until the window recovers. Complements — does not duplicate — the per-game correlation cap in the betting-layer-hardening spec.

## Motivation

Kelly sizing assumes the probability input is well-calibrated; when the model is temporarily miscalibrated (cold streak driven by model drift, not variance alone), full Kelly compounds the damage. A simple trailing-window drawdown gate preserves bankroll during the period it takes to detect and fix the upstream issue.

## Scope

**In scope:**
- Pre-bet hook that reads graded P&L (units, flat-1u convention) for the trailing 7 and 14 days.
- Two-tier gate: soft brake (Kelly × `SOFT_BRAKE_FACTOR`) and hard halt (no new logged bets).
- Gate status written to `data/drawdown_status.json` each pipeline run; briefing header shows status when engaged.
- Discord alert to the picks channel when the gate state changes (green → yellow → red and reverse).

**Out of scope:**
- Per-bet-type drawdown (future — would need a bet-type-P&L view).
- Auto-pausing grading or scraping (only affects bet logging / Kelly scaling).
- Bankroll *topping up* logic — stays manual.

## Architecture

```
agents/drawdown_guard.py          ← new
  ├─ evaluate_drawdown(as_of_date) → DrawdownStatus
  ├─ kelly_factor(status) → float in [0, 1]
  └─ persist_status(status) / load_status()

data/drawdown_status.json         ← new (tiny, overwritten each run)
  {"as_of":"2026-04-19","trailing_7d":-8.5,"trailing_14d":-12.0,
   "state":"SOFT_BRAKE","kelly_factor":0.5}

edge.py                           ← modify
  # Multiply every Kelly output by kelly_factor(status)
  # If state == HARD_HALT, drop the bet and write to skipped_signals.csv
  # (reusing the calibration-clv-loop sink if it's landed)

briefing.py                       ← modify
  # Render a banner when state != GREEN

notify/                           ← modify
  # On state transition, post a short alert to the picks channel
```

### State machine

```
GREEN          trailing_7d >= -SOFT_BRAKE_7D and trailing_14d >= -SOFT_BRAKE_14D
SOFT_BRAKE     trailing_7d < -SOFT_BRAKE_7D or trailing_14d < -SOFT_BRAKE_14D
HARD_HALT      trailing_7d < -HARD_HALT_7D  or trailing_14d < -HARD_HALT_14D

Hysteresis: require 1 winning day strictly above threshold to downgrade back.
```

## P&L computation

Reuse `notify.format.unit_profit_and_risk` (flat 1u stake). Only graded rows (`result ∈ {W, L, P}`) with `bet_type ∈ cfg.bet_types` count — analyst-team totals and props don't gate the mainline bankroll.

```python
def evaluate_drawdown(as_of_date: str) -> DrawdownStatus:
    df = load_bets()
    cutoff_14 = (dt.fromisoformat(as_of_date) - td(days=14)).date().isoformat()
    cutoff_7  = (dt.fromisoformat(as_of_date) - td(days=7)).date().isoformat()
    mainline = load_alerts_config()["bet_types"]
    g = df[df["bet_type"].isin(mainline) & df["result"].isin(["W","L","P"])]
    p7  = _units_since(g, cutoff_7)
    p14 = _units_since(g, cutoff_14)
    state = _classify(p7, p14)
    return DrawdownStatus(as_of_date, p7, p14, state)
```

## Config keys

| Key | Default | Notes |
|---|---|---|
| `DRAWDOWN_GUARD_ENABLED` | `True` | Master switch |
| `SOFT_BRAKE_7D_UNITS` | `-8.0` | Triggers soft brake if trailing 7d ≤ this |
| `SOFT_BRAKE_14D_UNITS` | `-12.0` | Triggers soft brake if trailing 14d ≤ this |
| `HARD_HALT_7D_UNITS` | `-15.0` | Triggers hard halt |
| `HARD_HALT_14D_UNITS` | `-25.0` | Triggers hard halt |
| `SOFT_BRAKE_KELLY_FACTOR` | `0.5` | Multiply Kelly by this in soft-brake state |
| `HARD_HALT_KELLY_FACTOR` | `0.0` | 0 = don't bet at all |

Default thresholds assume ~10–15 mainline bets/day and ~300u-size bankroll; document that these should be re-tuned to the user's bankroll.

## Edge.py hook point

Single insertion near the end of `_sized_kelly` (or the single Kelly-clamping line in the unified edge function — whichever exists when this lands):

```python
factor = drawdown_guard.kelly_factor_cached()
kelly = raw_kelly * factor
if factor == 0.0:
    _log_skipped(row, reason="drawdown_hard_halt")
    continue
```

## Discord alerting

On state transition only (not every run). Piggyback on the existing picks Discord channel since the operator already watches it for daily cards:

```
⚠️ Drawdown guard: GREEN → SOFT_BRAKE (7d: -8.4u, 14d: -11.9u)
        Kelly sized at 50% until recovery.
```

Keep messages short; no new channel.

## Testing strategy

- `tests/test_drawdown_guard.py`:
  - State transitions across threshold boundaries.
  - Hysteresis: still `SOFT_BRAKE` after exactly 1 flat day; drops to `GREEN` after 1 winning day above threshold.
  - `kelly_factor` returns correct multiplier per state.
  - P&L computation uses flat-1u, ignores ungraded + out-of-window rows.
- `tests/test_edge.py` regression: with `DRAWDOWN_GUARD_ENABLED=False`, no Kelly change; with True and `HARD_HALT`, bet dropped to skipped.

## Risks / open questions

- **Sample size**: with ~10 bets/day, 7-day drawdown is noisy. `HARD_HALT_7D_UNITS=-15u` at ROI neutral is only ~2σ, so false halts will happen. Pair with the calibration/CLV loop so we can tell "bad variance" from "bad model."
- **Interaction with calibration rebuild**: when calibration is re-fit mid-slump, yesterday's bad picks don't get re-graded — the drawdown window reflects stale model sizing. Document that `calibrate --rebuild` should be paired with a manual `drawdown-guard --reset` if the operator believes the slump was model drift now fixed.
- **Units vs. dollars**: the gate is unit-denominated. If the user ever moves to $ tracking, thresholds need re-expression.

## Rollout

1. Ship with defaults + state written to JSON; no Kelly scaling effect at first (`DRAWDOWN_GUARD_ENABLED=False`).
2. Observe status file for 2 weeks; tune thresholds to actual weekly variance.
3. Flip flag on.
4. After 4 weeks, review Discord transition alerts — too chatty? Tighten hysteresis.
