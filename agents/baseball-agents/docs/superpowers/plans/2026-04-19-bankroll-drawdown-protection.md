# Bankroll Drawdown Protection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gate the betting layer with a trailing-window drawdown circuit breaker — soft brake (Kelly × 0.5) and hard halt (no new bets) — so a cold stretch doesn't compound via full-Kelly sizing.

**Architecture:** New `agents/drawdown_guard.py` computes trailing 7/14-day P&L from `bets.csv` in flat-1u units and emits a `DrawdownStatus`. `edge.py` multiplies every Kelly output by `kelly_factor(status)`; on `HARD_HALT` the bet is dropped to `skipped_signals.csv`. Status persists to `data/drawdown_status.json`. On state transitions, a short message is posted to the existing picks Discord channel.

**Tech Stack:** Python 3.11+, `pandas`, `pytest`, reuses `notify.format.unit_profit_and_risk` and `notify.discord.send_discord`.

**Spec:** `docs/superpowers/specs/2026-04-19-bankroll-drawdown-protection-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `agents/drawdown_guard.py` | Create | `evaluate_drawdown`, `kelly_factor`, `kelly_factor_cached`, `persist_status`, `load_status`, state machine + hysteresis. |
| `data/drawdown_status.json` | Create (generated) | Overwritten each pipeline run. |
| `edge.py` | Modify | One insertion near Kelly clamp: multiply by `kelly_factor_cached()`; drop + log-skipped if hard-halted. |
| `briefing.py` | Modify | Render a warning banner when state ≠ `GREEN`. |
| `notify/drawdown_alerts.py` | Create | Post transition messages to the picks Discord webhook. |
| `config.py` | Modify | Add `DRAWDOWN_GUARD_ENABLED`, the four threshold keys, and the two Kelly-factor keys. |
| `main.py` | Modify | New `drawdown-guard` subcommand (`show` / `reset`) for ops use. |
| `tests/test_drawdown_guard.py` | Create | State transitions, hysteresis, kelly_factor, P&L correctness. |
| `tests/test_edge.py` | Modify | Flag-off regression + hard-halt path. |

---

## Tasks

### Step 1 — Config + scaffolding
- [ ] Add the 7 `DRAWDOWN_*` / `SOFT_BRAKE_*` / `HARD_HALT_*` keys to `config.py` with the defaults from the spec.
- [ ] Create `agents/drawdown_guard.py` skeleton with `DrawdownStatus` dataclass and stubbed functions.

### Step 2 — P&L evaluation
- [ ] Implement `evaluate_drawdown(as_of_date)` using `notify.format.unit_profit_and_risk` + the alerts-config `bet_types` filter.
- [ ] Compute trailing 7d and 14d units.
- [ ] Classify into `GREEN` / `SOFT_BRAKE` / `HARD_HALT` with hysteresis (track prev state from `drawdown_status.json`; require one day strictly above the relevant threshold to downgrade).

### Step 3 — Persistence + Kelly factor helper
- [ ] `persist_status(status)` → atomic write to `data/drawdown_status.json`.
- [ ] `load_status()` → dict, None if missing.
- [ ] `kelly_factor(status)` → float from config (`1.0` / `SOFT_BRAKE_KELLY_FACTOR` / `HARD_HALT_KELLY_FACTOR`).
- [ ] `kelly_factor_cached()` — module-level memoized variant that reads `drawdown_status.json` once per process.

### Step 4 — Edge hook + skipped-log
- [ ] Locate the single Kelly emission point in `edge.py`; wrap with `kelly *= kelly_factor_cached()`.
- [ ] On hard halt, drop the bet and write to `skipped_signals.csv` with `reason="drawdown_hard_halt"` (reusing the sink scaffolded by the calibration-clv-loop plan if landed; otherwise write a tiny inline logger until it is).

### Step 5 — Briefing banner
- [ ] In `briefing.py`, load status; render `⚠️ Drawdown: SOFT_BRAKE (7d: -8.4u, 14d: -11.9u) — Kelly × 0.5` when not `GREEN`.

### Step 6 — Discord transition alerts
- [ ] `notify/drawdown_alerts.py`: compare current vs. previous persisted state; if changed, post a single compact message to the picks webhook.
- [ ] Hook called once at the end of `main.py daily`, after `evaluate_drawdown` runs.

### Step 7 — Ops CLI
- [ ] `python main.py drawdown-guard show` — print current status.
- [ ] `python main.py drawdown-guard reset` — overwrite status to `GREEN` (documented manual-override escape hatch when user re-calibrates).

### Step 8 — Tests
- [ ] `tests/test_drawdown_guard.py`:
  - [ ] Boundary: `trailing_7d = -SOFT_BRAKE_7D_UNITS − 0.01` → `SOFT_BRAKE`.
  - [ ] Boundary: `trailing_7d = -HARD_HALT_7D_UNITS − 0.01` → `HARD_HALT`.
  - [ ] Hysteresis: previous `SOFT_BRAKE`, today flat → remains `SOFT_BRAKE`; winning day above threshold → `GREEN`.
  - [ ] `kelly_factor` returns 1.0 / 0.5 / 0.0 for the three states.
  - [ ] P&L ignores rows outside the config `bet_types` filter.
- [ ] `tests/test_edge.py`:
  - [ ] `DRAWDOWN_GUARD_ENABLED=False` → no change to Kelly.
  - [ ] With flag on + `HARD_HALT` → bet dropped and row appears in `skipped_signals.csv`.

### Step 9 — Rollout
- [ ] Ship with `DRAWDOWN_GUARD_ENABLED=False` for 2 weeks; observe `drawdown_status.json` for plausibility.
- [ ] Tune thresholds against observed weekly variance.
- [ ] Flip flag on; monitor Discord transition alerts for chattiness.
