# CLV Analysis: Deferred Items

**Date:** 2026-04-20
**Context:** Four CLV-aware analyst agents ran on 14,437 graded bets with 99.1% CLV coverage. Filter changes were shipped the same day (see `config.BET_FILTERS`). The items below are higher-investment follow-ups that were intentionally deferred.

## What shipped 2026-04-20

Cut to production:
- `batter_strikeouts` — disabled. Model broken for this type (CLV -0.03%, 8.5% positive CLV, ROI -0.96%)
- `first_5_rl` — disabled. Negative CLV, ROI -9.58%
- `first_3_ml` / `first_3_rl` / `first_3_total` — disabled per user direction

Filter adjustments:
- `batter_rbis`, `batter_total_bases` — removed side_contains (tracking both over/under now)
- `pitcher_hits_allowed` — line_in expanded from `[4.5]` to `[3.5, 4.5, 5.5]`
- `batter_hits` — added max_edge=0.25 cap (model overconfident in 25%+ tier)

Not shipped:
- `team_total_*` filter — edge-bucket CLV pattern is a barbell (+ at 5-7% and 25%+, − in middle); no clean threshold. Keep tracking both types unfiltered.

## Deferred — needs dedicated work

### D1. `pitcher_outs` calibration gap (31pp)

**Finding:** Model predicts mean edge 34.7%, realizes +3.58% CLV. Biggest predicted-vs-realized gap of any bet type. The type is still profitable, but the model's probability estimates are systematically inflated.

**Why:** The pitcher workload model (innings/outs distribution) over-estimates tail probability. Our 0.75 calibration cap already helps but doesn't fully correct the issue.

**Options:**
1. Tighter per-type cap: `apply_calibration(prob, "pitcher_outs")` returns `min(prob, 0.65)` — aggressive but type-aware
2. Rebuild the pitcher_outs MC distribution using empirical bullpen hook data
3. Accept the gap — +3.58% CLV is still profitable

**Cost:** Option 1 is ~30 min. Option 2 is a design effort (days). Option 3 is free.

**Recommendation:** Start with Option 1; revisit after 2 more weeks of CLV data.

### D2. Player blacklist for `batter_runs_scored`

**Finding:** Overall bet type shows +6.18% CLV (+0.81% ROI) — genuine edge. But the top hitters are systematic losers in this market:

| Player | n | Mean CLV ¢ | Win % |
|---|---:|---:|---:|
| Nick Kurtz | 11 | -180.1 | 64% |
| Jakob Marsee | 10 | -80.2 | 60% |
| Mike Trout | 11 | -76.4 | 45% |
| Cal Raleigh | 11 | -68.9 | 64% |
| Byron Buxton | 11 | -65.9 | 45% |
| Bobby Witt Jr. | 13 | -65.6 | 54% |
| Kyle Tucker | 12 | -65.5 | 42% |
| Aaron Judge | 13 | -44.4 | 69% |
| Ronald Acuna Jr. | 13 | -43.0 | 69% |
| Kyle Schwarber | 16 | -34.2 | 69% |

**Why:** Sim model over-weights star hitters' run-scoring probability. Market agrees they'll probably score, but prices it tighter than our model assumes.

**Implementation:** Extend `BET_FILTERS` with an optional `player_blacklist` key. Requires:
- Parse player_name out of `side` in `_passes_bet_filter`
- Maintain a list (or a CSV of names) — names can change spelling, need fuzzy matching
- Re-analyze monthly as players' CLV patterns shift

**Cost:** ~2 hours. New data model + fuzzy name handling + plan for ongoing maintenance.

**Recommendation:** Not this week. Revisit after the Wk-of-2026-04-27 CLV re-run to confirm the pattern persists.

### D3. Model-favored `batter_hits` players

**Finding:** Consistent +20-60¢ CLV on specific players with 11-12 bets each:

| Player | Mean CLV ¢ | Win % |
|---|---:|---:|
| Matt Wallner | +61.5 | 91% |
| Miguel Vargas | +45.6 | 73% |
| Wilyer Abreu | +42.5 | 73% |
| Vladimir Guerrero Jr. | +35.5 | 73% |
| Jakob Marsee | +34.4 | 91% |
| Shea Langeliers | +31.4 | 82% |
| Jacob Wilson | +24.1 | 82% |
| Salvador Perez | +23.8 | 92% |
| Francisco Lindor | +22.9 | 83% |
| Alec Bohm | +21.9 | 92% |

**Options:**
1. Upward-sized Kelly on these players (risky — still ≤12 bets each, needs validation)
2. Nothing structural — just note the pattern and let organic bet generation continue

**Recommendation:** Option 2. Sample sizes too small to confidently overweight.

### D4. Process: Weekly CLV re-review

**Gap:** The four-agent analysis ran once. Filter decisions made 2026-04-20 should be re-validated weekly as new CLV data accumulates.

**Proposed cadence:** Every Sunday evening, run:
1. `python3 main.py clv-apply` (catches any missing CLV from graded week)
2. Re-dispatch the 4 analyst agents (same prompts, fresh data)
3. Review output; update `BET_FILTERS` if any recommendations materially change

**Cost:** ~15-30 min each week.

**Recommendation:** Schedule via cron or set up as a `/loop 1w` dynamic task. Punt this to next session.

## Revisit triggers

Re-run the CLV-aware analysis if any of these hit:
- +500 new graded bets (~1.5 weeks at current cadence)
- Weekly ROI trend moves ≥ 3pp in either direction
- Any new bet type added to the pipeline
