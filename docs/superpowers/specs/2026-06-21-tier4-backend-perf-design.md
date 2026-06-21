# Tier 4 — Backend Audit Fixes (A5, A6, A8)

**Date:** 2026-06-21
**Status:** Design — pending reviewer pass
**Roadmap items:** Tier 4 A5, A6, A8

## Context

Three independent backend findings from the 2026-06-21 audit. All are
correctness or modest perf wins; none change scanner output or API shape.

## Goals

- **A5:** Re-resolve `_resolved_keys` every 24h so tournament rotations (ATP draws, soccer matchdays) get picked up without a server restart.
- **A6:** Eliminate the redundant O(N) scan in `rows_to_games`'s best-price selection (currently three sequential O(N) passes per outcome — list-build, max, then find-original-by-tuple-match).
- **A8:** Push `distinct_events`'s `commence_time` time-window filter into SQL via `HAVING MAX(commence_time) BETWEEN ? AND ?` instead of materializing every row and filtering in Python.

## Non-goals

- `_event_sport_map` cleanup. Audit lumped it with `_resolved_keys` but the two have different problems: `_event_sport_map` doesn't *go stale* (event_id → api_key is immutable for an event); it leaks memory monotonically as events accumulate. That's a separate memory-management concern, deferred.
- Renaming or changing the public signature of `distinct_events`, `pick_best_price`, or `_resolve_keys`. Pure internal changes.
- Migrating cache storage format. Existing pattern (lex comparison on ISO datetime strings with `+00:00` suffix) already trusted by `purge_finished_games`, `purge_live_rows_for_book`, `purge_old_closing_lines` — A8 reuses the same pattern.

## Architecture

### A5 — TTL on `_resolved_keys`

Today (`server/odds/fetcher.py:67, 246-257`):
```python
self._resolved_keys: dict[str, list[str]] = {}

async def _resolve_keys(self, sport: Sport) -> list[str]:
    cached = self._resolved_keys.get(sport.key)
    if cached is not None:
        return cached
    # ... resolve, cache forever
```

Once populated, never refreshed for the process lifetime. Sports with pattern-shaped keys (`tennis_atp_*`, etc.) miss tournament rotations until restart.

**Fix:** Change cache shape to `dict[str, tuple[list[str], datetime]]`. TTL is a module constant `_RESOLVED_KEYS_TTL = timedelta(hours=24)`.

Behavior matrix:

| State | Action |
|-------|--------|
| No cached entry | Resolve. On success, cache `(keys, now)`. On failure, fall back to static keys; cache `(fallback, now)` so we don't retry-storm. |
| Cached, fresh (`now - cached_at < TTL`) | Return cached. |
| Cached, expired, resolve succeeds | Replace with `(new_keys, now)`. Log diff if changed. |
| Cached, expired, resolve fails | Return previously-cached `keys` unchanged. **Do not update timestamp** — next call retries on whatever cadence the caller runs (tier intervals, 180s-300s). |

This handles three subtle cases the draft missed:
- A transient network error during refresh doesn't blank out a previously-good set.
- A first-time failure still caches the fallback (no retry storm on every tick).
- Recovery happens automatically without a restart.

Testability: `_resolve_keys` gains a `now: datetime | None = None` kwarg. Default `datetime.now(timezone.utc)`. Tests pass explicit `now` values to advance the clock.

### A6 — `rows_to_games` single-pass best-price

Today (`server/odds/normalize.py:237-245`):
```python
price_tuples = [(p["bookmaker_key"], p["price_american"]) for p in out["prices"]]
best = pick_best_price(price_tuples)
best_price = None
if best is not None:
    best_price = next(
        p for p in out["prices"]
        if p["bookmaker_key"] == best[0] and p["price_american"] == best[1]
    )
```

Three passes per outcome:
1. List comprehension to build tuples (O(N))
2. `pick_best_price` does `max()` (O(N))
3. `next()` linear search to recover the original dict (O(N))

The audit called this "O(prices²)" — the third pass is the redundancy; eliminating it makes the whole thing strictly O(N).

**Fix:** Add `best_price_dict(prices: list[dict]) -> dict | None` to `server/odds/best_odds.py` and use it directly:

```python
def best_price_dict(prices: list[dict]) -> dict | None:
    """Pick the dict whose price_american gives the best bettor payout."""
    if not prices:
        return None
    return max(prices, key=lambda p: _american_to_payout_multiplier(p["price_american"]))
```

Call site becomes:
```python
best_price = best_price_dict(out["prices"])
```

`pick_best_price` (the tuple-based API) stays in place — it's tested and may be called elsewhere; additive change.

### A8 — `distinct_events` SQL pushdown

