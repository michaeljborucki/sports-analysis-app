# Contextual Enrichment Phase 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship four per-source-flagged context scrapers — BvP history, public betting %, travel/rest, day-night splits — each surfacing in the briefing and (where applicable) nudging `sample_pa` rates with Bayesian-shrunk shifts.

**Architecture:** Each source is a standalone scraper with fixture fallback, reusing the `scrapers/_cache.py` helper landed under Spec 10 (statcast-umpire-catcher). New keys in `SOURCES_ENABLED` gate each source. A new `simulation/shrinkage.py` provides a shared `bayes_shrink` helper so sim-affecting shifts have consistent priors. BvP + day/night produce `bvp_shift` / `day_night_k_delta` / `day_night_bb_delta` shifts wired into `sample_pa`; public % + travel/rest are briefing-only in v1 (public % also unlocks proper `classify_rlm` in the RLM spec).

**Tech Stack:** `pybaseball>=2.2.7`, `requests`, `BeautifulSoup4` (for public-betting HTML scrape), `pandas`, `pytest`, existing `filelock`.

**Spec:** `docs/superpowers/specs/2026-04-19-contextual-enrichment-phase-2-design.md`

**Recommended source order:** schedule_context → day_night_splits → bvp_history → public_betting.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `config.py` | Modify | Add 4 keys to `SOURCES_ENABLED`; add `BVP_MIN_PA`, `DAY_NIGHT_MIN_IP`. |
| `simulation/shrinkage.py` | Create | `bayes_shrink(rate, n, prior, k_prior)` shared helper. |
| `scrapers/schedule_context.py` | Create | `get_team_context(team, game_date)` returning rest/travel dict. |
| `scrapers/player_stats.py` | Modify | Add `get_pitcher_day_night_splits(pitcher_id, season)`; extend existing cache with split keys. |
| `scrapers/bvp_history.py` | Create | `get_bvp(batter_id, pitcher_id, season)`; 7-day TTL cache. |
| `scrapers/public_betting.py` | Create | `get_public_betting(game_date)`; hourly-refresh cache; graceful degradation to `None`. |
| `simulation/pa_engine.py` | Modify | Accept `bvp_shift`, `day_night_k_delta`, `day_night_bb_delta`; apply after platoon routing, before normalization. |
| `simulation/game_sim.py` | Modify | Thread shifts through every `sample_pa` call site. |
| `briefing.py` | Modify | 4 new sections, each guarded by `SOURCES_ENABLED[<source>]` and non-None data. |
| `data/bvp_cache.json` | Create (generated) | BvP lookup cache. |
| `data/public_betting/` | Create (generated) | Per-date JSON snapshots. |
| `tests/fixtures/bvp_sample.json` | Create | Frozen sample for offline tests. |
| `tests/fixtures/public_betting_sample.json` | Create | Frozen sample. |
| `tests/test_schedule_context.py` | Create | Days-since-last-game, timezone shift, consecutive-games counters. |
| `tests/test_day_night_splits.py` | Create | Split extraction, shrinkage, min-ip gate. |
| `tests/test_bvp_history.py` | Create | Cache roundtrip, shrinkage, min-PA gate. |
| `tests/test_public_betting.py` | Create | Fixture parse, graceful degradation on HTTP error. |
| `tests/test_pa_engine_enrichment.py` | Create | Shifts applied, sum-to-1 invariant, shifts=0 when data absent. |

---

## Tasks

### Step 0 — Shared prep
- [ ] Add 4 keys to `SOURCES_ENABLED` (all `False` by default — per-source enable during rollout).
- [ ] Create `simulation/shrinkage.py` with `bayes_shrink(rate, n, prior, k_prior) -> float`.
- [ ] Add `tests/test_shrinkage.py`: n=0 → prior, n=k_prior → midpoint, n→∞ → rate.

