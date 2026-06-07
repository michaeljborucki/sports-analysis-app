# Sports Betting Agent Framework

A generic blueprint for building automated, sport-agnostic prediction-and-betting pipelines. This document captures the shared architecture that any sport repo should follow.

> **This is a template, not a contract.** Every section below is a starting point. Add new components freely (cron jobs, state files, modules, bet types, analysis passes) — the framework is meant to be extended per sport's needs, not strictly conformed to. Anything in this doc with a fixed number (pipeline steps, analyst angles, etc.) is "a reasonable starting baseline," not "the only valid shape." If a sport needs a fifth pipeline step or a new state file, add it.
>
> **Two use cases:**
> 1. **New sport** — spin up a fresh repo following the patterns here.
> 2. **Existing sport** — compare the existing implementation against this doc to find drift. Each sport repo evolves independently; this framework gives a baseline to align them. Use the operational checklist near the bottom as a per-repo gap audit.

## TL;DR — what the system does

Every day, for each scheduled game in a sport:
1. Detect when the game is close enough to bet (lineups confirmed, odds posted)
2. Run a model to predict probabilities for each market
3. Compare model probabilities to bookmaker odds — log any positive-EV bets
4. Send the day's picks to Discord
5. After the game ends, grade the bets against the final score
6. Capture closing odds independently — compute CLV (Closing Line Value)
7. Periodically re-analyze historical bets to refine which markets/segments to keep, fine-tune, or cut

The system is built so each layer is replaceable per sport, but the conventions (state files, dedup keys, scheduling logic, filter shapes) are shared.

---

## Daily flow (the happy path)

The diagram below shows **the baseline moving parts**. It's a starting set, not a complete one. New parts are expected — you might add a player-availability scraper that runs hourly, a model-monitoring agent that watches for ROI drift, a bankroll manager that gates Kelly sizing on weekly P&L, an arbitrage detector that cross-references multiple books, etc. Slot new components in wherever they fit; they don't have to fit the cron-driven pattern.

```
┌─ AUTO-ANALYZER (cron, every 30 min) ───────────────────┐
│  Read schedule + analyzed_games state.                 │
│  Any unanalyzed game with first-pitch within 2h?       │
│    yes → launch DAILY PIPELINE (subprocess)            │
│    no, but more games coming → idle                    │
│    no future unanalyzed games → "monitoring complete"  │
│       + auto-delete cron (rearm tomorrow morning)      │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌─ DAILY PIPELINE ───────────────────────────────────────┐
│  1. Fetch schedule (free sport API)                    │
│  2. Fetch odds (paid API)                              │
│  3. Fetch lineups → drop games with no lineup yet      │
│  4. Fetch injuries                                     │
│  5. Skip already-analyzed games                        │
│  6. Screen each game (cheap LLM filter)                │
│  7. Full ensemble + Monte Carlo on flagged games       │
│  8. Edge detection: model_prob vs market_prob          │
│  9. Apply BET_FILTERS (per-bet-type whitelist)         │
│ 10. Log bets to bets.csv                               │
│ 11. Mark each game in analyzed_games.csv               │
│ 12. Dispatch Discord alerts (filtered + deduped)       │
│ 13. Write daily bet card → bet_card_<date>.{txt,json}  │
└────────────────────────┬───────────────────────────────┘
                         │
                         ▼
┌─ CLOSE CAPTURE (cron, slow watcher → fast burst) ──────┐
│  Phase 1 — SLOW WATCHER (every 10 min):                │
│    Pre-check 1: bets logged for today? (free)          │
│    Pre-check 2: game in T-5..T-30 window? (free)       │
│    Pre-check 3: all today's games started? (free)      │
│      yes → "monitoring complete" + auto-delete cron    │
│    If captured rows > 0 → REPLACE self with fast burst │
│                                                        │
│  Phase 2 — FAST BURST (every 2 min):                   │
│    Same pre-checks; same shutoff signal.               │
│    Captures every line move during the active window.  │
└────────────────────────────────────────────────────────┘
                         ▲
                         │ daily re-arm at 08:05 local
                         │
┌─ MORNING REARM (cron, daily) ──────────────────────────┐
│  If today has games:                                   │
│    → recreate auto-analyzer cron if missing            │
│    → recreate close-capture slow watcher if missing    │
│  Both crons self-delete end of day; rearm restores     │
│  them before next day's slate.                         │
└────────────────────────────────────────────────────────┘

────────────────  next day  ────────────────

┌─ GRADER ───────────────────────────────────────────────┐
│  Compare each bet to final score → W/L/P + profit      │
│  Look up closing line for each bet                     │
│  Compute CLV (cents + %) → write to bets.csv           │
│  Send grade summary + season totals to Discord         │
└────────────────────────────────────────────────────────┘

────────────────  weekly / on demand  ────────────────

┌─ ANALYST AGENTS ───────────────────────────────────────┐
│  4 parallel analyses of bets.csv:                      │
│   • CLV vs ROI quadrant per bet type                   │
│   • Edge calibration (predicted edge vs realized CLV)  │
│   • BET_FILTERS validation (kept vs dropped CLV)       │
│   • Prop concentration (per-market, per-player CLV)    │
│  Output → BET_FILTERS / calibration adjustments        │
└────────────────────────────────────────────────────────┘
```

