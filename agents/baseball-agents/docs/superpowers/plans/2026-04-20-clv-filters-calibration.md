# Plan: CLV pipeline + per-bet-type filters + calibration cap

**Date:** 2026-04-20
**Driver:** Season ROI of +0.2% on 14,738 bets is too thin. Analyst-agent diagnosis (2026-04-20):
- Model is systematically over-confident at `sim_prob ≥ 0.75` across nearly every bet type
- Several bet types have profitable subsets isolatable by simple filters (edge tier, side, line, odds bucket)
- CLV coverage is 0% — `data/closing_lines.csv` was never populated; capture command exists but was never scheduled

## Goal

Three independent fixes that compound:
1. **CLV pipeline** — capture closing lines going forward + backfill mainlines historically
2. **Per-bet-type filters** — exclude losing subsets so bad bets are never logged
3. **Calibration cap** — clip model probabilities at 0.75 before edge calc

## Piece 1 — CLV pipeline

### 1A. Mainline-only flag for historical capture
- Add `--mainline-only` to `scrapers.closing_lines.capture_closing_lines()` so historical backfills skip the per-event prop endpoint (saves ~99% of credits)
- Mainline markets: `h2h, spreads, totals, alternate_totals, team_totals, totals_1st_5_innings, totals_3_innings, h2h_1st_innings_yrfi_nrfi`

### 1B. Historical backfill CLI
- New CLI: `python main.py close-backfill --start YYYY-MM-DD --end YYYY-MM-DD [--mainline-only]`
- For each date in range:
  - Loop over each game's first-pitch time
  - Call `/v4/historical/sports/baseball_mlb/odds?date={ts-5m}` for the snapshot
  - Use the existing `extract_closing_rows()` to convert to CLV rows
  - Append to `data/closing_lines.csv` (deduped by existing key logic)
- Cost estimate for 23-day mainline backfill: ~700 credits (1% of 70.5k quota)

### 1C. Apply CLV to historical graded bets
- New CLI: `python main.py clv-apply [--date YYYY-MM-DD]`
- Walks every graded bet missing `close_odds`, calls `lookup_clv()`, writes back
- One-shot operation after backfill completes

### 1D. Schedule the recurring capture
- Use `/loop 5m python main.py close-capture` going forward
- The capture function self-filters to T-15..T-5 window and dedupes, so safe to run frequently

### Acceptance criteria for Piece 1
- `data/closing_lines.csv` has rows for all dates from 2026-03-27 onward (mainlines)
- Graded mainline bets in `data/bets.csv` show non-empty `close_odds` and `clv_cents`
- Loop is running and captures new closing lines for each game tonight
- **Note for future:** prop backfill (~15k credits) deferred — collect CLV for new prop bets going forward; revisit after 14 days

## Piece 2 — Per-bet-type filters

### 2A. New BET_FILTERS config
- Add to `config.py`:
```python
BET_FILTERS = {
    "batter_strikeouts":     {"min_edge": 0.10, "max_edge": 0.25},
    "batter_hits_runs_rbis": {"min_edge": 0.10},
    "batter_total_bases":    {"side_contains": ["under"]},
    "batter_rbis":           {"side_contains": ["under"]},
    "pitcher_hits_allowed":  {"line_in": [4.5]},
    "first_5_rl":            {"odds_min": -150, "odds_max": -110},
    "first_3_total":         {"line_in": [2.5]},
}
```

### 2B. Filter application in edge.py
- Add helper `_passes_bet_filter(bet) -> bool` in `edge.py`
- Call it in `analyze_all_edges()` and the prop-edge equivalent
- Failed bets are silently dropped (logged at INFO level for visibility)

### Acceptance criteria for Piece 2
- Bets that violate `BET_FILTERS` are NOT logged to `bets.csv`
- Daily-runner output shows fewer total bets logged for affected types
- Existing logged bets are unchanged (backward compat)

## Piece 3 — Calibration cap

### 3A. Implement apply_calibration()
- Replace stub in `calibrate.py`:
```python
SIM_PROB_CAP = 0.75

def apply_calibration(prob: float, bet_type: str = "") -> float:
    """Cap at SIM_PROB_CAP to mitigate model over-confidence at extremes."""
    if prob is None:
        return prob
    return min(prob, SIM_PROB_CAP)
```

### 3B. Verify wire-up
- `edge.py:5` already imports `apply_calibration`
- Confirm it's called on `sim_prob` before edge calc in all bet-type paths
- If not all paths call it, wire them

### Acceptance criteria for Piece 3
- Today's pipeline logs no bet with `sim_prob > 0.75`
- Edges shrink for previously-extreme bets (a sim_prob of 0.95 → 0.75 means the calculated edge drops accordingly)

## Execution order

1. **First:** Piece 3 (calibration cap — 5 min, single function)
2. **Then:** Piece 2 (filters — wires into existing edge logic)
3. **Then:** Piece 1A + 1B (mainline backfill — independent, cheap to test)
4. **Then:** Piece 1C (apply backfilled CLV to graded bets)
5. **Last:** Piece 1D (start the recurring loop)

## Out of scope
- Isotonic calibration (defer until 2 weeks of CLV data)
- Prop CLV backfill (~15k credits — wait & gather CLV going forward)
- Model retraining
