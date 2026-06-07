# Reverse Line Movement (RLM) Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture two line snapshots per event (opening + closing-ish), detect reverse line movement, surface it in the briefing, and feature-flag a confidence multiplier in edge evaluation.

**Architecture:** New `scrapers/line_movement.py` wraps a cron-triggered opening snapshot and extends the existing `scrapers/closing_lines.py` flow to populate the "current" leg. A new `data/line_movement.csv` stores per-event movements. `briefing.py` adds a "Line Movement" section. `edge.py` gains an opt-in RLM-aware confidence multiplier behind `RLM_WEIGHT_ENABLED`.

**Tech Stack:** Python 3.11+, `requests`, `pandas`, existing `filelock` pattern, pytest.

**Spec:** `docs/superpowers/specs/2026-04-19-reverse-line-movement-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scrapers/line_movement.py` | Create | `capture_opening_snapshot`, `compute_movements`, `classify_rlm`, CSV I/O helpers. |
| `scrapers/closing_lines.py` | Modify | On closing capture, join opening snapshot and fill `current_*` cols in `line_movement.csv`. |
| `data/line_movement.csv` | Create (generated) | Per-event opening/current snapshot + derived fields. |
| `briefing.py` | Modify | Add "Line Movement" section per game; skip when all rows `NEUTRAL`. |
| `edge.py` | Modify | Optional multiplier on `confidence` when `RLM_WEIGHT_ENABLED`. |
| `ensemble/consensus.py` | Modify | Accept optional per-slot `rlm_factor` into `weighted_average_prob`. |
| `config.py` | Modify | Add `RLM_ENABLED`, `RLM_MIN_CENTS`, `RLM_PUBLIC_THRESHOLD`, `RLM_WEIGHT_ENABLED`, `RLM_CONFIDENCE_BOOST`, `RLM_CONFIDENCE_PENALTY`. |
| `main.py` | Modify | Add `capture-openings` CLI subcommand; hook opening-snapshot into `daily` if within window. |
| `tests/test_line_movement.py` | Create | `classify_rlm` matrix + CSV roundtrip + missing-market tolerance. |
| `tests/test_briefing.py` | Modify | Assert RLM section renders / skips correctly. |
| `tests/test_edge.py` | Modify | Feature-flagged multiplier path. |

---

## Tasks

### Step 1 — Config + storage scaffolding
- [ ] Add `RLM_*` config keys with the defaults from the spec.
- [ ] Create `data/line_movement.csv` column set: `date, game, market, side, opening_odds, opening_prob, current_odds, current_prob, move_cents, public_pct, rlm_flag, rlm_strength`.
- [ ] Write `scrapers/line_movement.py` skeleton with empty public functions + column constants + file lock.

### Step 2 — Opening snapshot capture
- [ ] Implement `capture_opening_snapshot(game_date)` — fetch odds for all of today's games, write a row per (game, market, side) with `opening_*` populated and `current_*` blank. Idempotent on re-run (dedupe by `(date, game, market, side)`).
- [ ] Wire `main.py capture-openings --date YYYY-MM-DD` CLI.
- [ ] Auto-trigger in `main.py daily` iff it's more than 2h before first pitch; otherwise warn + skip.

### Step 3 — Closing-side join
- [ ] In `scrapers/closing_lines.py`, after normal closing capture, call `line_movement.attach_current_snapshot(game_date)` which finds rows with empty `current_*` and fills from the closing payload.
- [ ] Compute `move_cents` as `(current_prob − opening_prob) × 100` (signed toward `side`).
- [ ] Leave `public_pct` blank (populated later if public-betting scraper lands).

### Step 4 — RLM classification
- [ ] Implement `classify_rlm(move_cents, public_pct, side, min_cents)` per the spec.
- [ ] Populate `rlm_flag` and `rlm_strength` (= `abs(move_cents)`) on each row.

### Step 5 — Briefing surface
- [ ] Extend `briefing.py` with a `format_line_movement_section(game_key)` helper.
- [ ] Render only games that have at least one `RLM` or `SHARP_MOVE` row; group by market; show move in cents + public % when present.
- [ ] Update the briefing's "Prediction Task" list to include an item referencing line movement when a game has an RLM tag.

### Step 6 — Optional confidence multiplier (feature-flagged)
- [ ] Extend `ensemble/consensus.weighted_average_prob` to accept `rlm_factor: float | None`.
- [ ] In `edge.py`, when `config.RLM_WEIGHT_ENABLED`, look up the slot's RLM row; pass `RLM_CONFIDENCE_BOOST` (aligned) or `RLM_CONFIDENCE_PENALTY` (opposed) as `rlm_factor`.
- [ ] Default is off — no behavior change when flag is False.

### Step 7 — Tests
- [ ] `tests/test_line_movement.py`:
  - [ ] `classify_rlm` returns correct label across the direction × public × threshold matrix.
  - [ ] `capture_opening_snapshot` + `attach_current_snapshot` is idempotent and order-independent.
  - [ ] Missing market row is tolerated (no exception).
- [ ] `tests/test_briefing.py`:
  - [ ] RLM section present when a row is flagged.
  - [ ] Section absent when every row is `NEUTRAL`.
- [ ] `tests/test_edge.py`:
  - [ ] With `RLM_WEIGHT_ENABLED=False`, confidence unchanged.
  - [ ] With `RLM_WEIGHT_ENABLED=True` and aligned side, confidence scaled by boost.

### Step 8 — Rollout + verification
- [ ] Shadow-capture openings + closings for 2 weeks with `RLM_WEIGHT_ENABLED=False`.
- [ ] Correlate `rlm_flag == RLM` rows with CLV outcomes in `bets.csv`; if positive t-stat, flip the weight flag.