### Step 1 — Schedule context (lowest risk, ships first)
- [ ] Implement `scrapers/schedule_context.py::get_team_context(team, game_date)` using the existing MLB schedule plumbing in `scrapers/scores.py`.
- [ ] Compute `days_since_last_game`, `consecutive_games`, `is_get_away_day`, `is_day_after_night`, `timezone_shift_hours`.
- [ ] Write `tests/test_schedule_context.py` against a schedule fixture covering: day off, 5-in-a-row, cross-coast travel, doubleheader.
- [ ] `briefing.py`: add a one-line "Rest / travel" row to each team's profile block.

### Step 2 — Day/night splits
- [ ] Extend `scrapers/player_stats.py` with `get_pitcher_day_night_splits(pitcher_id, season)` returning `{day, night, home, away}` buckets.
- [ ] Invalidate existing `data/pitcher_stats_cache.json` once on release (bump a `CACHE_VERSION` constant).
- [ ] Compute `day_night_k_delta` and `day_night_bb_delta` using `bayes_shrink` against league avg, `DAY_NIGHT_MIN_IP=30`.
- [ ] `tests/test_day_night_splits.py`: extraction, min-IP floor, shrinkage endpoints.
- [ ] `simulation/pa_engine.py`: thread `day_night_k_delta`/`day_night_bb_delta` as additive shifts on K and BB rates, normalize, re-sum to 1.
- [ ] `simulation/game_sim.py`: pass game-time (day vs night from schedule) + home/away into `sample_pa`.
- [ ] `briefing.py`: one-line add to pitcher profile.

### Step 3 — BvP history
- [ ] Implement `scrapers/bvp_history.py::get_bvp(batter_id, pitcher_id, season)` using `pybaseball.statcast_batter` filtered to pitcher.
- [ ] Cache at `data/bvp_cache.json` with 7-day TTL.
- [ ] Compute `bvp_shift ∈ [-0.03, +0.03]` wOBA via `bayes_shrink` against league wOBA, `BVP_MIN_PA=12`.
- [ ] `tests/test_bvp_history.py`: cache roundtrip, n=0 returns `None`, n=20 returns shifted.
- [ ] `simulation/pa_engine.py`: accept `bvp_shift`, apply as a wOBA-level nudge on hit outcomes before normalization.
- [ ] `simulation/game_sim.py`: look up BvP per (batter, starter) at game init.
- [ ] `briefing.py`: new `[BVP]` section per game listing any batter with `pa >= BVP_MIN_PA` vs. the starter.

### Step 4 — Public betting %
- [ ] Implement `scrapers/public_betting.py::get_public_betting(game_date)` with Action Network (preferred) or VSIN parser.
- [ ] Cache per-date JSON; gracefully return `None` on HTTP error or HTML-structure change.
- [ ] `tests/test_public_betting.py`: fixture parse, HTTP 500 → `None`, HTML-changed → `None`.
- [ ] `briefing.py`: new `[PUBLIC]` section with ticket% + money% per side; highlight ticket/money splits.
- [ ] Integrate downstream into RLM spec's `classify_rlm` by populating `public_pct` in `data/line_movement.csv`.

### Step 5 — End-to-end verification
- [ ] `tests/test_pa_engine_enrichment.py`: `sample_pa` with all shifts=0 identical to pre-enrichment; with shifts nonzero, rates still sum to 1; shifts applied in expected direction.
- [ ] Briefing smoke test: run `main.py daily --date <past> --dry-run` with each flag individually enabled; eyeball briefing output per source.
- [ ] Run against 1 day of live data with all flags on; verify no regressions in edge output (compare to prior snapshot).

### Step 6 — Rollout
- [ ] Enable `schedule_context` in production; observe 1 week.
- [ ] Enable `day_night_splits`; compare pitcher-prop EV before/after.
- [ ] Enable `bvp_history`; scan for EV drift in hitter props.
- [ ] Enable `public_betting` last; verify RLM flag distribution shifts as expected.
