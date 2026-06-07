# Plan: Monte Carlo run model recalibration (totals under-bias fix)

**Date:** 2026-04-21
**Trigger:** Operator observation that `total` bets are ~100% UNDERs in the last 10+ days. Analysis confirms systemic under-bias.

## Evidence

From `data/bets.csv` as of 2026-04-21:

| Side | n | Predicted win% (sim_prob mean) | Actual win% | Profit |
|---|---:|---:|---:|---:|
| Over | 11 | 57.1% | 63.6% | +3.71u |
| Under | 107 | 60.4% | 49.5% | -1.21u |

Key observations:
- 91% of `total` bets logged are UNDERs; last 10 consecutive game-days logged 100% UNDERs.
- Model predicts 60.4% win rate on unders but reality delivers 49.5% — an 11-point miscalibration in the losing direction.
- When the model DOES flag an over (rare, 11 bets), it hits 63.6% — the model has skill on overs, we're just not seeing them.
- Net: the MC run-scoring engine systematically produces fewer runs than games actually produce, so every game's edge calculation favors the UNDER side.

## Temporary guard (shipped 2026-04-21 — morning)

`BET_FILTERS["total"] = {"min_edge": 0.10}` — raises the threshold from the global `EDGE_THRESHOLDS["total"] = 0.05` default. Cuts the low-conviction under bets that dominate the volume; keeps only the strongest signals on either side until the real fix ships. Expected: ~60-80% reduction in `total` bet count.

## Phase 2 fix (shipped 2026-04-21 — afternoon)

Shipped simultaneously (same-day follow-up to the temporary guard):

### A. Park-factor recalibration (`config.PARK_FACTORS`)

Based on audit against public Baseball Savant / consensus park factors. The previous values systematically understated pitcher parks (SF 0.85, MIA/OAK/SEA/SD all 0.90 — all below public consensus of ~0.92-0.96) and overstated hitter parks (CIN 1.15, PHI 1.10). Corrections:

| Team | Old runs | New runs | Old hr | New hr |
|---|---:|---:|---:|---:|
| SF | 0.85 | **0.93** | 0.80 | **0.88** |
| SD | 0.90 | **0.95** | 0.90 | **0.93** |
| SEA | 0.90 | **0.95** | 0.90 | **0.92** |
| MIA | 0.90 | **0.95** | 0.85 | 0.90 |
| OAK | 0.90 | **0.95** | 0.85 | 0.90 |
| LAD | 0.95 | **0.98** | 0.95 | 0.97 |
| LAA | 0.95 | **0.97** | — | — |
| CIN | 1.15 | **1.08** | 1.25 | **1.18** |
| PHI | 1.10 | **1.06** | 1.15 | 1.10 |
| NYY | 1.05 | **1.03** | 1.15 | **1.12** |
| COL | 1.35 | **1.30** | 1.30 | 1.25 |
| BOS | 1.10 | **1.08** | — | — |
| plus minor adjustments to CLE, DET, PIT, NYM, STL, TB, TEX, TOR, KC | | | | |

Park factors enter the system through two paths:
1. `briefing.py:92` — appears in the LLM prompt context.
2. `simulation/monte_carlo.py:19` — scales the MC run-scoring engine (used for props).

Both paths are attacked by the same `PARK_FACTORS` update.

### B. Post-LLM bias correction (`config.TOTAL_UNDER_BIAS_CORRECTION`)

A new `TOTAL_UNDER_BIAS_CORRECTION = 0.06` constant, applied in `edge.check_total_edge` before calibration cap and edge detection. Shifts 6pp of probability mass from UNDER to OVER. Set conservatively at half the observed miscalibration (0.11) so the park-factor fix can carry most of the work; this correction picks up any residual bias.

The correction only applies to `total` bets. First-N totals (`first_3_total`, `first_5_total`) are currently disabled or use their own threshold — revisit if they show similar bias.

## Phase 2b — Extend to team_total_home (shipped 2026-04-22)

Follow-up after diagnosis of NRFI and team_totals revealed a **separate, opposite-direction** bias on `team_total_home`:

**Observed on 324 settled team_total bets:**
- `team_total_home`: 97 over / 50 under (66% OVER bias) — over wins 48.5% / -4.29u / mean sim_prob on over 0.723
- `team_total_away`: balanced (83 over / 94 under), both sides profitable
- `nrfi`: 141 NRFI / 3 YRFI (98% NRFI), mild 3.6pp bias (predicted 60.3% actual 56.7%)

Shipped: `TEAM_TOTAL_HOME_OVER_BIAS_CORRECTION = 0.06` in `config.py`, applied in `edge.check_team_total_edge` **only for side='home'** before calibration cap. Shifts probability OVER → UNDER (opposite direction from totals; matching observed bias).

Not shipped (observe first):
- `team_total_away` — balanced; don't break what works
- `nrfi` — 3.6pp bias is mild; park-factor fix (shipped with `be849f3`) should organically lower NRFI volume by raising expected 1st-inning runs. Re-check after 7 days.

