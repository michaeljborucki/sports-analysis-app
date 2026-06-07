# Player Data Rebuild — Design Spec

**Date**: 2026-04-21
**Status**: Design — not yet implemented
**Replaces**: `docs/sackmann-self-hosted-plan.md` (obsolete — written before we discovered api-tennis exposes serve stats)

## Context

The Jeff Sackmann GitHub data integration was removed 2026-04-21 after months of upstream lag (2025/2026 CSVs never posted) caused:

- Retry storms of ~25 404s per player profile build
- 5-8 min wasted per pipeline run
- Silently stale predictions (Elo/form frozen at 2024-12-18)

`scrapers/players.py` is currently a stub — `get_player_profile()` and `get_head_to_head()` return shape-correct dicts with all fields set to `"N/A"`. The LLM ensemble's Phase 3 challenger now correctly flags every prediction as "speculation from zero data" and kills most bets.

We need to restore the data layer. **A probe during this brainstorm discovered that `api-tennis.com` already exposes full match serve statistics** via its `get_fixtures` endpoint (every finished match has a `statistics` field with aces, 1st/2nd serve %, break points, etc.). This collapses what was going to be a multi-source integration into a single-source rebuild.

## Goal

Restore `scrapers/players.py` to produce populated player profiles (Elo, records, serve/return stats, recent form, H2H) by combining:

1. **Sackmann 2020-2024 archive** — kept locally as the canonical historical record (for Elo warmup and deep H2H)
2. **`api-tennis` `get_fixtures`** — for 2025+ matches, including serve stats

All via one external API we already use. No paid APIs, no scraping, no second data source.

## Success criteria

- Daily pipeline produces briefings with **populated** serve stats, return stats, Elo, records, recent form, and H2H for post-2020 matches
- Zero `ERROR` log lines from data fetching (no 404 retry storms)
- Pipeline health check passes without depending on `github.com/JeffSackmann/*` being alive
- Re-running the backfill is idempotent (no duplicate rows)
- Restoring on a fresh clone takes one command (`bootstrap_player_data.sh`)
- Challenger no longer flags "no data available" as a kill reason (but may still kill for other legitimate flaws)

## Architecture

```
 ┌────────────────────────────────────────────────────────┐
 │                   data/sackmann/                       │
 │  ┌──────────┐         ┌──────────┐                     │
 │  │   atp/   │         │   wta/   │                     │
 │  │  2020    │         │  2020    │                     │
 │  │  2021    │         │  2021    │                     │
 │  │  2022    │         │  2022    │    ← historical,   │
 │  │  2023    │         │  2023    │      read-only      │
 │  │  2024    │         │  2024    │      (Sackmann)     │
 │  │  -----   │         │  -----   │                     │
 │  │  2025    │         │  2025    │    ← backfilled +   │
 │  │  2026    │         │  2026    │      appended       │
 │  │ players  │         │ players  │      (api-tennis)   │
 │  │ rankings │         │ rankings │                     │
 │  └──────────┘         └──────────┘                     │
 └────────────────────────────────────────────────────────┘
        ▲                      ▲
        │                      │
        │ read                 │ append
        │                      │
 ┌──────────────┐      ┌────────────────┐
 │ players.py   │      │ sackmann_sync. │
 │ (un-stubbed) │      │ py (new)       │
 │              │      │                │
 │ Elo, records │      │ sync_matches_  │
 │ serve/return │      │   day()        │
 │ H2H, form    │      │ sync_rankings()│
 └──────────────┘      │ _ensure_player │
                       └────────────────┘
                              ▲
                              │ fetches via
                              │
                       ┌────────────────┐
                       │ api-tennis.com │
                       │  get_fixtures  │
                       │  get_standings │
                       │  get_players   │
                       └────────────────┘
```

**One data source (api-tennis), one local archive (data/sackmann/), one reader (players.py).**

## Components

### 1. `scrapers/players.py` — un-stub + restore math

Restores the Sackmann-era math (Elo, `_calc_serve_stats`, `_calc_return_stats`, `_calc_record`, `_recent_form`, `get_head_to_head`) from the prior implementation. Changes from the prior implementation:

- **`_fetch_csv` reads local-only.** No GitHub URL. If a file is missing, returns `[]` and logs a single warning. No retries.
- **Elo still iterates years 2020 → current.** The appended 2025/2026 CSVs are read as-is — same schema, so the math is unchanged.
- **Serve stats gracefully handle missing fields.** If `w_ace` etc. are blank (shouldn't happen for 2025+ but might for 2020-2024 edge rows), the helper returns "N/A" for that entry (existing behavior).

### 2. `scrapers/sackmann_sync.py` — new, appends api-tennis data

Three functions:

#### `sync_matches_day(game_date: str, tour: str) -> int`

- Calls `api-tennis get_fixtures` for `date_start=date_stop=game_date`
- Filters to `event_status == "Finished"` and `event_type_type` matching `tour` (`Atp Singles` / `Wta Singles`)
- For each match:
  - Build a row conforming to Sackmann's 46-column CSV schema
  - Call `_ensure_player()` for winner + loser (lazy `get_players` lookup if unknown)
  - Aggregate the `statistics` field into match-level serve/return counts (see Stats Aggregation below)
  - Append to `data/sackmann/{tour}/{tour}_matches_{year}.csv`, creating the file with Sackmann header if missing
- Deduplicates by `(tourney_id, match_num)` before writing — safe to rerun
- Returns count of new rows written

#### `sync_rankings(tour: str) -> int`

- Calls `api-tennis get_standings?event_type={tour}`
- Overwrites `data/sackmann/{tour}/{tour}_rankings_current.csv` with columns `ranking_date, rank, player, points`
- `ranking_date` is today (YYYYMMDD format)
- Single API call, ~2200 rows per tour

#### `_ensure_player(player_key: int, tour: str) -> dict`

- Looks up `player_key` in local `{tour}_players.csv`
- If not found, calls `api-tennis get_players?player_key=N`, appends the row with whatever fields api-tennis provides (hand, country, age, dob) + Sackmann schema columns blank for what's missing
- Returns the player row (either existing or newly-fetched)
- Cached in memory within a single pipeline run to avoid repeat lookups for the same player across matches

### Stats Aggregation (subsection)

api-tennis returns stats as **per-set running totals** (discovered during brainstorm probe — same stat repeated once per set, values reflect running totals through that set). To get match-final stats:

1. Group stats by `(player_key, stat_type, stat_name)`
2. Take the LAST entry (highest set index) as the match-final value
3. Convert percentage strings ("51%") to floats (0.51)
4. Map into Sackmann column names:
   - Raw counts (Aces, Double Faults): direct copy
   - Percentages: stored as floats in dedicated columns (see schema section) — downstream Sackmann math is updated to consume percentages directly rather than back-computing from svpt/1stIn counts

**Open implementation detail**: verify the "last entry = match-final" assumption against 2-3 known matches during implementation. If it's wrong, fall back to summing raw counts and averaging percentages weighted by points played.

### 3. `scrapers/players.py` serve-stats refactor

The existing `_calc_serve_stats` and `_calc_return_stats` compute percentages from raw counts (`w_1stIn / w_svpt` etc.). Since api-tennis gives us percentages directly, we extend the schema with pre-computed percentage columns:

| New Sackmann column | Source |
|---|---|
| `w_1stSvPct` / `l_1stSvPct` | api-tennis "1st serve percentage" |
| `w_1stWonPct` / `l_1stWonPct` | api-tennis "1st serve points won" |
| `w_2ndWonPct` / `l_2ndWonPct` | api-tennis "2nd serve points won" |
| `w_bpSavedPct` / `l_bpSavedPct` | api-tennis "Break Points Saved" |
| `w_retPtsWonPct` / `l_retPtsWonPct` | api-tennis "Return Points Won" |
| `w_bpConvPct` / `l_bpConvPct` | api-tennis "Break Points Converted" |

Historical 2020-2024 rows have blanks in these new columns — `_calc_serve_stats` falls back to computing from `w_svpt` / `w_1stIn` etc. (existing behavior). 2025+ rows use the pre-computed values directly. Both paths return the same output shape to `briefing.py`.

### 4. `scripts/bootstrap_player_data.sh` — new, one-time setup

For fresh clones. Checks if `data/sackmann/atp/atp_matches_2024.csv` exists:

- If yes: exit 0 (already bootstrapped).
- If no: download Sackmann's 2020-2024 files from github.com/JeffSackmann/tennis_atp and tennis_wta. Fail loudly if GitHub is unreachable (future-proof: if Sackmann's repos disappear, we publish a tarball as a GitHub release of this repo and the script falls back to that).

