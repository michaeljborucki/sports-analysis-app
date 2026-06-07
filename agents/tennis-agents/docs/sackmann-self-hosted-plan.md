# Self-Hosted Sackmann Data Plan

## Context

Jeff Sackmann's `tennis_atp` and `tennis_wta` GitHub repos have not been updated
since the 2024 season ended. The latest season files are
`atp_matches_2024.csv` and `wta_matches_2024.csv` (complete through
2024-12-18). No 2025 or 2026 files exist upstream.

Our pipeline pulls these CSVs to compute season records, recent form,
serve/return stats, Elo ratings, and head-to-head. Without 2025-2026 data,
Elo is frozen at 2024-12-18, current-season records and form are empty, and
H2H is missing all recent meetings. Ensemble picks are being made on
16+ month-stale player data.

The pipeline currently hits GitHub every run and logs ~25 ERROR lines per
run from the 2025/2026 404s.

## Goal

Take Sackmann's existing 2024-and-earlier archive as a one-time snapshot,
declare it canonical inside this repo, and extend it ourselves as new matches
complete. Stop depending on the upstream GitHub repo entirely.

## Current state of the local mirror

`data/sackmann/` already contains cached copies of everything we need:

```
data/sackmann/
  atp/
    atp_matches_2020.csv ... atp_matches_2024.csv
    atp_players.csv
    atp_rankings_current.csv
  wta/
    wta_matches_2020.csv ... wta_matches_2024.csv
    wta_players.csv
    wta_rankings_current.csv
```

These were cached by `scrapers/players._fetch_csv` during normal runs. They
are identical to Sackmann's canonical files. The snapshot is already local —
we just need to treat it as authoritative instead of "cache."

## Architecture

### 1. Declare local files canonical

**File:** `scrapers/players.py`

Rewrite `_fetch_csv` to read only from `data/sackmann/{tour}/{filename}`.
Remove GitHub fetching. If a file is missing, return `[]` and log a single
warning (not an error). This eliminates 404 noise, removes upstream
dependency, and makes the pipeline fully offline-capable for player data.

### 2. Daily match appender

**New file:** `scrapers/sackmann_sync.py`

Function: `sync_matches_day(game_date: str, tour: str) -> int`

- Call `get_fixtures` on api-tennis for that date
- Filter to singles matches with `event_status == "Finished"`
- For each match, emit a row in Sackmann's exact 46-column schema
- Append to `data/sackmann/{tour}/{tour}_matches_{year}.csv`, creating the
  file with the Sackmann header if it doesn't exist
- Deduplicate by `(tourney_id, match_num)` so reruns are idempotent

**Column mapping (api-tennis → Sackmann):**

| Sackmann column | Source |
|---|---|
| `tourney_id` | `tournament_key` |
| `tourney_name` | `tournament_name` |
| `surface` | cached `get_tournaments` join on `tournament_key` → `tournament_sourface` |
| `draw_size` | blank (not provided) |
| `tourney_level` | inferred from `event_type_type` (`Atp Singles` → `A`, Grand Slam → `G`, etc.) |
| `tourney_date` | `event_date` reformatted to `YYYYMMDD` |
| `match_num` | `event_key` |
| `winner_name` / `loser_name` | derived from `event_winner` ("First Player"/"Second Player") + `event_first_player` / `event_second_player` |
| `winner_id` / `loser_id` | `first_player_key` / `second_player_key` |
| `winner_hand` / `_ht` / `_ioc` / `_age` | lookup from local `{tour}_players.csv` by id |
| `score` | reconstructed from `pointbypoint` — final game score per set joined by spaces, e.g. `"3-6 6-2 6-2"` |
| `best_of` | inferred from set count (≥3 sets won → best_of=5, else 3) |
| `round` | `tournament_round` (strip tournament prefix) |
| `minutes` | blank |
| `w_ace` / `w_df` / `w_svpt` / `w_1stIn` / `w_1stWon` / `w_2ndWon` / `w_SvGms` / `w_bpSaved` / `w_bpFaced` | **blank — api-tennis does not expose serve stats** |
| same for `l_*` | blank |
| `winner_rank` / `_rank_points` | lookup from local rankings file |
| `loser_rank` / `_rank_points` | same |

