# Contextual Enrichment Phase 2 — Design Spec

**Date:** 2026-04-19
**Status:** Draft
**Source ideas:** `docs/improvement-ideas.md` §3 (BvP history), §7 (public betting %), §9 (travel/rest), §11 (day/night + home/away splits)

## Overview

Bundle four independent context sources into a single Phase-2 enrichment rollout, modeled after the pattern established by the Statcast/umpire/catcher spec: each source is a standalone scraper behind a per-source feature flag, surfaces in the briefing, and — where applicable — shifts PA-level sim rates through `simulation/pa_engine.py`.

Four sources:
1. **BvP history** (§3) — batter-vs-pitcher historical matchup from `pybaseball.statcast_batter`.
2. **Public betting %** (§7) — Action Network or similar; feeds briefing context + unlocks strong RLM classification.
3. **Travel / rest** (§9) — derived from MLB Stats API schedule.
4. **Day/night + home/away splits** (§11) — pitcher-level splits via `pybaseball`.

## Motivation

Each source is individually small-value, but collectively they close data-gap holes in the briefing. Bundling them into a single phase (vs. four separate specs) avoids four full-spec rituals for four cheap scrapers. They share the same framework plumbing — per-source flag, daily cache file, briefing section, fixture fallback — so the ROI of specing them together is high.

## Scope

**In scope (per source):**
- Fetch + cache + fixture fallback.
- A per-source toggle in `SOURCES_ENABLED`.
- Briefing section rendering.
- For BvP and day/night: a narrow, well-documented shift into `sample_pa` rates (guarded by Bayesian shrinkage against small samples).

**Out of scope:**
- Recomputing all historical bets against these sources (shadow observe only).
- Real-time public% polling (single daily snapshot is enough to use).
- Integration with the correlation-group sizing from betting-layer-hardening (orthogonal concern).

## Source-by-source design

### 1. BvP History (`scrapers/bvp_history.py`)

**Source:** `pybaseball.statcast_batter(start_dt, end_dt, player_id)` filtered to rows where `pitcher_id == starter_id`.

**Output:** lightweight dict per (batter, pitcher):
```python
{"pa": 22, "h": 7, "hr": 1, "k": 6, "bb": 2, "xwOBA": 0.345}
```

**Cache:** `data/bvp_cache.json`, 7-day TTL, keyed by `(batter_mlb_id, pitcher_mlb_id, season_year)`.

**Shrinkage:** use a Bayesian shrinkage toward league-average wOBA with `k_prior = 50 PA`. Never overwrite standard platoon rates; instead, compute a per-batter `bvp_shift` ∈ `[-0.03, +0.03]` wOBA that's additive on top of the base rate. Flag as `bvp_shift` in the `sample_pa` call and apply only when BvP has `pa >= 12`.

**Feature flag:** `SOURCES_ENABLED["bvp_history"] = True`.

### 2. Public Betting % (`scrapers/public_betting.py`)

**Source:** Action Network public endpoint (reverse-engineered / HTML scrape) or a free aggregator like VSIN. Pick whichever has a stable HTML at spec time.

**Output:** per-game dict `{market: {side: ticket_pct, money_pct}}`.

**Cache:** `data/public_betting/<game_date>.json`, overwritten hourly (last-write-wins).

**Briefing surface:** per-game section listing ticket% + money% on each side; highlight splits (ticket-heavy + money-light = potential RLM confirmer).

**Downstream unlock:** feeds the `public_pct` column in `data/line_movement.csv` (RLM spec) so `classify_rlm` returns proper `RLM` vs `SHARP_MOVE` distinction.

**Feature flag:** `SOURCES_ENABLED["public_betting"] = True`.

**Legal/robustness note:** this source is the weakest — if Action Network blocks scraping or restructures HTML, gracefully degrade to "unavailable" and do not fail the pipeline.

### 3. Travel / Rest (`scrapers/schedule_context.py`)

**Source:** MLB Stats API `/schedule` — already integrated in `scrapers/scores.py`. Pull previous 10 days of games per team.

**Output:** per-team, per-game-date dict:
```python
{"days_since_last_game": 1, "timezone_shift_hours": -3,
 "consecutive_games": 5, "is_get_away_day": True,
 "is_day_after_night": True}
```

**Cache:** keyed by `(team, game_date)`, trivial to derive — no cache needed; compute on demand in <10ms per team.