---

## Core data model

The schemas below are **the minimum** every sport repo should support. Each one is extensible — add columns for sport-specific signals (e.g., `weather_temp`, `surface`, `bullpen_hand`, `referee`), add new state files entirely (e.g., `injuries_log.csv`, `model_versions.csv`, `bankroll_history.csv`), or split a single file into per-day shards. The dedup keys and required columns are the contract; everything else is yours to shape.

### `bets.csv` — the source of truth
One row per logged bet. Schema (extend per sport but never break these):
```
date, game, bet_type, side, odds, sim_prob, edge, kelly_pct,
result, profit, market_prob, close_odds, close_prob, clv_cents, clv_pct
```
- `date`: game date in US/Eastern, ISO `YYYY-MM-DD`
- `game`: `"<AWAY>@<HOME>"` for team sports; sport-specific format otherwise (e.g. `"PlayerA-vs-PlayerB"` for tennis)
- `bet_type`: enum (e.g. `moneyline`, `total`, `batter_hits`, `pitcher_strikeouts`)
- `side`: free-form, must include direction + line so the parser can extract it (e.g. `"home -1.5"`, `"over 8.5"`, `"Player Name under 1.5"`)
- `odds`: American format
- `sim_prob`: model's predicted win probability (post-calibration)
- `edge`: fractional (`0.10` = 10% edge over fair line)
- `kelly_pct`: recommended bet size (typically quarter-Kelly)
- `result`: `W` / `L` / `P` (push) — empty until graded
- `profit`: in units (1u stake basis)
- `market_prob`: bookmaker's no-vig implied probability
- `close_odds` / `close_prob` / `clv_cents` / `clv_pct`: filled by the grader from closing_lines.csv

### `closing_lines.csv` — CLV ground truth
One row per (game, market, side, line, player_name) snapshot. Captured live or backfilled.

### `analyzed_games.csv` — pipeline state
One row per game per pipeline run, with status (`flagged`, `no_edge`, `no_odds`, `screen_error`, `screen_timeout`). Lets the auto-analyzer skip work it's already done.

### Other state files
- `notifications_sent.json` — Discord dedup
- `alerts_config.json` — alert channel + bet_type whitelist + min_edge / min_kelly thresholds
- `bet_card_<date>.{txt,json}` — per-day mainline summary (history preserved by date suffix)

---

## Module map

This table lists **the baseline module set** the framework assumes. Add your own freely — sport-specific stat scrapers, bankroll managers, parlay-correlation analyzers, lineup-change watchers, anything. Modules don't need to fit any of the existing categories.

