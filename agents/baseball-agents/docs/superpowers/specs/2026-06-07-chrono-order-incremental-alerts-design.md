# Chronological Game Ordering + Incremental Per-Game Alerts

**Date:** 2026-06-07
**Status:** Approved

## Problem

The daily pipeline (`main.py daily`) processes games in MLB API order and sends
Discord bet alerts once, after every flagged game has finished simulating. A
full slate takes ~90 minutes, so picks for a game starting in 20 minutes can
arrive after first pitch while the run grinds through games that start hours
later.

## Goals

1. Analyze games in chronological start-time order, so the soonest games are
   screened and simulated first.
2. Send Discord alerts for each game as soon as that game's analysis completes,
   instead of batching all alerts at the end of the run.

## Non-goals

- No changes to `notify/dispatch.py`, message formatting, grading, or channel
  routing.
- No deadline-aware scheduling or dynamic reprioritization (priority queues,
  worker preemption).
- No suppression or tagging of alerts for games that have already started —
  alerts always send when analysis completes (user decision).

## Design

### 1. Chronological ordering

Two sort points in `main.py`, both using the same key:

```python
def _chrono_key(time_str: str) -> tuple:
    return (time_str == "", time_str)  # blanks last, then ISO-8601 lexicographic
```

- **Step 1 output:** after `games = get_probable_starters(game_date)`
  (main.py:276), sort `games` by `_chrono_key(game.get("game_date", ""))`.
  ISO-8601 UTC strings sort lexicographically, which equals chronological
  order. This fixes submission order for Step 5 screening.
- **Step 6 input:** Step 5 collects results via `as_completed()`, which returns
  them in completion order — so the flagged list must be re-sorted. Before
  submitting to the Step 6 pool (main.py:438), sort `screened_games` by
  `_chrono_key(game_data.get("game_time_utc", ""))`.

The two call sites read different dict keys (`game["game_date"]` in Step 1,
`game_data["game_time_utc"]` in Step 6), but both derive from the same MLB API
`gameDate` value (copied at screen time, main.py:134), so the orders cannot
diverge.

With `PARALLEL_GAMES` workers (currently 4), submission order = start order,
so the soonest games are always in flight first in both steps.

### 2. Incremental per-game alerts

In the Step 6 `as_completed` loop (main.py:443-463), after each game's result
is collected, call:

```python
if not no_notify:
    try:
        send_notifications(game_date=game_date)
    except Exception:
        logger.warning("Per-game notification dispatch failed for %s", game_key,
                       exc_info=True)
```

Why this is safe and sufficient:

- Each game's bets are already on disk when its future resolves — `log_bet()`
  runs inside `_simulate_game()` in the worker thread.
- `send_notifications()` is idempotent: it loads all bets for the date, then
  drops anything already in the sent-log (`data/notifications_sent.json`).
  Each per-game call therefore alerts only the bets newly logged since the
  previous call — at most one alert message per completed game, and a no-op
  for games that produced no new bets (it returns `bets_new: 0` and sends
  nothing; do not force a message in that case).
- Calls happen on the main thread only (inside the `as_completed` loop), so
  the read-filter-send-record sequence is never concurrent with itself.
- The existing end-of-run `send_notifications` call (main.py:470-480) stays as
  a catch-all. Normally a no-op; it retries any per-game dispatch that failed
  (failed sends never enter the sent-log) and picks up stragglers.

### Error handling

A Discord/network failure during a per-game dispatch logs a warning and the
pipeline continues; the end-of-run catch-all retries. No new failure modes for
the simulation path.

## Testing

- **Ordering:** unit tests that games with mixed and blank `game_time_utc`
  values sort chronologically with blanks last — for both the Step 5 input
  list and the Step 6 flagged list.
- **Incremental dispatch:** unit tests (mocking `send_notifications`) that it
  is called once per completed game in the Step 6 loop; that an exception from
  it does not abort remaining games; and that `no_notify` suppresses the
  per-game calls.
- **Idempotency:** already covered by existing notify dedup tests; no new
  coverage needed.

## Affected files

- `main.py` — two sort call sites + per-game dispatch in Step 6 loop.
- `tests/` — new tests per above.