Root cause hypothesis for team_total_home over-bias: LLM/ensemble likely has a "home team offensive framing" in the prompt that doesn't apply to away teams. Worth investigating in briefing.py during the 7-day window.

## Phase 3 — Validate (still 7 days of live data)

Observation window starts with the first post-fix pipeline run. Re-query the over/under split after 7+ days of new `total` bets. Acceptance criteria (unchanged from original plan):

- Over/under split on `total` bets: between 40/60 and 60/40 (vs current 9/91).
- Under-side win rate: ≥ 50% (vs current 49.5%).
- Under-side mean CLV: ≥ 0.
- Remove the temporary `min_edge: 0.10` filter on `total` once these hold.

If the split over-corrects (goes too heavily to OVER), reduce `TOTAL_UNDER_BIAS_CORRECTION` or revert park-factor changes for the teams where the fix overshot.

## Root cause hypotheses (in decreasing order of likelihood)

1. **Park factors calibrated too low.** `config.PARK_FACTORS["<team>"]["runs"]` multipliers. A uniform +3-5% shift upward could close the gap. Validate by comparing model vs actual runs-per-game for each park over the season.

2. **Weather defaults suppress offense.** `WEATHER_API: NO KEY SET` causes the weather adapter to return defaults. If the default assumes neutral-or-adverse conditions, totals shift down. Check `scrapers/ballpark.py`'s fallback.

3. **Batter/pitcher stats too stale.** The sim uses season-to-date aggregates, which under-weight hot streaks and lag current form. Rolling-window (last 30 PA) projections would be more responsive.

4. **MC engine tail events under-represented.** The discrete at-bat engine may produce fewer multi-run innings than reality. Validate by comparing simulated inning-scoring distributions to Retrosheet play-by-play.

5. **Game-environment enrichment missing signals.** Lineup L/R handedness vs pitcher, catcher framing, umpire strike-zone bias — all small factors we may not model. Each is a few percent; in aggregate they could account for the gap.

## Investigation plan

### Phase 1 — Diagnose (2-4 hours)

For each graded game over the past 30 days:
- Compute: `model_expected_runs`, `actual_runs_scored`, `residual = actual - model`
- Group residuals by: park, weather (if available), starting-pitcher hand vs lineup hand
- Plot the residual distribution: is it centered at 0? Or biased upward (the hypothesis)?

**Deliverable:** `docs/superpowers/plans/2026-04-21-totals-recalibration-diagnosis.md` with findings. Answers: is the bias uniform (add a constant) or concentrated in specific parks / weather / matchups (fix selectively)?

### Phase 2 — Fix candidates (1 day each, shipped one at a time)

Priority order based on Phase 1 findings:

**Option A: Uniform park-factor shift.** Apply a global `RUNS_UNDER_BIAS_FIX` constant to every `PARK_FACTORS[*]["runs"]` value. Fastest to ship, easy to test.

**Option B: Per-park park-factor recalibration.** Recompute `PARK_FACTORS` from the last 2 full seasons' runs-per-game, weighted recent-more. Takes the most-wrong parks and fixes them without touching the rest.

**Option C: Weather API key + real defaults.** Set up the weather adapter with a real API key (OpenWeather, Visual Crossing) so conditions stop being a blanket default. Validate that real weather data moves the simulator in the expected direction.

**Option D: Rolling stat windows.** Switch batter/pitcher aggregates from season-to-date to 30-PA-rolling. Biggest code change; highest potential accuracy gain.

Each option: ship, wait 7 days of new data, compare over/under split + win rates, decide whether to keep.

### Phase 3 — Validate (1 week of live data)

After shipping any Phase 2 fix, the `total` over/under split should move toward 50/50 and the under-side win rate should move up toward 52%. If neither happens, the fix wasn't the right one; revert and try the next option.

### Phase 4 — Remove the temporary guard

Once a Phase 2 fix is validated, remove the `"min_edge": 0.10` on `total` in `BET_FILTERS` — the underlying model is now producing balanced output and the guard is no longer needed.

## Acceptance criteria

Recalibration is done when ALL of these hold over a 14-day rolling window:
- Over/under split on `total` bets: between 40/60 and 60/40 (vs current 9/91).
- Under-side win rate: ≥ 50% (vs current 49.5% — marginal but at least calibrated).
- Under-side mean CLV: ≥ 0 (no longer losing to the close).
- Temporary `min_edge: 0.10` filter removed.

## Related work (not blocking)

- **Per-bet-type isotonic calibration** (already documented as deferred): once we have enough graded data per bet type, replace the global `SIM_PROB_CAP = 0.75` with per-type isotonic regression. This would address tangential calibration issues beyond the under-bias.
- **`team_total_*` may have the same issue.** Check after Phase 1 — team totals are a sibling of game totals and share the same MC engine.
