# Ensemble Cache, Breakeven Odds, and CLV Tracking

**Date:** 2026-04-14
**Status:** Approved
**Scope:** Three features enabling a "set and forget" scheduled pipeline

## Problem

Three gaps prevent running the daily pipeline on a tight recurring schedule without wasting LLM credits or missing critical post-bet analytics:

1. **No ensemble caching** — every scheduled run re-screens and re-simulates games whose inputs haven't changed. At ~$0.06/game screening + ~$2-6/game full ensemble, polling every 30 min during a 6h window can re-spend 10-14× on the same game state.
2. **No line-shopping ceiling on the bet card** — the card shows consensus odds and our model probability, but not the breakeven price. We can't see how aggressively we can chase a move before losing edge.
3. **No closing-line-value capture** — we don't record where the consensus closed, so we can't compute CLV, the gold-standard long-run signal of whether we're beating the market.

## Feature 1: Ensemble + Screening Cache

### Design
Single JSON file per day at `data/ensemble_cache/<YYYY-MM-DD>.json`. Keyed by `{game_pk}:{starters_hash}`. Each entry holds both the Kimi screening verdict and the full ensemble result.

### Hash Rule
Hash inputs (SHA-256, hex, first 16 chars):
- Sorted list of 9 home batter IDs
- Sorted list of 9 away batter IDs
- Home starting pitcher ID
- Away starting pitcher ID

Any change to starters invalidates the cache. Bench swaps, odds moves, and injuries to non-starters do NOT invalidate.

### Cache Entry Shape
```json
{
  "12345:a1b2c3d4e5f6a7b8": {
    "starters_hash": "a1b2c3d4e5f6a7b8",
    "game_pk": 12345,
    "cached_at": "2026-04-14T18:30:00Z",
    "screening": { ...run_plan_b output... },
    "ensemble": { ...run_mirofish output... }
  }
}
```

`screening` always present on cache hit; `ensemble` present only if game was flagged by screening and run_mirofish succeeded.

### Pipeline Integration
- `_screen_game()` (main.py:42): compute hash, check cache. On hit → return cached screening + reuse for edge re-eval with fresh odds. On miss → run_plan_b, write cache, compute edges, return verdict.
- `_simulate_game()` (main.py:124): same pattern. On hit for `ensemble` key → reuse result, re-run `analyze_all_edges` with fresh odds, return bets. On miss → run_mirofish, write, return.

Fresh odds are always passed into `analyze_all_edges`. Probabilities stay cached; edges recompute every run.

### File Rotation
On pipeline start, delete cache files older than 30 days.

### Module
`cache/ensemble_cache.py` with:
- `compute_starters_hash(lineup_data) -> str`
- `get_cache_entry(game_pk: int, starters_hash: str, game_date: str) -> dict | None`
- `set_cache_entry(game_pk, starters_hash, game_date, kind, payload)` — kind = "screening" | "ensemble"
- `rotate_old_cache(keep_days=30)`

## Feature 2: Breakeven Odds Column

### Design
For each pick on the bet card, display American odds at which implied prob = model prob (zero edge threshold).

### Math
```python
def prob_to_american(p: float) -> int:
    if p >= 0.5:
        return -round(p / (1 - p) * 100)
    return round((1 - p) / p * 100)
```

### Display
New column in `agents/bet_card.py::format_bet_card()` and in the `/mainline-bet-card` slash command. Appended after the existing Kelly column:
```
... | Odds: +125 | Kelly: 4.12% | BE: -122
```

Format: `BE:` followed by the American odds. So users can see "can I take this bet up to -122 before edge evaporates?"

## Feature 3: Closing Line Value (CLV) Tracking

### Design
Deterministic T-10 min capture, no LLM calls. Full consensus snapshot + post-grade denormalization to `bets.csv`.

### Capture Job
New CLI command: `python main.py close-capture [--date YYYY-MM-DD]`.
- Reads today's games + probable first-pitch times
- For each game within the capture window (T-15 to T-5 before first pitch), fetches odds via existing `get_mlb_odds()` + `get_additional_odds()`
- Devigs with existing `power_devig()`
- Appends one row per (game, market, side, line) to `data/closing_lines.csv`

Designed to be run every 5 min by an external scheduler. Idempotent via (date, game_pk, market, side, line) dedup.

### Closing Lines CSV
`data/closing_lines.csv` columns:
```
date, game, game_pk, market, side, line, close_odds, close_prob_devig, captured_at
```

Markets captured: moneyline, run_line, total, team_total_home, team_total_away, first_5_ml, first_5_rl, first_5_total, first_3_ml, first_3_rl, first_3_total, first_1_rl, nrfi.

### Grade-Time Backfill
Extend `tracker.update_result()` and `agents/results_grader.py` to join each bet to its matching closing line at grade time and write back four new columns to `bets.csv`:
- `close_odds` (int) — American odds at close
- `close_prob` (float) — devigged closing probability
- `clv_cents` (int) — `bet.odds - close_odds` in American-odds cents (positive = beat the close)
- `clv_pct` (float) — `(our_decimal / close_decimal) - 1` (market-value interpretation)

### Line-Movement Matching
Match order:
1. Exact line match (same bet_type, same side, same point) → use directly
2. Line moved (totals, team totals, F5/F3/F1 totals):
   - For v1: only compute CLV when exact line is present
   - Flag non-matched bets with `close_odds = ""` (empty), not zero
3. ML/RL: side must match; RL spread must match exactly

Interpolation across moved lines is deferred to a future iteration.

### Module
`scrapers/closing_lines.py` with:
- `capture_closing_lines(game_date, now_utc)` — main entry; filters to in-window games, calls existing odds fetchers, devigs, writes rows
- `load_closing_lines(game_date) -> DataFrame`
- `find_closing_line(date, game, bet_type, side) -> dict | None`

`tracker.py` gets:
- New column additions to `COLUMNS`
- `compute_clv(bet_row, closing_line) -> dict`
- Called from `update_result()` alongside profit calculation

## Files Changed

New:
- `cache/__init__.py`, `cache/ensemble_cache.py`
- `scrapers/closing_lines.py`
- `tests/test_ensemble_cache.py`
- `tests/test_closing_lines.py`
- `tests/test_breakeven.py`
- `data/ensemble_cache/` (created on first run)
- `data/closing_lines.csv` (created on first capture)

Modified:
- `main.py` — cache integration in `_screen_game`/`_simulate_game`, new `close-capture` CLI command, rotate_old_cache at startup
- `agents/bet_card.py` — breakeven column
- `.claude/commands/mainline-bet-card.md` — breakeven column in the slash command's inline script
- `tracker.py` — new CSV columns + compute_clv
- `agents/results_grader.py` — backfill CLV at grade time

## Tests

- `test_breakeven.py` — `prob_to_american(0.5) == 100`, `prob_to_american(0.55) == -122`, `prob_to_american(0.45) == 122`, boundaries
- `test_ensemble_cache.py` — hash determinism, order-independence of batter lists, hit/miss, rotation, invalidation when a starter changes
- `test_closing_lines.py` — idempotent captures, devig correctness, CLV math on example bets, no-match returns None

## Rollout Notes

- Cache is write-safe: if the file is deleted mid-day, next run rebuilds cleanly.
- CLV backfill only runs at grade time, so bets placed before CLV capture is deployed will have empty CLV columns (acceptable — we start tracking forward).
- External scheduling (cron/launchd) of `close-capture` every 5 min is a separate ops concern and not in this spec.
