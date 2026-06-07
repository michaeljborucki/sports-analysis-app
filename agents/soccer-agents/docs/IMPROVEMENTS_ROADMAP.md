# MiroFish Soccer — Improvements Roadmap

Drafted 2026-04-17 after a 4-agent brainstorm across (1) prediction quality,
(2) soccer-specific data, (3) betting strategy & risk, (4) code quality & ops.
Extended same day with patterns ported from `baseball-agents`.

Phase 1 + baseball-inspired ops patterns are **shipped**. Phases 2 and 3 are
planned next work. Reassess priorities once Phase 1 has generated ~50
CLV-tagged bets so we can measure against close lines instead of raw W/L noise.

---

## Phase 1 — SHIPPED (2026-04-17)

| Agent | File | What it does | Status |
|-------|------|--------------|--------|
| CLV tracker | `tracker.py`, `agents/clv_snapshotter.py` | Adds `market_prob`, `close_market_prob`, `clv`, `league` columns to bets.csv. `snap-close` CLI fetches closing odds pre-kickoff and records CLV per bet. `report` now prints avg CLV + beat-close %. | ✅ |
| xG-Poisson quant challenger | `ensemble/quant_poisson.py` | Bivariate Poisson + Dixon-Coles ρ=-0.15 low-score correction. Injected as a 7th voter in `run_ensemble` when `match_data` is passed. 1.5x default weight on total + BTTS slots. | ✅ |
| Club Elo anchor | `scrapers/club_elo.py` | Free daily CSV from clubelo.com; `get_match_elo` returns home/away Elo + HFA-adjusted 1X2 probs. Cached per-date in `data/club_elo/`. Injected into `briefing.py` as a "POWER RATINGS" section. **MLS not covered** (clubelo limitation). | ✅ |
| Fixture-congestion agent | `scrapers/context.py` (replaces stub) | Rest-days + matches-in-last-10d + upcoming-continental-cup (UCL/UEL/UECL/cup, 72h window) + motivation classification from standings + derby flag + crude dead-rubber flag. Injected into briefing. | ✅ |
| Correlation manager | `edge.py`::`apply_correlation_penalty` | Scales same-match Kelly stakes by `1/sqrt(1 + Σρ)`. Priors: ρ(AH,T)=0.40, ρ(AH,BTTS)=0.30, ρ(T,BTTS)=0.70. | ✅ |
| Bankroll guardian | `agents/bankroll_guardian.py` | Drawdown Kelly annealer (-10u → 0.5x, -15u → 0.25x, -20u → circuit break) + daily 5% exposure cap + proportional rescale on overflow. `bankroll` CLI shows state. | ✅ |
| Integrity auditor | `agents/integrity.py` | `audit-orphans` finds rows >48h without results and auto-regrades. `audit-names` checks every Odds API team resolves to ESPN standings (defends the 100% mapping fixed in commit 5f5ab24). | ✅ |

### New CLI commands
- `python3 main.py snap-close [--date YYYY-MM-DD]` — run ~15m pre-kickoff
- `python3 main.py bankroll` — show guardian state
- `python3 main.py audit-orphans` — re-grade stale bets
- `python3 main.py audit-names` — team-name mapping check
- `python3 main.py report` — now includes CLV

## Phase 1.5 — SHIPPED (baseball-inspired ops patterns, 2026-04-17)

Patterns ported directly from `baseball-agents` where the mature version
already existed:

