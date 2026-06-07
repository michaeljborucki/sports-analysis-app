# INVESTIGATE_LATER.md

Items deferred from the framework gap analysis (2026-04-20) that require a larger bet sample before they become actionable. Each has an explicit revisit trigger — do not open these until the trigger fires.

**Current state: 4 settled bets.** All triggers below are functions of sample size.

---

## 1. Per-bet-type filter tuning

**What**: Populating `BET_FILTERS` (see scaffolding work from item 2 of the active work) with concrete `min_edge`, `max_edge`, `side_contains`, `line_in`, `odds_min/max` rules derived from which bet types and segments actually earn CLV.

**Why deferred**: Tuning values requires the four-quadrant CLV-vs-ROI view the framework describes. At n=4 there is no distribution to analyze; any rule we add would be pattern-matching on noise.

**Revisit trigger**: n ≥ 30 settled bets *per bet_type* (≈ 90 total across moneyline / game_handicap / total_games). First pass should be conservative — cut only clearly -CLV segments, keep edge-case decisions for a later pass.

**Depends on**: `BET_FILTERS` scaffolding being in place so the rules have somewhere to land.

---

## 2. Isotonic regression calibration

**What**: Replacing the global hard-cap `SIM_PROB_CAP` with per-bet-type isotonic regression keyed on observed CLV / closing-line outcomes.

**Why deferred**: Isotonic regression needs enough observations per bet type to fit a non-trivial step function. With a handful of bets, the fit collapses to a near-identity mapping or overfits wildly.