**Impact of blank serve stats:** `_calc_serve_stats` and `_calc_return_stats`
already return "N/A" on missing data. Records, recent form, Elo, and H2H
all still work correctly for 2025+ matches. Briefings lose ace rate / 1st
serve % etc. for current-season players (degradation already present today).

### 3. Weekly rankings refresh

**File:** `scrapers/sackmann_sync.py`

Function: `sync_rankings(tour: str) -> int`

- Call `get_standings?event_type={tour}` (atp or wta)
- Overwrite `data/sackmann/{tour}/{tour}_rankings_current.csv` with columns
  `ranking_date,rank,player,points` (WTA adds `tours` — leave blank)
- Use today's date in YYYYMMDD for `ranking_date`
- ~2200 rows per tour, single API call

Schedule: run once per Monday from `daily_runner` (gated by weekday check)
or hit it on every daily run (cheap).

### 4. Players file (passive growth)

Sackmann's 2024 `{tour}_players.csv` is kept as-is. New player_keys that
appear in `get_fixtures` but aren't in the file trigger a lazy
`get_players?player_key=N` lookup, and the resulting row is appended.

**Function:** `_ensure_player(player_key: int, tour: str)` — called by
`sync_matches_day` for every winner/loser it encounters.

### 5. One-time 2025 backfill

**New script:** `scripts/backfill_sackmann.py`

- Loops over every date from 2025-01-01 through yesterday
- Calls `sync_matches_day(date, "atp")` and `sync_matches_day(date, "wta")`
  for each day
- ~470 days × 2 tours = ~940 API calls; rate-limited by api-tennis plan
- Idempotent (dedupe on `(tourney_id, match_num)`), so safe to rerun

**Alternative:** Skip backfill, start clean from today. Accept that Elo
and records stay stale until enough 2026 data accumulates.

## File changes

| File | Change |
|---|---|
| `scrapers/players.py` | `_fetch_csv` reads local-only; remove GitHub URL logic |
| `scrapers/sackmann_sync.py` | **new** — `sync_matches_day`, `sync_rankings`, `_ensure_player` |
| `agents/daily_runner.py` | call `sync_matches_day` after grading yesterday; call `sync_rankings` once per week |
| `scripts/backfill_sackmann.py` | **new** — one-time backfill |
| `tests/test_sackmann_sync.py` | **new** — schema conformance, dedup, lazy player lookup |
| `.gitignore` or commit | decision pending: do we commit `data/sackmann/` to git? |
| `config.py` | remove `sackmann_repo` URLs (no longer used) |

## Open decisions

1. **Backfill scope?** Full 2025 / 2026-only / skip entirely
2. **Commit `data/sackmann/` to git?** ~30-50MB of CSVs. Pros: version-controlled, backed up, easy bootstrap. Cons: repo size bloat, merge noise on appends. Alternative: keep in `.gitignore`, ship a bootstrap script that re-pulls from `github.com/JeffSackmann/*` one time (works while his repos exist).
3. **Serve-stats gap?** Leave blank forever / revisit later with a second source (SportsRadar, tour-site scrape) / approximate from `pointbypoint`
4. **Rankings cadence?** Every run (cheap, always fresh) vs weekly (lower API usage)

## Verification

- Unit: `tests/test_sackmann_sync.py` covers schema shape, deduplication,
  surface join, player lazy-load
- Integration: after implementing, run
  `python3 scripts/backfill_sackmann.py --start 2026-04-01 --end 2026-04-18`
  and spot-check a few matches against official ATP/WTA pages
- Regression: `python3 main.py health && python3 -m agents.daily_runner`
  — pipeline should complete with zero Sackmann ERROR lines in the log
- Feature check: after backfill, briefings for players with 2026 matches
  should show non-empty `season_record` and `recent_form`; Elo should
  differ from the frozen-2024 value