| Pattern | Baseball file → Soccer file | What changed |
|---------|-----------------------------|--------------|
| Thread-safe tracker + bet-log dedup | `tracker.py` | `_csv_lock` mutex + `log_bet` returns False on duplicate (date, game, bet_type, side). Enables safe parallel writes. |
| Separate `closing_lines.csv` table | `scrapers/closing_lines.py` (new) | Proper CLV table keyed on (date, game, bet_type, side, line) with time-windowed capture (T-15 to T-5). Replaces our ad-hoc `snap-close`. |
| Auto-CLV at grade time | `tracker.update_result` | When a bet is settled, `update_result` looks up the matching closing-line row and fills `clv` + `close_market_prob`. Zero extra command runs. |
| Parallel screening + simulation | `main.py::daily` | `ThreadPoolExecutor(max_workers=PARALLEL_GAMES)` for both phases. Dropped `signal.alarm` (doesn't work in threads anyway). Throughput scales ~linearly with `PARALLEL_GAMES` (default 3). |
| `close-capture` CLI | `main.py` | Standalone command for cron: `python3 main.py close-capture`. Silently no-ops outside window. Use `--force` for backfill. |
| Notify module (Discord) | `notify/` (new) | Filter config at `data/alerts_config.json`, dedup at `data/notifications_sent.json`. `--no-notify` flag on `daily`. |

### New CLI commands (Phase 1.5)
- `python3 main.py close-capture [--force]` — CLV capture, cron-friendly
- `python3 main.py notify [--force] [--dry-run]` — Discord dispatch
- `python3 main.py daily --no-notify` — skip post-pipeline Discord send

### Bugfix: AH/total devig was mixing lines across bookmakers
Previously, `scrapers/odds.py` devigged every (home_price, away_price) pair
across all books and averaged the results — ignoring that different books
offer different handicap/total lines (e.g. -0.5, -0.75, 0 DNB). The
"consensus" probability was a mash of bets with different payout structures.

Fix: group pairs by line, pick the mode line (most books), devig only within
that group. Also overrides `od.asian_handicap` / `od.total` with the mode-line
consensus so edge detection and the bet-side label agree. Adds
`ah_lines_seen` / `total_lines_seen` diagnostics in `implied_probs`.

Impact: a meaningful share of pre-fix "edges" were false positives — betting
at minority lines offered by a single book against a fake multi-line
consensus. Post-fix, `market_prob` values are ~0.10 different on matches with
AH line variation, and the bet's `side` label now reflects the mode line.

### Migration notes
- `bets.csv` columns expanded. Legacy rows are auto-migrated on first read
  (empty strings fill new columns). No manual migration required.
- `model_weights.json` gains a `quant_poisson` entry on next write; safe to
  delete the file to regenerate with the new defaults.
- `scrapers/context.py` is now a live scraper (was a hard-coded stub).
  First pipeline run will add ~2 ESPN API calls per match.

### Known caveats / must-verify
- **Dead-rubber detection is crude.** Currently flags "both teams mid-table" —
  doesn't account for matchday number. Refine once we have a reliable
  matches-remaining signal.
- **Correlation priors are literature estimates, not measured.** Revisit
  values once ~100 settled bets exist and empirical correlation can be
  computed from `bets.csv`.
- **Club Elo team matching is best-effort.** Watch logs for
  `Club Elo: no match for '<team>'` — add to `CLUBELO_OVERRIDES` as they surface.
- **CLV snap-close** currently uses consensus implied across multiple books,
  not Pinnacle specifically. Converges to sharp signal when Pinnacle is in the
  book list; add a Pinnacle-only mode if we start pulling from `eu` region.

---

## Still worth porting from baseball (P2-ish, not yet done)

These patterns exist in `baseball-agents` but weren't ported yet because they
need soccer-specific adaptation:

### BP.1 — Ensemble cache (per-day JSON, keyed by lineup hash)
**Baseball:** `cache/ensemble_cache.py`. Keyed by `(game_pk, starters_hash)`
where starters_hash is SHA256 of 9 batters + SP per side. Lets re-runs skip
the ensemble (and screening) when lineups haven't changed.
**Soccer adaptation needed:** Starting XIs aren't confirmed until ~60m pre-match.
Options: (a) hash-skip-when-lineup-unknown + hash-hit-when-lineup-confirmed,
(b) hash on (injuries + last-5-form + odds-line) as a looser cache key.
**Win:** re-running the pipeline at T-3h and T-1h same day costs ~50% less.
**Effort:** M.

### BP.2 — Monte Carlo player-prop simulation
**Baseball:** `simulation/` (game_sim, pa_engine, monte_carlo, props_edge) runs
5000 sims on confirmed lineups to price hits/HR/K props — entirely independent
of the LLM ensemble.
**Soccer adaptation:** Same idea, different distributions. Shot count per
player ≈ Poisson(λ=xG-per-90/90 × minutes). Goals ≈ Bernoulli given shot
quality. Assists ≈ correlated with team-xG. Offers:
- "Player X to score anytime" (BetMGM, DraftKings have this for EPL)
- "Player X over 2.5 shots"
- "Player X over 0.5 assists"
**Prereq:** FBref per-player xG/xA (currently missing; see P2.4 in original roadmap).
**Effort:** L.

### BP.3 — Per-event odds enrichment (`get_additional_odds`)
**Baseball:** Per-event endpoint fetches F5/F3/F1/team-totals/NRFI markets
after the main odds pull. Soccer equivalent markets:
- Asian handicap ±0.25, ±0.75, ±1.25 lines (quarter lines)
- Double chance (1X, X2, 12)
- Draw no bet
- Team totals (home/away over/under 1.5/2.5)
- Half-time / full-time combos
- First team to score
- Exact score
**Effort:** M. Check Odds API `markets=` parameter for which are available.
**Gate:** only worth it if per-event endpoint doesn't cost extra API calls.

### BP.4 — `kelly_analysis.py` script
**Baseball:** `scripts/kelly_analysis.py` — rich per-bet Kelly breakdown with
scenarios (flat 1u vs ⅛-Kelly vs ¼-Kelly on logged bets).
**Effort:** S. Mostly a port, updated for soccer bet types.

### BP.5 — `recover_model_predictions.py` script
**Baseball:** Recovery tool when `model_predictions.csv` gets corrupted or
mis-filtered. Rebuilds from logged ensemble outputs.
**Effort:** S. Worth porting defensively.

### BP.6 — `daily_runner.py` subprocess wrapper (retry + outer timeout)
**Baseball:** Wraps `main.py daily` in `subprocess.run(timeout=3600)` with
explicit retry loop. Ours uses `--grade-yesterday` only and delegates retry to
pipeline internals.
**Win:** Cleaner failure mode — if a pipeline run hangs, outer timeout kills it
and retries from scratch. Our in-process `run_ensemble` can leak LLM calls on
exception.
**Effort:** S.

---

## Phase 2 — NEXT (data quality + measurement infra)

Build order matters: the backtest harness is a prerequisite for the rest.

### P2.1 — Backtest replay harness
**Scope:** CLI `python3 main.py backtest --weeks 8` that replays archived
briefings through the current ensemble (using cached LLM responses where
available) and reports ROI / Brier / log-loss / CLV per league × bet slot.
**Why now:** 50-bet sample sizes take weeks live. Required before tuning
thresholds, weights, or calibration. Without this, every Phase 2/3 change
is blind.
**Effort:** 1-2 days.
**Files:** new `agents/backtest.py`, extends `ensemble/logger.py` to archive
briefings + parsed responses, new `data/backtest_runs/`.

### P2.2 — Isotonic calibration (per league × bet slot)
**Scope:** Build out `calibrate.py` (currently a stub). Fit isotonic
regression per (league, bet_slot) on settled ensemble probabilities vs
outcomes. Insert a `calibrate_prob(prob, league, slot)` call between
`build_ensemble_result` and `edge.analyze_all_edges`.
**Why now:** LLMs are documented to be overconfident in the 0.6-0.75 band
where most AH/BTTS picks live. Per-league fits matter because MLS vs Serie A
have very different home-advantage regimes (already encoded in
`HOME_ADVANTAGE_BY_LEAGUE`).
**Blocker:** Needs 50+ settled bets per (league × slot) cell → ~6-8 weeks of
live data OR the backtest harness above.
**Effort:** 1 day after backtest exists.

### P2.3 — Line-movement gate (pre-bet)
**Scope:** Poll odds at publish-time AND at `snap-close`. If line steamed
15+ cents against our side, block/downsize the bet. If it steamed toward
us, we're on the sharp side — allow full Kelly.
**Why now:** Soccer lines are the most lineup-sensitive of major sports —
starting XI drops ~60m pre-kickoff and totals can move 20 cents. Betting 4h
early into steam is -EV even when the model says +EV.
**Effort:** S (needs odds-history persistence; 1 day). Add
`data/odds_history/<date>/<match>.json` and diff on snap.

### P2.4 — FBref shot-based xG + GK PSxG
**Scope:** Replace the Poisson-from-goals proxy in `scrapers/xg.py` with real
xG / xGA / PSxG from FBref team squad pages. Respects 1 req/3s rate limit.
**Why now:** Our quant Poisson voter is only as good as its xG inputs.
Real xG separates finishing luck from chance creation.
**Effort:** M (1-2 days). **Risk:** FBref HTML occasionally changes — cache
aggressively + add a schema-drift alert.

### P2.5 — Match-day weather agent
**Scope:** One OpenWeather call per fixture (key already in config as
`WEATHER_API_KEY`). Wind/rain/temp at kickoff for the venue.
**Blocker:** Need a venue → lat/lon table (~80 stadiums across 4 leagues).
**Effort:** S (~half day including stadium coords).
**Lift:** ~1% on totals, bigger on weather-extreme MLS early-season games.

### P2.6 — Referee profile agent
**Scope:** Rolling cards/game, pens/game, home-bias index per referee from
FBref or the league's official ref-assignment feed. Extra briefing section.
**Effort:** M (1-2 days). **Risk:** ref assignments are flaky for
Eredivisie/MLS; EPL/Serie A publish reliably ~48h out.
**Lift:** ~1% on totals (late-stoppage goals), ~2% on BTTS (pens).

### P2.7 — Quarter-line AH optimizer
**Scope:** When AH 0, ±0.25, ±0.5 all exist, pick the minimum-vig
representation. Auto-convert strong ML edges to DNB / AH 0 equivalents.
**Effort:** M.
**Lift:** +0.5-1.5% ROI from vig reduction alone; more bets qualify.

---

## Phase 3 — LATER (after Phase 2 + real CLV data)

### P3.1 — Market-efficiency / bet-type rotator
Suspend (league × bet_type) cells with 50-bet ROI < -5% AND CLV < 0.
Re-enable after 10 paper-traded wins. Extends `agents/self_optimizer.py`.

### P3.2 — Late-news kickoff window
For lineup-sensitive bet types (total, BTTS, AH-heavy-fav), refuse to place
>3h before kickoff. Queue for T-45m re-check.

### P3.3 — Stale-model / drift detector
Daily job: each model's 30-day Brier vs 90-day baseline. Auto-halve weights
on 1.5σ drift until recovery. Extends `agents/self_optimizer.py`.

### P3.4 — Expected lineups + star-player flag
Scrape rotowire/sofascore expected XI ~2h pre-match. Flag starting GK,
main striker, CBs. Combine with `scrapers/injuries.py`.
**Risk:** timing-sensitive + scraping fragility.

### P3.5 — Set-piece proficiency
SP xG for/against + corner counts from FBref (free if P2.4 lands).

### P3.6 — Cost/quota guardrail
Pre-flight check: OpenRouter credit balance + Odds API quota, project spend
(`len(fixtures) * MAX_CALLS_PER_GAME * avg_cost`), abort/downshift on overrun.

### P3.7 — Data-freshness & schema gate
Hard-fail pre-ensemble if odds timestamps are stale, briefing JSON keys
missing, or a league's fixture count is anomalously low.

### P3.8 — Cheap-screener swap
Shadow-run Haiku/GPT-4o-mini as screener vs Kimi K2.5 for a week. If cheap
recall >95%, flip the toggle. Screener is ~60% of LLM calls → 70-80% cost cut.

### P3.9 — Prompt regression / golden-set tester
Lock 10 canonical briefings + expected prob ranges. CI fails on
prompt/briefing edits that shift per-model probs >X%. Extends
`tests/ensemble_fixtures.py`.

### P3.10 — SPI / Understat data pull
Secondary power-rating anchor to cross-check Club Elo; Understat shot-level
xG for in-match context once we add live/prop markets.

---

## Ideas parked (not prioritized)

- **In-play hedge agent** — bet BTTS Yes, game is 1-0 at 60', auto-hedge.
  Interesting but requires live odds polling infra not currently built.
- **Manager-change bounce detector** — new-manager bump is real but noisy;
  needs ~6 months of data to validate the signal.
- **Transfer-window effects** — deadline-day signings not integrated; would
  need a targeted news scraper. Low lift per hour.
- **Public betting %** — Action Network scraping is brittle; the sharp-money
  signal from line movement (P2.3) likely captures most of the edge.
- **Rewrite `docs/improvement-ideas.md`** — that file is MLB-themed (umpires,
  Statcast, F5). Replaced by this document; delete after review.

---

## Notes for future work

- **Revisit correlation priors** (`SAME_MATCH_CORRELATION` in `edge.py`) once
  the bet log has enough samples to compute empirical correlations. The 0.7
  BTTS/total correlation is the one most likely to be wrong.
- **Bankroll guardian thresholds** (`BANKROLL_RULES` in
  `agents/bankroll_guardian.py`) are seat-of-pants. Revisit with the
  `staking-model backtester` idea (P3.x if we prioritize it).
- **Quant Poisson weight of 1.5x on total/BTTS** is a judgment call. Let Brier
  scoring + `update_model_weights()` converge it naturally.
- **The `market_prob` column used for CLV calculation** is whatever
  `edge.check_*` writes when the bet is detected — this is the devigged
  market implied prob at bet-decision time. Compare to `close_market_prob`
  from `snap-close` for CLV.