Runs in < 30 sec on a cold clone.

### 5. `scripts/backfill_player_data.py` — new, one-time 2025+ backfill

Loops over dates from 2025-01-01 through yesterday:

- For each date, calls `sync_matches_day(date, "atp")` and `sync_matches_day(date, "wta")`
- Rate-limited (~0.5 sec between calls) to not hammer api-tennis
- Idempotent — safe to rerun if interrupted
- Estimated runtime: ~475 days × 2 tours × 0.6 sec/call = ~10 min
- API credit cost: ~950 calls

Accepts `--start`, `--end`, `--tour` flags for targeted re-runs.

### 6. `agents/daily_runner.py` — add sync step

New step inserted BEFORE grading yesterday:

```
[1] Health check
[1.5] sync_matches_day(yesterday, "atp") and ("wta")   ← NEW
[1.6] sync_rankings(tour) if Monday OR file_age > 7d   ← NEW
[2]  Grade yesterday
[3]  Run today's pipeline
[4]  Bet card
```

If sync fails, log a warning but continue — the pipeline should still run with whatever's in the local CSVs. A missed sync just means today's Elo is slightly stale; tomorrow's run catches up (idempotent).

### 7. `agents/health_check.py` — archive presence check

Add a check that `data/sackmann/atp/atp_matches_2024.csv` and `wta/wta_matches_2024.csv` exist on disk. If missing, prints "Run scripts/bootstrap_player_data.sh" — critical check.

## Data flow

### Daily run (normal)

1. `daily_runner` starts, runs health check (validates local archive exists)
2. `sync_matches_day(yesterday, "atp")` — fetches yesterday's ATP fixtures, appends new finished matches to `atp_matches_2026.csv`
3. Same for WTA
4. Conditionally: `sync_rankings()` if Monday or >7d stale
5. Grader proceeds (unchanged)
6. Pipeline proceeds (unchanged) — `get_player_profile` now reads the fresh appended CSV, produces a populated briefing
7. LLM ensemble sees real serve stats, Elo, H2H → makes informed predictions → challenger approves more bets

### Bootstrap (fresh clone)

1. User clones the repo
2. `scripts/bootstrap_player_data.sh` downloads Sackmann 2020-2024 snapshot
3. `scripts/backfill_player_data.py` runs ~10 min to populate 2025-2026
4. `python3 main.py health` confirms everything is in place
5. Daily pipeline works from day one

### Backfill reprocess (corruption recovery)

1. `rm data/sackmann/atp/atp_matches_2025.csv data/sackmann/wta/wta_matches_2025.csv` (etc.)
2. `python3 scripts/backfill_player_data.py --start 2025-01-01 --end 2026-01-01`
3. Re-run any dates that had issues
4. Idempotency via `(tourney_id, match_num)` dedup ensures no duplicates

## Error handling

| Failure | Behavior |
|---|---|
| api-tennis unreachable during sync | Log warning, skip the sync, continue pipeline. Next day's sync catches up. |
| `get_fixtures` returns empty for a day | Normal (no matches that day). Write nothing. No error. |
| Statistics field missing on a finished match | Write match row with blank serve-stats columns. Log INFO with event_key. No error. |
| Unknown player_key in fixtures | Lazy-fetch via `get_players`. If that also fails, write a partial row with name from fixture, other fields blank. |
| Rate limit hit (429) | Exponential backoff: 5s, 15s, 45s. After 3 failures, give up that call with a warning. |
| CSV file lock/concurrent write | Not a concern — daily_runner is single-threaded and the sync functions complete before pipeline starts. |
| Corrupt row in local CSV | Reader (`_fetch_csv`) uses `csv.DictReader` which tolerates row-level issues. Bad rows degrade that specific player's data; rest of pipeline continues. |

