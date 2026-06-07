# Parallel Game Processing

**Date:** 2026-03-22
**Status:** Approved
**Problem:** The daily pipeline processes games sequentially. On days with 15-16 games (e.g., Spring Training), the 1-hour subprocess timeout is hit before all games can be screened and simulated.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Concurrency model | `ThreadPoolExecutor` | Minimal diff, matches existing ensemble pattern, I/O-bound workload |
| Concurrency level | Configurable `PARALLEL_GAMES`, default 4 | Safe starting point, avoids OpenRouter rate limiting |
| Per-game timeout | `future.result(timeout=GAME_TIMEOUT)` | Replaces `signal.SIGALRM` which is process-global and incompatible with threads |
| Output style | Hybrid — one-liner per completion + summary table | Real-time progress without interleaved output |
| Parallelized phases | Both screening (Step 5) and simulation (Step 6) | Covers 95% of wall-clock savings |

## Architecture

### Current Flow (Sequential)
```
Steps 1-4: Fetch schedule, odds, lineups, injuries (shared data, runs once)
Step 5: FOR each game (sequential):
          build briefing → screen (LLM) → edge check → flag if edge ≥ 3%
Step 6: FOR each flagged game (sequential):
          ensemble sim (3 runs × 6 models) → edge check → log bets → MC props
```

### New Flow (Parallel)
```
Steps 1-4: Unchanged (shared data, runs once)
Step 5: ThreadPoolExecutor(max_workers=PARALLEL_GAMES):
          submit _screen_game() for each game
          as_completed: print one-liner, collect flagged games
          print summary table
Step 6: ThreadPoolExecutor(max_workers=PARALLEL_GAMES):
          submit _simulate_game() for each flagged game
          as_completed: print bet lines
          print summary
```

## Changes By File

### config.py
Add one constant:
```python
PARALLEL_GAMES = 4  # max games processed concurrently (screen + sim)
```

### main.py

**Remove:**
- All `signal.SIGALRM` / `signal.alarm()` usage and associated `try/finally` blocks in Steps 5 and 6
- Import of `signal` module
- `GameTimeout` exception class and `_timeout_handler`

**Add:**
- Import `concurrent.futures.ThreadPoolExecutor, as_completed`
- Import `PARALLEL_GAMES` from config

**Extract `_screen_game(game, odds_by_teams, injuries_by_team, lineups, game_date)`:**
- Contains the per-game logic currently in the Step 5 loop body
- Builds pitcher profiles, team profiles, environment, briefing
- Calls `run_plan_b()` and `analyze_all_edges()`
- Returns `(game_key, brief, game_data, max_edge)` on success, `None` on failure
- No printing (existing `click.echo` calls removed), no signal handling — pure function
- All progress reporting happens in the main thread via `as_completed`

**Extract `_simulate_game(game_key, brief, game_data, game_date)`:**
- Contains the per-game logic currently in the Step 6 loop body
- Calls `run_mirofish()`, `analyze_all_edges()`, `log_bet()`
- Runs Monte Carlo prop simulation if lineups confirmed
- Returns `(game_key, bets_list, result_dict)` — `result_dict` includes `ensemble_meta` with `cost_usd` for cost aggregation in the main thread
- `log_bet()` calls are thread-safe via lock (see tracker.py below)

**Replace Step 5 loop:**
```python
with ThreadPoolExecutor(max_workers=PARALLEL_GAMES) as pool:
    futures = {
        pool.submit(_screen_game, game, odds_by_teams, ...): game
        for game in games_with_odds
    }
    for future in as_completed(futures):
        try:
            result = future.result(timeout=GAME_TIMEOUT)
            # print one-liner, collect flagged
        except TimeoutError:
            # print timeout
        except Exception as e:
            # print error
# print summary table
```

**Replace Step 6 loop:** Same `ThreadPoolExecutor` + `as_completed` pattern.

### tracker.py

