# Reverse Line Movement (RLM) Detection — Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Source idea:** `docs/improvement-ideas.md` §4 (Top 3 priority)

## Overview

Detect **reverse line movement** — the line moves *against* the side the public is betting — as a sharp-money signal. Surface RLM tags in the pre-game briefing and (optionally) modulate ensemble confidence or Kelly sizing on plays whose side is the sharp side.

## Motivation

When 70% of tickets are on Team A but the line *moves toward* Team B, that's a tell that sharp/respected money is on Team B, even though the public volume is on A. Over a season, aligning with RLM has been shown (in public studies) to produce marginal edge on sides and totals. We already poll The Odds API; capturing a second snapshot costs one additional API call per event per day.

## Scope

**In scope:**
- Two-snapshot line capture per event (opening at T-3h, latest at T-15m).
- Per-market (ML / RL / total) line-movement computation in American-odds cents.
- RLM flag when `|move| ≥ RLM_MIN_CENTS` AND move direction disagrees with public-ticket % (when available) OR disagrees with implied-volume proxy (fallback).
- Briefing section listing RLM plays for the day.
- Optional confidence boost/penalty in `ensemble/consensus.py` gated behind `RLM_WEIGHT_ENABLED`.

**Out of scope:**
- Steam-move detection across multiple books (separate, larger feature).
- Live in-game line tracking.
- Automated Kelly sizing changes based on RLM (only tagging + display in v1).

## Data Sources

- **The Odds API** — already integrated. We'll add a dedicated "opening snapshot" scheduled call at ~T-3h, separate from the main briefing fetch at T-90m. The closing fetch at T-15m already exists (`scrapers/closing_lines.py`); we'll reuse that path for the "current" leg of the move.
- **Public ticket % (optional)** — deferred to Spec-level note: if `scrapers/public_betting.py` ships (Contextual Enrichment Phase 2), its signal becomes the primary direction check; otherwise the implied-prob delta is the sole RLM basis.

## Architecture

```
scrapers/line_movement.py       ← new module
  ├─ capture_opening_snapshot(game_date)   # T-3h cron
  ├─ compute_movements(game_date)          # diff vs. closing_lines.csv
  └─ classify_rlm(movement, public_pct)    # returns RlmFlag

data/line_movement.csv           ← new storage
  cols: date, game, market, side, opening_odds, opening_prob,
        current_odds, current_prob, move_cents, public_pct,
        rlm_flag, rlm_strength

briefing.py                      ← add "Line Movement" section
edge.py / ensemble/consensus.py  ← optional confidence bump
config.py                        ← RLM_* flags + thresholds
```

### Data-flow per day

1. **T-3h** (cron/manual): `scrapers.line_movement.capture_opening_snapshot(today)` → appends to `line_movement.csv` with `current_*` fields blank.
2. **T-15m** (existing `close-capture`): closing-lines path is extended to populate `current_odds`/`current_prob` on the open rows.
3. **Briefing build time**: `briefing.py` reads the CSV, computes move, flags RLM, writes a "Line Movement" section per game.
4. **Edge evaluation** (optional v1.1): in `edge.py`, if `RLM_WEIGHT_ENABLED` and the pick side matches the RLM-favored side, multiply confidence by `RLM_CONFIDENCE_BOOST` (default 1.05); if the pick side matches the public/non-RLM side, multiply by `RLM_CONFIDENCE_PENALTY` (default 0.95).

## Core Algorithm — `classify_rlm`

```python
def classify_rlm(move_cents: float, public_pct: float | None,
                 side: Literal["home", "away", "over", "under"],
                 min_cents: float = 10.0) -> RlmFlag:
    """
    move_cents  positive = line moved toward `side`
                negative = line moved away from `side`
    public_pct  fraction of public tickets on `side` (None if unavailable)
    Returns: "RLM" (sharp), "WITH_PUBLIC", "NEUTRAL", or "UNKNOWN".
    """
    if abs(move_cents) < min_cents:
        return "NEUTRAL"
    moved_toward_side = move_cents > 0
    if public_pct is None:
        # Fallback: large move itself is the signal. Direction tagged only.
        return "SHARP_MOVE" if moved_toward_side else "SHARP_MOVE_OPP"
    public_heavy = public_pct >= 0.60
    if moved_toward_side and public_heavy:
        return "WITH_PUBLIC"
    if moved_toward_side and not public_heavy:
        return "RLM"  # line moved toward the side the public is NOT on
    return "NEUTRAL"
```

## Config keys

| Key | Default | Purpose |
|---|---|---|
| `RLM_ENABLED` | `True` | Master switch for line-movement capture + briefing section |
| `RLM_MIN_CENTS` | `10.0` | Minimum line move to consider (cents of implied prob) |
| `RLM_PUBLIC_THRESHOLD` | `0.60` | Ticket % threshold for "public heavy" |
| `RLM_WEIGHT_ENABLED` | `False` | Feature-flag the confidence boost path (off in v1, on in v1.1) |
| `RLM_CONFIDENCE_BOOST` | `1.05` | Multiplier when aligned with RLM side |
| `RLM_CONFIDENCE_PENALTY` | `0.95` | Multiplier when on opposite side |

## Testing strategy

- `tests/test_line_movement.py` — classify_rlm direction matrix (toward/away × public/no-public × ≥/<min_cents), CSV roundtrip, idempotent opening-snapshot writes, missing-market tolerance.
- `tests/test_briefing.py` — RLM section rendered when movements exist; section skipped when all `NEUTRAL`.

## Risks / open questions

- **Opening-snapshot timing**: 3 hours before first pitch may miss overnight sharp action. Consider making the opening capture configurable to T-5h or T-12h.
- **Public % source**: without a real source, RLM becomes "sharp move" which is weaker signal. Treat `RLM_WEIGHT_ENABLED` as dependent on public % being available.
- **Odds-API quota**: adding a 3rd daily call per event roughly doubles quota use on days with 15+ games. Monitor usage; fall back to single fetch if over 80% of daily budget.

## Rollout

1. Ship scraper + CSV + briefing section behind `RLM_ENABLED=True`, confidence path off (`RLM_WEIGHT_ENABLED=False`).
2. Shadow-observe 2 weeks: does RLM-flagged alignment correlate with CLV or W%?
3. If yes, flip `RLM_WEIGHT_ENABLED=True` and measure EV lift over another 2 weeks.