## Testing strategy

### New file: `tests/test_sackmann_sync.py`

- **Schema conformance**: every row appended has all 46 Sackmann columns + the 12 new percentage columns. Column order matches existing 2024 header exactly.
- **Dedup idempotency**: calling `sync_matches_day("2026-04-20", "atp")` twice produces exactly one new row per match (not two).
- **Stats aggregation**: given a mocked fixture with per-set statistics entries, the aggregation picks the LAST entry per `(player, stat_type, stat_name)` and converts percentage strings correctly.
- **Lazy player lookup**: unknown `player_key` triggers one `get_players` call, and the resulting row is appended to the players CSV.
- **Missing statistics graceful**: fixture with `statistics=[]` still produces a match row (stats columns blank).
- **Rankings sync**: overwrites the current file, preserves header, writes today's date.

### Regression updates

- `tests/test_players.py` grows back from stub tests to cover Elo/record/form against the restored implementation. Keep the stub tests as guard against accidental re-removal.
- `tests/test_regression_briefing.py` golden file updates — briefings now have populated fields instead of N/A. Once the change lands, regenerate the golden once and commit.

## Migration / rollout

1. Merge the un-stub + sync module + bootstrap + backfill scripts together (single commit or PR)
2. Run `scripts/bootstrap_player_data.sh` on the dev machine (local copy already present, will no-op)
3. Run `scripts/backfill_player_data.py --start 2025-01-01` (~10 min, populates 2025 + 2026 YTD)
4. Run `python3 main.py health` to validate archive state
5. Run `python3 -m agents.daily_runner` as a full-stack smoke test
6. Observe: bet card populated, challenger kill rate drops, Plan B fallback rate drops

Rollback: revert the commit, re-stub `scrapers/players.py`. The `data/sackmann/` archive stays — it's gitignored, not committed. No data loss.

## Scope boundaries — what this does NOT do

- Does not add any new external dependencies (no paid API, no new scrapers)
- Does not rewrite Elo, H2H, or briefing math — preserves existing logic
- Does not commit `data/sackmann/` to git (stays ignored; regenerated via bootstrap + backfill)
- Does not address the separate "injuries feed" gap (INVESTIGATE_LATER item 6)
- Does not handle ITF / challengers / juniors beyond what api-tennis returns for finished fixtures
- Does not provide real-time in-match data (only finished matches)

## Decisions locked in

| Decision | Chosen | Rationale |
|---|---|---|
| Primary data source | api-tennis | Already in use, exposes everything we need (discovered during brainstorm) |
| Historical archive | Sackmann 2020-2024 local snapshot | Already on disk; covers Elo warmup period |
| Backfill scope | Full 2025 + 2026 YTD | User requested; achievable in ~10 min |
| Daily appending | `sync_matches_day(yesterday, ...)` in `daily_runner` | Idempotent, low-overhead, catches missed days |
| Rankings cadence | Weekly (Monday) OR file-age > 7d | Rankings refresh weekly on tour; daily fetches wasted |
| Commit `data/sackmann/` to git? | **NO** — gitignored + bootstrap script | Repo bloat + merge noise from daily appends; data is reconstructable |
| Serve-stats source | api-tennis `statistics` field | Confirmed in probe; no second source needed |
| Stats aggregation | Last entry per (player, stat_name) | Per-set running totals → last = match-final |

## Open items (deferred to implementation)

1. **Verify "last entry = match-final" stats interpretation** against 2-3 known 2025 matches before trusting the aggregation. If wrong, fall back to summing raw counts + averaging percentages.
2. **Monitor api-tennis rate limit behavior** during backfill. If we hit 429s, introduce concurrent fetches with a semaphore rather than purely serial.
3. **Briefing golden file regeneration** — the regression test will fail after this lands until the golden is updated with populated stats. Capture the expected new output during the first smoke-test run.