| Concern | Module | Responsibility |
|---|---|---|
| Daily orchestration | `agents/daily_runner.py` | Health check → grade yesterday → run pipeline → bet card |
| Pipeline | `main.py daily` command | The 6-step pipeline above |
| Schedule + lineups | `scrapers/<sport>.py` | Sport-specific data adapters |
| Odds | `scrapers/odds.py` | Paid Odds API client (live + historical) |
| Edge detection | `edge.py` | `analyze_all_edges(sim, odds) → list[bet]` |
| Per-bet-type filters | `config.py:BET_FILTERS` + `edge.py:_passes_bet_filter` | Whitelist what gets logged |
| Calibration | `calibrate.py:apply_calibration(prob, bet_type)` | Currently a hard cap; grows into isotonic regression |
| Closing-line capture | `scrapers/closing_lines.py` + `main.py close-capture` | Live snapshots + historical backfill |
| CLV apply | `tracker.py:lookup_clv()` + `main.py clv-apply` | Match bets ↔ closing lines (line-relaxed) |
| Auto-analyzer | `agents/auto_analyzer.py` | Decides when to launch the pipeline |
| Analyzed-games state | `agents/analyzed_games.py` | Persists pipeline progress per game |
| Notifications | `notify/` | Discord dispatch with dedup |
| Bet card | `agents/bet_card.py` | Daily mainline summary, dated file |
| Grader | `agents/results_grader.py` | Apply final-score → W/L/P + profit + CLV |
| Priority alerts (**universal**) | `agents/universal/priority.py` | Shared, sport-agnostic: sort games soonest-first, analyze in parallel, alert each game the instant it finishes. See [Priority alerts](#priority-alerts-universal-rule). |

---

## CLI command surface

Every sport repo exposes its operational entry points as CLI commands (typically through `main.py` with `click` subcommands). Treat the *Essential* group as required for any sport, the *CLV* group as required if the sport has a meaningful closing-line market, and the *Optional* group as add-on tooling.

| Command | Group | Purpose |
|---|---|---|
| `daily` | Essential | Run the full prediction pipeline for one date (schedule → odds → screen → simulate → log). |
| `game <AWAY> <HOME>` | Essential | Run pipeline for one specific matchup (catch-up after lineup changes). |
| `card` | Essential | Print today's bet card. Backed by the dated bet card writer. |
| `health` | Essential | Pre-pipeline diagnostic: API keys present, sport schedule reachable, LLM endpoints up. |
| `results` (or `grade`) | Essential | Compare logged bets to final outcomes; write W/L/P + profit. |
| `notify` | Essential | Dispatch the day's filtered alerts to Discord/Slack/etc. |
| `close-capture` | CLV | Live closing-line snapshot (cron-driven, T-5..T-30 window). |
| `close-backfill --start --end` | CLV | Historical backfill via the odds provider's historical endpoint. |
| `clv-apply` | CLV | Back-apply CLV from `closing_lines.csv` to any graded bet missing it. |
| `optimize` | Optional | Performance/calibration recommendations from historical data. |
| `report` | Optional | Rolling P&L / ROI summary. |

A new sport repo at minimum needs Essential. Adding CLV is the single highest-leverage upgrade once the sport has 2–4 weeks of bets logged. Optional commands grow naturally over time.

---

## Testing strategy

A regression test suite is the framework's safety net for fast iteration. New sports should follow these patterns from day one — retrofitting tests after the fact is harder.

### What to test (highest leverage first)

1. **Pure functions** — anything that takes input → produces output deterministically. Side-string parsers, CLV math, calibration, edge calculations, line extraction. Tests are fast, cheap, and catch the most refactor-time regressions.
2. **Schema contracts** — pin every CSV's column list as a literal assertion. If a column gets renamed or dropped, the test fires immediately rather than silently breaking a downstream reader days later. Same for any cross-module constant set (e.g. `PROP_BET_TYPES == PROP_MARKETS`).
3. **Output-string contracts** — when a downstream consumer (cron prompt, parser, monitoring tool) pattern-matches against a specific log line or CLI output, pin the exact string in a test. Without this, an "innocent" log message edit silently breaks the consumer.
4. **Decision logic with mocks** — for orchestration code (auto-analyzer's "should we launch the pipeline?", close-capture's pre-checks, doubleheader matcher), use mocked inputs (schedule, state file, odds response) to assert the decision tree's outputs. No live API calls.
5. **Bug-regression fixtures** — every time you fix a non-trivial bug, add a test that fails on the buggy version and passes on the fixed one. Pin it forever.

### What NOT to test

- **Live API calls** — flaky, costs credits, fails in CI. Use recorded fixture responses (e.g. `tests/fixtures/odds_response.json`) instead.
- **LLM ensemble outputs** — non-deterministic. Test the parsing and aggregation layers; treat the LLM itself as a black box.
- **Whether the model's edges are good** — that's evaluation, not regression. Use the analyst-agent loop for that.
- **Wall-clock-dependent timing** — never use `datetime.now()` in test code. Inject a fixed `now_utc` parameter or use `freezegun`.

### Suggested test file layout per sport

| File | Pins |
|---|---|
| `test_schemas.py` | Every CSV column list + cross-module constant alignments |
| `test_<bet>_filters.py` | Every BET_FILTERS rule shape (disabled, min_edge, max_edge, side/line/odds whitelist) |
| `test_clv_math.py` | `compute_clv` for fav/fav, dog/dog, mixed-sign odds combinations |
| `test_clv_lookup.py` | Exact-line match, line-relaxed fallback, prop player_name disambiguation |
| `test_<bet>_for_clv_parsing.py` | Every bet type's side string → (market, side, line, player) tuple |
| `test_auto_analyzer.py` | Decision tree: due/skip-already-analyzed/skip-too-early/shutoff-when-no-future |
| `test_output_contracts.py` | Pin exact phrases the cron prompts grep for |
| `test_<sport>_specifics.py` | Sport-specific edge cases (e.g. same-day repeated matchups, format variations, tie-break / penalty rules) |

Aim for tests that fail loudly and obviously when broken. Avoid tests that test the test framework or just exercise glue code without checking a specific behavior.

---

## Optional / experimental modules

These are modules one sport repo has wired up but that aren't yet part of the framework baseline. Evaluate per sport before adopting — benefit depends on model architecture, data volume, and the specific problem the module solves.

### Ensemble model weight tracking

**Status: not required. Evaluate per sport.**

When a sport simulates via a multi-LLM ensemble (e.g. N models × K runs per flagged game), per-model Brier scores can be computed by joining `data/model_predictions.csv` against `data/bets.csv` (settled rows only). A weighted map written to `data/model_weights.json` lets the orchestrator blend predictions: poorly-calibrated models get downweighted over time; well-calibrated models gain influence.

Baseline files when adopted:
- `agents/self_optimizer.py` — Brier score computation + weight updates
- `ensemble/orchestrator.py` — reads weights at prediction time
- `data/model_weights.json` — persistent weights, one entry per ensemble member

**When to consider adopting:**
- Simulation uses a multi-model blend (not a single ML model or single-LLM call).
- You have ≥200 settled bets per ensemble member (below that, Brier scores are too noisy to drive weight changes meaningfully).
- You suspect models drift differently (some get worse over time as the data distribution shifts).

**When to skip:**
- Single-model simulation (weights are N/A).
- Short-tail sport where the full data-collection cycle produces few settled bets per model.
- Ensemble where all members use the same base architecture (little divergence to exploit).

Add to your sport's roadmap if the above conditions are met and you want to close the "which model was right" feedback loop. Otherwise, stick with uniform ensemble averaging.

### launchd / cron install scripts

**Status: recommended for any sport running production crons.**

Every sport repo should ship `scripts/launchd/install.sh` (macOS) and/or `scripts/cron/install.sh` (Linux) that turns its scheduling scripts into persistent OS-level daemons. Detailed in [Persistent scheduling](#persistent-scheduling-launchd--cron) below.

Session-bound crons (Claude's `/loop`, `CronCreate`) die when the conversation ends — they're fine for interactive iteration but not for unattended overnight operation.

---

## Conventions

These are the conventions worth keeping consistent across sports for tooling reuse — but each is extensible. New filter keys, new calibration shapes, new pre-check stages, new dedup compositions are all fair game.

### Filter shape (`BET_FILTERS`)
A single dict in `config.py`. Each bet type maps to a small dict of optional keys:
```python
BET_FILTERS = {
    "<bet_type>": {
        "disabled": True,            # cut entirely (no bets of this type logged)
        "min_edge": 0.10,            # drop bets below this edge
        "max_edge": 0.25,            # drop bets above this edge (overconfidence guard)
        "side_contains": ["under"],  # whitelist sides containing any of these substrings
        "line_in": [4.5, 5.5],       # whitelist numeric lines
        "odds_min": -150,            # whitelist odds range (American)
        "odds_max": -110,
    },
}
```
Filters are applied AFTER edge detection, BEFORE logging. Bet types not in the dict pass through unchanged.

### `EDGE_THRESHOLDS` vs `BET_FILTERS` (don't conflate them)

Both live in `config.py` and both are keyed by bet type, but they operate at different points in the pipeline and serve different purposes:

| | `EDGE_THRESHOLDS` | `BET_FILTERS` |
|---|---|---|
| **When applied** | During edge detection (inside the model layer) | After edge detection, before logging |
| **Question it answers** | "Is the edge significant enough to call this a bet?" | "Even though we found edge, do we want to log it?" |
| **Shape** | Flat float per bet type (the minimum edge to flag) | Dict per bet type (multi-key whitelist/blacklist) |
| **Driven by** | Statistical significance, baseline noise floor | Historical CLV/ROI analysis of *which subsets actually win* |
| **Changes when** | The model's noise characteristics change | An analyst-agent run finds a losing subset |

A bet type can fail `EDGE_THRESHOLDS` (no edge worth flagging) and never reach `BET_FILTERS`, OR clear `EDGE_THRESHOLDS` (edge found) and still be dropped by `BET_FILTERS` (e.g., the edge exists but only on the side/line we've historically lost on).

Both are necessary. Skipping `EDGE_THRESHOLDS` means the pipeline logs every tiny statistical blip; skipping `BET_FILTERS` means you can't act on retrospective analysis without retraining the model.

### Side-string format (the single point of failure for CLV)

Every bet's `side` column must encode direction + line in a parseable way. This is the contract the CLV lookup depends on — the parser extracts `(direction, line, player_name)` from this string and uses it as part of the dedup key. **If the format breaks for any one bet type, CLV silently disappears for that bet type forever.**

Required formats (extend per sport but never break these):

| Bet type pattern | Required `side` format | Example |
|---|---|---|
| Moneyline / first-N ML | direction only | `"home"`, `"away"` |
| Run line / spread | direction + signed handicap | `"home -1.5"`, `"away +2.0"` |
| Totals (game / first-N) | direction + line | `"over 8.5"`, `"under 2.5"` |
| Team totals | side + direction + line | `"home over 4.5"`, `"away under 3.5"` |
| Single-token mainlines | direction enum | `"NRFI"`, `"YRFI"` |
| Player props | full name + direction + line | `"Aaron Judge over 0.5"`, `"Vladimir Guerrero Jr. under 1.5"`, `"Moisés Ballesteros over 0.5"` |

Watch out for: multi-word player names, accented characters, apostrophes (`Ke'Bryan Hayes`), suffixes (`Jr.`, `Sr.`, `III`), and players sharing a last name. The parser walks tokens looking for the `over`/`under` keyword to split name from line — anything before that keyword is treated as the name.

Pin every supported format in a parser test (`test_<bet>_for_clv_parsing.py`). When you add a new bet type, add a parsing test in the same commit.

### Time zone handling (recurring source of bugs)

Two different times matter, and they're in different time zones:

| Concept | Time zone | Format | Why |
|---|---|---|---|
| **Game date** | The sport's local time (US/Eastern for MLB, NBA, NFL; varies for soccer/tennis) | `YYYY-MM-DD` | Matches how the league publishes schedules and how operators talk about "today's slate" |
| **First pitch / commence_time** | UTC | ISO-8601 with `Z` suffix | Matches how every odds/schedule API returns timestamps |

The most common bug: a 23:00 ET game has `commence_time = "2026-04-21T03:00:00Z"`. If you derive its game date from the UTC date (`2026-04-21`), you'll bucket it under tomorrow's slate and either lose it from today's pipeline or double-process it tomorrow. **Always derive game date from the sport's local-time conversion of `commence_time`**, never from the raw UTC date.

In Python:
```python
from datetime import datetime
from zoneinfo import ZoneInfo

LEAGUE_TZ = ZoneInfo("America/New_York")  # parameterize per sport
commence_time = "2026-04-21T03:00:00Z"
fp_utc = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
game_date = fp_utc.astimezone(LEAGUE_TZ).date().isoformat()  # "2026-04-20"
```

Other timezone-related conventions:
- All math (capture window, lead-time-to-first-pitch, "is the game live?") uses UTC.
- All user-facing display (bet card, Discord) uses the league's local time, with the timezone abbreviation (ET / PT) shown.
- Cron schedules in `crontab` / `launchd` run in the host's local time — document that explicitly when shipping a sport repo.

### Multi-channel notification dispatch

Notifications are split across multiple channels (Discord webhooks, Slack channels, etc.) by purpose, not by sport. The baseline pattern:

| Channel | Content | Cadence | Filter |
|---|---|---|---|
| **picks** | New bet alerts, one game at a time as each finishes (see [Priority alerts](#priority-alerts-universal-rule)) | Immediately after each game is analyzed — never batched until the slate is done | `bet_type` whitelist + min edge/Kelly |
| **grades** | Per-bet W/L/P + profit + CLV (when available) | After each grading run | All graded bets in window |
| **summary** | Daily totals: bets, profit, ROI, CLV avg | Once per day after grading | All graded bets for that day |
| **season** | Rolling season totals, broken down by bet type | Once per day after grading | All graded bets season-to-date |

Config shape (`data/alerts_config.json`):
```json
{
  "discord": {"enabled": true, "webhook_url": "${DISCORD_WEBHOOK_URL}"},
  "discord_grades": {"enabled": true, "webhook_url": "${DISCORD_GRADES_WEBHOOK_URL}"},
  "discord_summary": {"enabled": true, "webhook_url": "${DISCORD_SUMMARY_WEBHOOK_URL}"},
  "discord_season": {"enabled": true, "webhook_url": "${DISCORD_SEASON_WEBHOOK_URL}"},
  "bet_types": ["moneyline", "run_line", "total", "nrfi"],
  "min_edge_pct": 0.0,
  "min_kelly_pct": 0.0
}
```

Per-channel dedup logs (`data/notifications_sent.json`, `data/grade_notifications_sent.json`, `data/season_notifications_sent.json`) prevent duplicate sends across pipeline re-runs. Each log is keyed per (date, bet) or per (date, summary-type) — re-running the pipeline never spams.

Webhook URLs live in `.env` (`${DISCORD_WEBHOOK_URL}`-style placeholders in the JSON), never in committed config. The `bet_types` whitelist is the alert filter — keep it tight (mainlines only) to avoid drowning the channel in props. Props get logged but not alerted by default; build a separate "props" channel if you want one.

### Priority alerts (universal rule)

**Status: framework-level. Every sport's daily pipeline must follow it.** Shared implementation: `agents/universal/priority.py`.

The naive pipeline analyzes the whole slate, then alerts once at the end. That's wrong for time-sensitive markets: a 10-game slate run at once doesn't surface its first pick until the slowest game finishes, by which point the earliest games have already started and the alert is useless. The rule fixes both halves:

1. **Priority order** — sort games by first pitch / commence_time, **soonest first**, and feed them to a bounded worker pool in that order. The games closest to starting claim a worker first.
2. **Immediate alerts** — the instant a game's analysis finishes, if it produced any bets, dispatch its alert right then. Never wait for the rest of the slate.

This collapses the old two-phase "screen the whole slate → simulate the whole slate → one batched alert" into a single per-game phase: each game is screened and, only if it clears `SCREEN_EDGE_THRESHOLD`, fully simulated, then alerted — so the expensive ensemble still runs solely on flagged games and **cost is unchanged**.

The universal helper is sport-agnostic — it owns the ordering and the alert-timing; each sport supplies its own per-game work (`process_game`) and alert sender (`send_alert`). Concurrency: games are submitted soonest-first to a thread pool, and results are consumed (and alerts dispatched) on a single thread, so the sport's alert sender never needs to be thread-safe. Per-game alerts lean on the existing `notifications_sent.json` dedup, so an optional end-of-pipeline safety-net sweep can re-call `send_notifications` without ever double-posting.

Wiring (each sport adds the shared `agents/` dir to `sys.path`, since each sport package is its own import root):

```python
import os, sys
_AGENTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../agents
if _AGENTS_ROOT not in sys.path:
    sys.path.append(_AGENTS_ROOT)
from universal.priority import run_priority_pipeline
```

Reference consumers: `baseball-agents/main.py` and `soccer-agents/main.py` (`daily` command). `tennis-agents` predates the helper but already conforms (it time-sorts flagged matches and alerts per match). A sport can only do the *immediate-alert* half once it has a `notify/` module; until then it should at least process the slate soonest-first so the closest games are analyzed first.

### Calibration cap
`apply_calibration(prob, bet_type)` is wired into every edge-detection path (mainlines + props). The current implementation is a hard cap at `SIM_PROB_CAP` (e.g. 0.75) to dampen overconfident model probabilities at the extremes. Replace with isotonic regression once you have ~2 weeks of CLV data per bet type.

### Cost discipline
Paid APIs are gated by cheap pre-checks. Two examples in `close-capture`:
1. Skip if no bets logged for today (no point capturing CLV with no bets).
2. Skip if no game is in the T-5..T-30 capture window (use the free schedule API to check).

The general rule: **never call a paid API without a free pre-check that proves the call is necessary.**

### Schedule timing

Two supported trigger patterns — pick whichever fits the sport's schedule. A sport can also run both (one for the daily-slate launch, one for single-game catch-ups).

**Fixed-lead trigger**. Auto-analyzer fires on a short interval (e.g. every 30 min) and launches the pipeline for any game within N hours of first pitch (a 2h lead is a reasonable default). Works well when a sport's games cluster in a predictable daily window (e.g. a league with games mostly concentrated in a 6-8h slot). See `agents/auto_analyzer.py`.

**Event-driven trigger**. A lightweight tick script fires hourly (via cron/launchd). Each tick:
1. Fetches the schedule across tours/leagues.
2. Finds any game with `commence_time ∈ [now + window_start_h, now + window_end_h]` — e.g. `[7h, 9h]` for an ~8h lead with a 2h tolerance band.
3. Groups games by calendar date; dedup is per-date via `data/pipeline_runs.json` (not per-game).
4. For each date not yet processed, launches the pipeline for that specific date.

Event-driven wins when the sport has a truly global schedule that one fixed-time cron can't catch (e.g. an international tour where events start in very different UTC windows day-to-day). See `scripts/pipeline_tick.py`.

**Grading trigger**. Independent from the pipeline trigger. Fires once daily at a fixed local time (e.g. 04:00 local). Grades strictly `date.today() - 1` and refuses any `game_date >= today` (defense-in-depth: a 2 AM game on today's calendar must not be graded this run — it's picked up tomorrow). See `scripts/grade_tick.py`.

**Grade-tick CLV-first pattern**. Wherever a sport uses post-grade historical-backfill CLV, run operations in this order:
1. Capture closing lines for yesterday's date (historical odds API call).
2. Run the grader (which reads `closing_lines.csv` to populate `close_odds`/`clv_*` columns on each graded bet).
3. Run `clv-apply` to back-fill any bets missed in step 2 (race conditions, late captures).

Doing capture BEFORE grade ensures CLV is available the moment a bet flips W/L, instead of having to re-process the next day. Defense-in-depth via the trailing `clv-apply`.

**Close-capture window** (both trigger patterns). T-5 to T-30 from first pitch. Two capture modes:
- **Live**: cron every 5 min during the day; snapshots the consensus odds at T-5..T-30.
- **Historical backfill**: once-per-day post-grade snapshot via the odds provider's historical endpoint (~1 API credit per match). Simpler — no daemon, no lock file — but captures at a single timestamp rather than a rolling window.

### Cron lifecycle (auto-shutoff + dynamic re-arm)

For sports running operational crons (close-capture, auto-analyzer), they should be active only during the daily game window — not 24/7. The framework pattern is a self-modifying cron that applies **symmetrically** to both crons:

**General pattern**:
1. The script detects an end-of-day condition and emits a distinct shutoff phrase.
2. The cron prompt watches for that phrase and calls `CronDelete` on itself.
3. A separate "morning rearm" cron fires daily at a safe pre-game time and recreates any missing crons.

**Per-cron shutoff conditions**:
- **Close-capture**: `capture_closing_lines` returns `monitoring_complete_for_today: True` when all today's games have started AND no game is in T-5..T-30. CLI prints `"CLV monitoring complete for today — all games have started."`
- **Auto-analyzer**: `_has_future_unanalyzed_games()` returns False when every scheduled game today is either already analyzed OR past first pitch. CLI prints `"auto-analyzer: monitoring complete for today — all games analyzed (or started)."`

**Morning rearm** (one cron, daily, fires at a safe pre-game local time — e.g. 08:05):
- Calls `CronList` to inspect active jobs
- For each operational cron (auto-analyzer, close-capture), if missing AND today has scheduled games: recreates via `CronCreate`
- Idempotent — safe to run when crons already exist (just no-ops them)

This pattern avoids both extremes:
- **Always-on cron** wastes ~250 firings/day during overnight hours (cheap with pre-checks, but noisy in operator logs).
- **Manual re-arm** requires the operator to remember to re-create the cron each morning.

The morning-rearm cron is the only cron that runs 24/7; close-capture is dynamic. The auto-analyzer can use the same pattern if its pipeline-trigger window is bounded to game hours, or stay always-on with free pre-checks guarding paid API calls.

> **Note: this pattern depends on the cron infrastructure supporting self-modification.** Claude Code's session-bound `/loop` and `CronCreate`/`CronDelete` tools provide this. For system `crontab` or `launchd`, the equivalent is a wrapper script that writes/removes the cron entry — see [Persistent scheduling](#persistent-scheduling-launchd--cron) below.

### Persistent scheduling (launchd / cron)

Session-bound crons (Claude's `/loop`, `CronCreate`) die when the session ends. For 24/7 production, use the OS scheduler.

**Baseline pattern** (`scripts/launchd/install.sh` on macOS, `scripts/cron/install.sh` on Linux):
- Each cron job is a `.plist` (macOS) or crontab entry (Linux) under `scripts/launchd/` or `scripts/cron/`.
- An `install.sh` script:
  - Detects the repo path
  - Creates `logs/` directory
  - Unloads any existing matching daemon (idempotent reinstall)
  - Loads each job via `launchctl load -w` or `crontab -`
  - Prints next-fire time and uninstall instructions
- Typical daemons: `com.<sport>.pipeline-tick` (hourly schedule trigger), `com.<sport>.grade-tick` (daily grader at a fixed local time).

**Adoption recommendation**: every sport repo should ship an install script. The framework treats persistence as a sport-repo concern, not a framework concern — but the install script is a tiny piece of operational tooling that belongs in every sport.

### Dedup keys
- Bets: `(date, game, bet_type, side)` — prevents pipeline re-runs from double-logging.
- Closing lines: `(date, game, market, side, line, player_name)` — empty `player_name` for mainlines, set for props.
- Notifications: `bet_key` per `(date, bet)`.
- Analyzed games: `(date, game)` — only the latest status per game per day.

### Same-day repeated matchups
Any sport where the same two teams/players can meet twice on the same calendar date (e.g. doubleheaders, tournament formats with multiple legs) needs the closing-line matcher to disambiguate by `commence_time`, not by `(team_a, team_b)` alone. The historical-odds endpoint returns each game under a distinct `event_id`; use a list keyed on commence-time proximity, not a `(away, home) → event` dict.

---

## How to instantiate the framework (or retrofit an existing sport repo)

1. **Adapter layer** (sport-specific):
   - `scrapers/schedule.py`: `get_probable_starters(date) → list[{game_pk, away_team, home_team, game_date, ...}]`
   - `scrapers/lineups.py`: `get_lineup(game_pk)` if the sport has lineups (baseball/tennis yes; soccer yes for starting XI; UFC no)
   - `scrapers/odds.py`: parameterize the sport key (`baseball_mlb`, `tennis_atp`, etc.) and the markets list

2. **Bet types**:
   - Define the canonical bet types your model produces
   - Decide which are "mainline" vs "props" (mainline ⇒ included in bet card by default)

3. **Simulation**:
   - Build whatever ML/LLM/MC stack fits the sport
   - Output must be a probability per (game, bet_type, side) — that's all `edge.py` needs

4. **Reuse the framework shells**:
   - The 6-step `daily` pipeline structure
   - `BET_FILTERS` config + `_passes_bet_filter`
   - `apply_calibration`
   - Closing-lines capture + backfill (just point at the right sport key)
   - Auto-analyzer (parametric on the sport's schedule source)
   - Analyzed-games state (already sport-agnostic)
   - Bet card (sport-agnostic, just pulls from bets.csv)
   - Grader (sport-agnostic shell; result-determination is sport-specific)

5. **Configure**:
   - `alerts_config.json` for the alert channels + bet_type whitelist
   - `EDGE_THRESHOLDS` and `BET_FILTERS` in `config.py`
   - Sport-specific calibration tuning

---

## The iteration loop

These seven steps are **the baseline feedback cycle**. Other sports may add steps (e.g., per-week model retraining, parlay simulation, line-shopping across multiple books) or simplify (e.g., skip CLV for sports where closing-line markets are too thin). Treat the loop as a starting cadence, not a fixed protocol.

The framework's value compounds via this loop:

1. **Log every bet** — no filtering at the source. Anything the model thinks has edge gets logged.
2. **Capture CLV religiously** — this is the one signal you can't fake. Without CLV, you can't tell skill from variance.
3. **Grade daily** — keep `bets.csv` current.
4. **Run analyst agents weekly** — re-evaluate every bet type's CLV-vs-ROI quadrant.
5. **Tune `BET_FILTERS`** — cut bet types/segments with negative CLV; tighten edge thresholds where the model overconfides.
6. **Tighten calibration** — start with the hard cap; graduate to isotonic regression per bet type.
7. **Repeat.**

The four-quadrant decision rule from CLV vs ROI:

| | +CLV | –CLV |
|---|---|---|
| **+ROI** | KEEP / SCALE — real edge, profitable | LUCKY — variance flattering, expect reversion → consider cut |
| **–ROI** | VARIANCE — edge exists, short-term unlucky → keep | CUT — no edge, losing |

---

## Cost model (rough magnitudes)

- **Schedule APIs** (sport leagues' official APIs): free.
- **Odds API** (the-odds-api.com): paid; ~10 credits per region per market for live, more for historical. Pre-checks gate the spend.
- **LLM ensemble** (OpenRouter / Anthropic / OpenAI): ~$0.50–$2.00 per game fully simulated. Screening filter prevents low-EV games from reaching the expensive ensemble.
- **Discord webhooks**: free.

A typical day for one sport: ~$2–10 API + LLM combined, depending on game count and screen pass rate.

---

## Operational checklist (also a gap audit for existing sport repos)

Use this list two ways:
1. **New sport setup** — work top to bottom; check each box as you wire it.
2. **Existing repo audit** — go down the list and ask "do we have this?" for each sport repo. Anything unchecked is a known gap to close (or a deliberate omission to document).

- [ ] `scrapers/<sport>.py` — schedule + lineups
- [ ] `scrapers/odds.py` — points at correct sport key
- [ ] `config.py` — `EDGE_THRESHOLDS` + initial `BET_FILTERS` (start permissive)
- [ ] `calibrate.py` — `SIM_PROB_CAP` set to a reasonable starting value
- [ ] `main.py daily` command — wired to your screening + simulation
- [ ] `agents/daily_runner.py` — health check + grade + pipeline + bet card
- [ ] `agents/analyzed_games.py` — copy as-is (sport-agnostic)
- [ ] `agents/auto_analyzer.py` — copy and update `get_probable_starters` import
- [ ] `agents/bet_card.py` — adapt mainline filter; date-suffixed file output
- [ ] `agents/results_grader.py` — sport-specific result determination
- [ ] `scrapers/closing_lines.py` — copy; parameterize markets per sport
- [ ] `data/alerts_config.json` — Discord webhooks + alert filter
- [ ] Cron / launchd: trigger pattern — **pick one**:
  - Fixed-lead: `auto-analyzer` every 30 min
  - Event-driven: `pipeline_tick` every hour with a 7–9h lookahead window
- [ ] Cron / launchd: `grade_tick` daily at a fixed local time (refuses any `game_date ≥ today`); ideally captures CLV first, grades second, runs `clv-apply` third
- [ ] Cron / launchd: `close-capture` every 5 min **OR** historical backfill once per day from `grade_tick`
- [ ] If running live close-capture: implement auto-shutoff (`monitoring_complete_for_today`) + morning rearm cron so the live cron runs only during the daily game window
- [ ] `scripts/launchd/install.sh` (macOS) or `scripts/cron/install.sh` (Linux) — persistent daemon installer; idempotent; logs directory, unload-before-load, status check

When all of these are in place, the framework runs itself: pipeline triggers when due, CLV captures when relevant, bets are graded the next day, and you have a clean dataset to run analyst agents on.

---

## Open design questions (worth solving once at the framework level)

- **Player blacklists** — some bet types have player-specific blind spots (the model loses CLV on certain stars). A per-bet-type `player_blacklist` filter would generalize cleanly across sports.
- **Per-bet-type calibration** — replacing the global cap with isotonic regression keyed by bet_type.
- **Smart trigger inside close-capture** — if a game with a confirmed lineup has zero bets (was missed by the pipeline window), trigger a single-game pipeline run instead of waiting.
- **Cross-sport cost dashboard** — one place to see API spend per sport per day.