Today (`server/odds/cache.py:670-702`):
```python
q = """SELECT event_id, MAX(sport_key), MAX(commence_time), ...
       FROM odds_snapshot {WHERE sport_key=?}
       GROUP BY event_id"""
# Python:
for r in rows:
    ct = parse(r["commence_time"])
    if now <= ct <= horizon:
        out.append(...)
```

Pulls every event regardless of the time window; filters in Python.

**Fix:** Push the time window into SQL via `HAVING`. Critical: must filter on `MAX(commence_time)` (the per-event aggregate the SELECT returns), not on raw row `commence_time`, to preserve semantics when rows for one event disagree on commence_time.

```python
q_parts = ["""
    SELECT event_id, MAX(sport_key) AS sport_key,
           MAX(commence_time) AS commence_time,
           MAX(home_team) AS home_team, MAX(away_team) AS away_team
    FROM odds_snapshot
"""]
args: list = []
where: list[str] = []
if sport_key:
    where.append("sport_key = ?"); args.append(sport_key)
if where:
    q_parts.append("WHERE " + " AND ".join(where))
q_parts.append("GROUP BY event_id")
if within_hours_ahead is not None:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=within_hours_ahead)
    q_parts.append("HAVING MAX(commence_time) >= ? AND MAX(commence_time) <= ?")
    args.extend([now.isoformat(), horizon.isoformat()])
```

Then the Python post-loop only does the `str → datetime` conversion, no filtering.

**Why HAVING, not WHERE on the raw row:** if event X has rows with `commence_time = {2026-06-21T20:00, 2026-06-21T21:00}` (rare but possible via independent venue ingest paths), the current Python filter compares against `MAX = 21:00`. A naive `WHERE commence_time <= horizon` filters rows individually then groups — different result. The HAVING path matches today's behavior bit-for-bit.

**ISO-string lex comparison safety:** the existing `purge_finished_games`, `purge_live_rows_for_book`, and `purge_old_closing_lines` all use the same `commence_time <= ?` pattern against ISO strings. All write paths normalize to `+00:00`-suffixed ISO via `datetime.isoformat()` (the writer in `normalize_odds_response:112` explicitly converts `"Z"` to `"+00:00"` before parsing). The lex comparison is therefore safe.

## Testing

### A5 (`server/tests/test_fetcher.py`, new or extended)
- First-time resolve: success path caches both keys and timestamp.
- Repeat within TTL: no second API call (assert via mock).
- Past TTL with success: re-resolves; cache updated; log line emitted if keys changed.
- Past TTL with failure: returns previously-cached keys; timestamp NOT updated (so next call retries).
- First-time failure: returns static-key fallback; caches with `now` timestamp.

### A6 (`server/tests/test_best_odds.py`)
- Add `test_best_price_dict_picks_highest_payout`: 3 books at known American odds → returns the dict for the best payout.
- Add `test_best_price_dict_empty_returns_none`.
- Existing `rows_to_games` tests in `test_normalize.py` must remain green (output shape unchanged).

### A8 (`server/tests/test_cache.py`)
- `distinct_events` with no filters → returns all events (unchanged).
- With `sport_key` only → filters by sport (unchanged).
- With `within_hours_ahead=24` → SQL emits HAVING; returns only events in `[now, now+24h]`.
- With both filters → both filters AND'd correctly.
- Edge case: event with multiple rows whose commence_times differ — `MAX(commence_time)` is the filter target (preserves current behavior).

## Error handling

- **A5 refresh failure:** caught, log+keep cached set, don't update timestamp. Already partial via the `except Exception` in current code; the fix preserves that fallback.
- **A6:** zero-length `prices` list returns `None` (preserved from current `next(... if best is not None)` guard).
- **A8:** ISO-string comparison with malformed stored values would silently miss rows. Mitigation: trust the writer (which normalizes on the way in via existing code paths); failure would surface as a regression in the cache tests.

## Out of scope / deferred

- `_event_sport_map` memory growth (different problem from A5's staleness; not in the audit's repro).
- Index optimization on `odds_snapshot.commence_time` — index already exists per `cache.py:221`.
- Bidirectional ISO format normalization (`Z` vs `+00:00`) at write time — the existing pipeline already produces `+00:00`; no rows with `Z` reach the cache.

## Verification

Full server-test sweep should remain green (excluding the 15 pre-existing failures in `test_coral33_event_matcher`, `test_coral33_normalizer`, `test_ev`). Server restart + smoke-test should show:
- Boot log "sport X resolves to Odds API keys: ..." for each sport (unchanged).
- No errors from `_resolve_keys`.
- `/api/dashboard`, `/api/edges`, etc. all return data as before.