**Briefing surface:** one-liner per team in the existing team-profile block (`Rest: 1d (5 in a row, day after night game, -3hr tz)`).

**Simulation impact:** none in v1. Document a v2 hook to shift pitcher fatigue on `consecutive_games >= 5` but defer to next phase.

**Feature flag:** `SOURCES_ENABLED["schedule_context"] = True`.

### 4. Day/Night + Home/Away Splits (`scrapers/player_stats.py` extension)

**Source:** `pybaseball.pitching_stats_bref` (or the newer `pitching_stats` Statcast split endpoint) filtered to the starter's season.

**Output:** per pitcher:
```python
{"day": {"ip": 42.0, "era": 3.21, "k9": 9.1, "bb9": 2.8},
 "night": {"ip": 67.0, "era": 4.55, "k9": 8.3, "bb9": 3.2},
 "home": {...}, "away": {...}}
```

**Cache:** reuse existing `data/pitcher_stats_cache.json` by adding split keys (invalidate the cache once on first release).

**Shrinkage:** same-season splits are always small-sample. Emit a single `day_night_k_delta` and `day_night_bb_delta` shift ∈ `[-0.02, +0.02]`, applied to `sample_pa` K/BB rates only when the split has `ip >= 30`.

**Briefing surface:** add one line to the pitcher profile block.

**Feature flag:** `SOURCES_ENABLED["day_night_splits"] = True`.

## Architecture

```
config.py
  SOURCES_ENABLED["bvp_history"]
  SOURCES_ENABLED["public_betting"]
  SOURCES_ENABLED["schedule_context"]
  SOURCES_ENABLED["day_night_splits"]
  # SOURCES_ENABLED["statcast_advanced"] etc. already landed under Spec 10

scrapers/_cache.py              ← landed under Spec 10 (statcast-umpire-catcher)
scrapers/bvp_history.py         ← new
scrapers/public_betting.py      ← new
scrapers/schedule_context.py    ← new
scrapers/player_stats.py        ← extend with day/night/home/away

simulation/pa_engine.py         ← accept `bvp_shift`, `day_night_k_delta`, `day_night_bb_delta`
simulation/game_sim.py          ← thread shifts through `sample_pa` call

briefing.py                     ← 4 new sections (guarded by SOURCES_ENABLED)

data/bvp_cache.json             ← generated
data/public_betting/            ← generated directory, per-date files
```

## Shared conventions (cross-cutting)

- **Graceful degradation:** every scraper returns `None` (never raises) when its feature flag is off, its fixture is missing, or its HTTP call fails. Callers treat `None` as "no data — don't shift."
- **Briefing format:** each new section follows the existing tag convention `[SOURCE]` (e.g. `[BVP]`, `[PUBLIC]`, `[REST]`, `[DAY/NIGHT]`) so downstream LLMs can reference them consistently.
- **Fixture fallback:** each source ships with a frozen fixture under `tests/fixtures/<source>_sample.json` and loads it when `PYTEST_CURRENT_TEST` is set.
- **Shrinkage first:** any sim shift goes through a shared `simulation/shrinkage.py::bayes_shrink(rate, sample_size, prior, k_prior)` helper (created under this spec if not already present) so priors are consistent across sources.

## Testing strategy

Per source, same shape:
- Cache hit / miss / stale.
- HTTP error → returns `None`, pipeline continues.
- Shrinkage at n=0, n=k_prior, n=large.
- Briefing section present iff enabled + data non-None.
- `sample_pa` rate sums to 1 after shift (invariant).

## Risks / open questions

- **Public betting reliability:** Action Network will break eventually. Design the scraper to tolerate HTML changes by parsing by CSS-stable data attributes if possible; otherwise document the TOS status explicitly.
- **BvP sample noise:** 22 PAs vs. a pitcher is almost nothing. Shrinkage mitigates but doesn't eliminate. Watch for a false-edge spike in logs once enabled.
- **Day/night splits confounding:** some starters don't pitch much at day; the split is near-meaningless. `ip >= 30` floor is the first filter; may need to tighten to 50.

## Rollout

Per-source independent rollout. Suggested order:
1. **Travel / rest** first — zero external dependencies, derivable from data we already have.
2. **Day/night splits** — ride on existing pitcher-stats cache.
3. **BvP history** — moderate cost, real shift.
4. **Public betting %** last — highest breakage risk, biggest unlock for the RLM spec.