**Revisit trigger**: ≈ 2 weeks of continuous CLV data (framework's own stated threshold) AND n ≥ 50 settled bets *per bet_type*, whichever is later.

**Interim**: A symmetric hard cap ships now (see active work); this replaces it when data is sufficient.

---

## 3. Analyst agents (weekly CLV / ROI re-analysis)

**What**: The four parallel analyses the framework describes — CLV-vs-ROI quadrant per bet type, edge calibration (predicted vs realized), `BET_FILTERS` validation (kept vs dropped CLV), prop concentration. These drive the weekly tuning cycle.

**Why deferred**: The four-quadrant analysis has no statistical power below tens of bets per bucket. "Keep / Scale / Cut / Variance" decisions on n<20 are coin flips dressed up as signal.

**Revisit trigger**: n ≥ 100 total settled bets AND n ≥ 20 per bet_type. Start with a single monthly run; ramp to weekly only when the dataset clearly supports it.

---

## 4. Ensemble weight updates via `self_optimizer` — ACTIVELY HARMFUL TODAY

**What**: The Brier-score-driven model-weight updates in `agents/self_optimizer.py` that feed `data/model_weights.json`, which `ensemble/orchestrator.py` reads to blend predictions.

**Why deferred — and possibly actively harmful right now**: The framework explicitly calls out the ≥ 200 settled bets per ensemble member threshold. Tennis runs 6 models × 3 runs per flagged match; at n=4, per-model Brier scores are pure noise. Any weight shift from noise-driven optimization feeds back into the next prediction and can drift the blend off-center on garbage signal.

**Immediate action recommended** (worth doing BEFORE more bets accumulate — not a later item):
- Freeze weight writes until the threshold is met. Either:
  - Disable the write step in `self_optimizer.run_optimizer()` by default (require an explicit `--force` flag), **or**
  - Add a guard: if total settled bets < 200, log the computed weights but do not persist them.
- Document current `data/model_weights.json` as "uniform baseline" and reset it if it has already drifted.

**Revisit trigger**: n ≥ 200 settled bets overall (framework's stated minimum). Then re-enable auto-write and observe weight drift for a month before trusting it to steer blends.

---

## 5. Replacement for Sackmann player-data integration (HIGH PRIORITY)

**What**: Rebuild the player-profile data source. Historical stats, Elo ratings, head-to-head records, recent form — all of this fed the LLM ensemble with concrete numbers until 2026-04-21.

**Why deferred — this is a removed capability, not a missing one**: The Sackmann GitHub data integration (`github.com/JeffSackmann/tennis_atp` and `tennis_wta`) was removed because:
1. Current-year CSVs (`atp_matches_2026.csv`, `atp_matches_2025.csv`) don't exist yet — upstream only posts them at season end or after tournaments complete.
2. Every player profile retried those 404'd files, adding ~15-20 sec per profile. Pipeline runs lost 5-8 min per call to 404 retry storms.
3. The data was also increasingly stale — weeks behind the live tour.

Current state: `scrapers/players.py` is stubbed — `get_player_profile` and `get_head_to_head` return the same shape but with `"N/A"` values. The LLM ensemble sees less signal per match (no serve stats, no recent form, no H2H record) but nothing breaks.

**Revisit trigger**: we have a data source we trust AND time to integrate. Not volume-gated.

**Options to evaluate**:
- **Build our own scraper** against live tour sites (atptour.com, wtatennis.com) — fresher data, we control latency, but fragile to site redesigns
- **Paid tennis data API** (SportRadar, Entity Sports, others) — reliable but $$/month
- **Merge a self-hosted copy of Sackmann data** updated on our own cadence, gated by retry-caching so missing years fail once per run, not 26× per run
- **Hybrid: self-hosted Sackmann for historical + live scraper for current year**

**Recommended first pass when revisiting**: the hybrid. Sackmann historicals are well-structured and stable; a thin live-tour scraper fills the current-year gap.

**Related files already stubbed** (check when restoring):
- `scrapers/players.py` — the stub
- `agents/health_check.py` — Sackmann check removed
- `config.py` — `SACKMANN_*` constants removed; `sackmann_repo` key removed from `TOUR_CONFIG`
- `docs/sackmann-self-hosted-plan.md` — prior design notes, still in repo for reference

---

## 6. Injury / player-news data source

**What**: Populate the `injuries` field in `match_data` (currently hardcoded to `"N/A"`) with real injury/illness reports, so the LLM ensemble can factor physical status into predictions.

**Why deferred — blocked, not volume-gated**: The original `scrapers/news.py:get_player_news()` was written against an API-Tennis `method=get_injuries` endpoint that **does not exist** (returns 404 on 2026-04-20 probe). Probed five other candidate method names (`get_injury`, `get_news`, `injuries`, `get_player_news`, `get_withdrawals`) — all 404. API-Tennis does not expose any injury/news feed on any tier we've tested.

**Expected value — honest calibration**:
- Best case with a clean tennis-focused feed: **0.1-0.3% overall Brier improvement**
- Realistic case with a general news feed: **net-zero to mildly negative** (LLM overweighting noise)
- Two structural reasons the upside is modest:
  1. Our event-driven trigger fires **7-9h before match**. Most injury news breaks and gets priced before we place bets. We catch only news landing inside that 9h window — rare for top players.
  2. LLM ensembles overweight stale/generic injury blurbs ("managing a minor niggle"), which can worsen predictions on matches that would otherwise have been called correctly.

**Conclusion from the 2026-04-20 decision**: this is ~5-10× lower value than the calibration cap and `BET_FILTERS` work. Do not go hunting for a feed unless the cost is near zero.

**Candidate sources if revisiting**:

| Source | Cost | Signal | Work | Verdict |
|---|---|---|---|---|
| Scrape tennisexplorer.com withdrawals | Free | Good, tennis-specific | 2-3h + ongoing breakage | Fragile |
| Scrape ATP/WTA official news | Free | Low coverage, needs NLP | High | Not worth it |
| NewsAPI / Mediastack | $50-250/mo | Noisy, lots of irrelevant tennis news | 4-6h + filter tuning | Paid AND noisy |
| **Retirement detection from `scores.py` recent form** | **Free** | **Narrow but high-signal (retired-last-match is material)** | **1-2h** | **Best cost/value** |
| LLM web search inside ensemble | $0.50-2 per flagged match | Unpredictable | 2-3h | Expensive, uncertain |
| SportRadar / paid tennis API | $500+/mo | Excellent | 3-4h | Overkill for current volume |

**Recommended first pass when revisiting**: retirement-detection heuristic. Parse `scores.py` recent-form output for `"Ret."` / `"W/O"` markers on each player's most recent match. Zero external dependency, leverages data already fetched, catches the strongest acute-injury signal we have free access to.

**Revisit trigger**: either (a) n ≥ 100 settled bets AND we have a specific hypothesis that injury-adjacent matches are underperforming (measurable from bets.csv), OR (b) a usable tennis-focused feed becomes available at low cost.

**Related cleanup**: `main.py daily` imports `get_player_news` but never calls it. `scrapers/news.py` has a docstring warning about the 404. Both can stay as-is until this item is revived; remove the dead import then.

---

## 7. Challenger calibration / logging

**What**: The Phase 3 adversarial challenger (Claude Sonnet) has been observed killing a large fraction of proposed bets across multiple matches. When it kills every surviving slot, the ensemble now abstains (returns empty predictions) instead of returning `None` — the bug where this triggered wasteful Plan B fallback was fixed 2026-04-21.

**Why deferred**: need data to tune. The challenger's kill reasoning IS logged at INFO level (`parse_challenge_response` in `ensemble/challenger.py` already logs `KILL %s: %s (flaw: %s)`), but we haven't analyzed whether Claude is killing legitimately (catching real flaws) or over-conservatively (rejecting reasonable bets).

**Revisit trigger**: after ~20-30 runs where the challenger has made kill decisions, audit the logged reasoning. If > 70% of kills are "legitimate flaws" (injuries, matchup errors, stale data), leave it alone. If kills are generic hedging ("uncertain outcome", "variance"), tighten the prompt or raise the kill threshold.

**Possible tuning levers**:
- Require a `flaw_found` field (currently optional) — kills without a concrete flaw get downgraded to approve
- Require 2/3 reasoning criteria met before kill (split the current prompt's "concrete flaw" list into explicit checks)
- Switch to majority-of-N challenger runs instead of single-call verdict

---

## 8. Player blacklists / prop concentration analysis

**What**: Per-player and per-market CLV breakdowns that would let a `player_blacklist` filter surface player-level blind spots (framework's own "open design question"). Tennis is particularly well-suited since matches are identified by two players directly, not aggregated into a team.

**Why deferred**: Per-player CLV requires per-player sample. Even at n=200 total bets, most individual players would appear 1–3 times. This needs a long tail of repeated names.

**Revisit trigger**: n ≥ 500 settled bets, or any single player appearing in ≥ 15 bets, whichever comes first.

---

## Revisit checklist (paste when a trigger fires)

When opening an item:
- [ ] Confirm the trigger condition is actually met — run a count on `bets.csv`, don't trust memory
- [ ] Sanity-check whether the trigger threshold still feels right given what the data looks like
- [ ] Re-read the relevant framework doc section — patterns may have evolved since this file was written
- [ ] Scope a first pass that is conservative and easy to roll back
- [ ] Add a follow-up note in this file if the first pass uncovers a new deferred item