Add thread-safety to CSV operations. Lock must encompass `_ensure_csv()` to prevent TOCTOU race on first run:
```python
import threading

_csv_lock = threading.Lock()

def log_bet(bet, csv_path=None):
    csv_path = csv_path or BETS_CSV
    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")
    with _csv_lock:
        _ensure_csv(csv_path)
        df = pd.read_csv(csv_path)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(csv_path, index=False)

def update_result(game, bet_date, result, profit, csv_path=None):
    with _csv_lock:
        # ... existing read-modify-write ...
```

Note: `update_result` is only called from `results_grader` (a separate CLI command), not during the daily pipeline, so the index-based addressing is safe.

### scrapers/player_stats.py

Add thread-safety to player map cache. Lock only around cache read/write, **not** around API calls, to avoid serializing network I/O:
```python
import threading

_player_map_lock = threading.Lock()

def resolve_player(name, season=None):
    with _player_map_lock:
        mapping = _load_player_map()
        if name in mapping:
            return mapping[name]

    # API call outside the lock (may take seconds)
    pid = _api_lookup(name, season)

    with _player_map_lock:
        mapping = _load_player_map()  # re-read to avoid lost updates
        mapping[name] = pid
        _save_player_map(mapping)
    return pid
```

Also: `UNMATCHED_LOG` file append should be folded under the same lock (or use a separate lock) to prevent interleaved writes.

### ensemble/logger.py

Add thread-safety to prediction logging:
```python
import threading

_log_lock = threading.Lock()

def log_model_prediction(...):
    with _log_lock:
        # ... existing CSV append ...
```

### ensemble/weights.py

Add thread-safety to weight initialization (race on first load when file doesn't exist):
```python
import threading

_weights_lock = threading.Lock()

def load_weights(path=None):
    with _weights_lock:
        # ... existing load, with save_weights() on first init ...
```

### ensemble/orchestrator.py

Replace `print()` call (line 373) with `logger.error()` to prevent interleaved output under threading.

## Thread-Safety Analysis

| Resource | Protection | Deadlock Risk |
|----------|-----------|---------------|
| `data/bets.csv` | `tracker._csv_lock` | None — single lock, no nesting |
| `data/player_map.json` | `player_stats._player_map_lock` | None — single lock, no nesting |
| `data/unmatched_players.log` | `player_stats._player_map_lock` | None — same lock as player_map |
| `data/model_predictions.csv` | `logger._log_lock` | None — single lock, no nesting |
| `data/model_weights.json` | `weights._weights_lock` | None — single lock, no nesting |
| OpenRouter API | HTTP-level timeouts + retry | N/A |
| Shared dicts (odds, injuries) | Read-only after Steps 1-4 | N/A |

No lock is ever acquired while holding another lock. No deadlock is possible.

## Performance Expectations

| Scenario | Sequential (current) | Parallel (PARALLEL_GAMES=4) |
|----------|---------------------|----------------------------|
| 16 games, 4 flagged | ~80 min (timeout) | ~20 min screening + ~10 min sim |
| 8 games, 2 flagged | ~30 min | ~10 min screening + ~5 min sim |
| 4 games, 1 flagged | ~15 min | ~5 min |

Estimates assume ~2 min per game for screening (LLM call + scrapers) and ~5 min per flagged game for full simulation.

## Risk Mitigation

- **OpenRouter rate limiting:** Default `PARALLEL_GAMES=4` keeps concurrent API calls manageable (max 24 during simulation). Configurable to reduce if rate-limited.
- **Lingering threads after timeout:** `future.result(timeout=...)` stops waiting but can't kill the thread. The thread will eventually return when its HTTP call times out. The outer 1-hour subprocess timeout in `daily_runner.py` is the hard backstop.
- **Output interleaving:** Each `click.echo()` call is a single line printed atomically. No multi-line output from worker threads — all printing happens in the main thread via `as_completed`.

## Not In Scope

- Parallelizing Steps 1-4 (scrapers run once for all games, already fast)
- Async rewrite (disproportionate effort for the gain)
- Changing `daily_runner.py` subprocess timeout (orthogonal concern)
