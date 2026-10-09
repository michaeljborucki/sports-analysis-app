# Backend performance plan — 2026-10-08

## Measured symptom

`/api/cache-mode` was polled every 50ms for 60s:

| p50 | p90 | p99 | max |
|---|---|---|---|
| 6ms | 52ms | 640ms | **3,661ms** |

- Stalls of 300ms to 2s happen every 5 to 15s.
- Cached scanner responses take 2 to 20ms.
- Cold first hits: arb 430ms, EV 724ms, low-hold 330ms, dashboard 393ms.
- The API process sits at a steady ~22% CPU with 370MB RSS.

**Root cause:** the event loop is blocked. A py-spy profile was not captured because it needs sudo. The evidence below comes from three code audits, and I spot-checked the headline claims in the code.

## Ranked fixes

None of P1 to P3 change which edges are surfaced.

### P1: high impact, low risk

**1. Bound the betting_db events query.**
- Location: `server/odds/bettingdb_source.py:903` (`_betting_db_events_uncached`). The caller is `_betting_db_events(sport_key)` at `:1002`, which passes no window.
- Problem: there is no `commence_time` lower bound, so for each sport the query walks every past event in betting-db's 3.2GB `odds.db`.
  - Timings: NHL 4.9s, MLB 19.3s (for 2 events), all sports 44s.
  - Kalshi, Polymarket, Coral33 and Novig all call it every cycle, about 22 times a minute.
  - Its memo uses a 5s bucket, so calls almost always miss it.
  - This is the likely main source of the steady 22% CPU.
- Fix:
  - Add `e.commence_time >= now - past_hours`. The odds subquery already requires this, so the results are the same.
  - Change the memo to an age-based TTL.
- Verify: diff the event-ID sets from the old and new query on the live DB.

**2. Move SQLite writes off the event loop.**
- Problem: the Coral33, Kalshi and Polymarket cycles, their WebSockets, Novig and the orderbook poller all call `cache.upsert`, `purge_*` and `delete_rows` synchronously from `async def`.
  - Each call opens a new connection and runs 6 PRAGMAs, with a 10s busy timeout.
  - If a threadpool writer holds the lock, the loop waits on it. This is the likely cause of the multi-second stalls.
- Fix:
  - Use one writer thread with a persistent connection and a queue.
  - Batch WebSocket rows every ~200ms, which is well inside the 1-minute freshness target.
  - Run Coral33, Kalshi and Polymarket normalize/match in `to_thread`.

**3. Fix async handlers that do blocking DB work.**
- `cache_mode.py:191` `capture_snapshot` runs `VACUUM INTO` on the 633MB `cache.db` on the loop.
- `systems.py:65-75` and `coral33_accounts.py:307` also do blocking DB work on the loop.
- Fix: make them sync `def` or use `to_thread`.

**4. Bug: `POST /api/cache-mode` returns 500.**
- Location: `cache_mode.py:176`, `return await get_mode()`. `get_mode` is sync, so `await` raises TypeError.
- The mode is already applied and saved before the crash.
- Fix: one line.

### P2: medium impact, low risk

**5. Stop `mapping_health` re-scanning everything.**
- Location: `mapping_health.py:148`. It does its own full ~265k-row scan every 60s.
- Fix: reuse the snapshot's rows. This roughly halves RSS and reduces GC pressure.

**6. Fix the scanner memo TTL for arb and low-hold only.**
- Location: `util.py:26-32`. The 20s TTL overrides the generation key, so the same snapshot is re-scanned about 3 times a minute per open tab.
- Fix: rely on the generation key.
- **Do not apply this to EV, odds or props.** Their staleness filters use the current time.

**7. Serialize responses once inside the threadpool and memoize the bytes.**
- Today pydantic validates, dumps and runs `json.dumps` on the loop for every request, including memo hits.

**8. Add `GZipMiddleware`, excluding SSE.**
- The 413KB, 366KB and 310KB payloads would shrink about 8 to 12x.

**9. Memoize the unfiltered arb scan per generation.**
- Location: `ev.py:151`. EV re-runs a full `scan_all_arbs` for `tag_arb` on every miss.

**10. Slim the dashboard's `upcoming_games`.**
- It sends the full markets tree, but the card only reads 5 fields.
- After the change, regenerate `web/types/api.ts`.

**11. Memoize `/api/cache-mode` GET.**
- It runs two `COUNT(*)` scans on the 633MB and 315MB databases every 30s poll.
- Fix: key the memo on file mtime and size.

### P3: larger work, measure first

**12. Tune the garbage collector.**
- Use `gc.freeze()` after each snapshot publish, and/or raise thresholds.
- Confirm with `gc.callbacks` timing first.

**13. Make the snapshot rebuild incremental.**
- Use a watermark on `fetched_at` and stop running `rows_to_games` twice.
- Test it against a full rebuild in parallel.
- Medium risk, because `stale_seconds` must be recomputed for non-prop games.

**14. Point CLV capture at only the events it needs.**
- Location: `clv_capture.py:301`. Push `event_id IN (...)` into the query instead of reading the whole sport.

## Explicitly NOT doing

- Post-filtering an unfiltered arb scan by `books=`. The best price per side depends on the allowlist, so this would change which edges are shown.
- Result caps on low-hold or EV. These would change which rows are shown.
- A longer TTL on EV, odds or props. This would show prices that should have been dropped as stale.

## Separate observation

`/api/ev` returned 0 opportunities for draftkings, fanduel, novig and pinnacle at 22:15Z. This has not been investigated, and it may be legitimate.

## Status — 2026-10-09

**Done and live:** items 1–4, plus these:
- **5:** `mapping_health` now reuses the snapshot's rows.
- **11:** the cache-mode counts are memoized for 30s, and recomputed right away when the snapshot file changes.
- **12:** `gc.freeze()` runs after each snapshot publish.

**New diagnostic:** `server/loop_watchdog.py`. It only writes to the log:
- It logs event-loop stalls over 300ms, with the loop thread's stack.
- It logs full (gen-2) garbage-collection passes over 100ms.

**Results:**

| | Before | Now |
|---|---|---|
| Slow full GC passes | ~22 per 200s, 120–990ms each | ~1–3 per 2 min |
| p99 latency | 640ms | ~110–150ms |
| Responses over 300ms | ~13 per min | ~2–3 per min |
| `/api/cache-mode` | up to 4.6s | p50 3.7ms |

Occasional spikes of 2–2.8s remain, about one or two every 2 minutes.

**Remaining causes, from a `/usr/bin/sample` profile (no sudo needed):**
- The event-loop thread spends ~9% of its time waiting for the GIL.
- The main GIL holder is the snapshot rebuild thread. It runs `rows_to_games` twice on 230k rows every minute, taking 7–12s.
- The loop thread also spends ~2% on RSA signing (Kalshi auth) and on TLS/CA-bundle loading for each request.
- The writer thread does heavy `fsync`, open and unlink file I/O, because it opens a new SQLite connection for each write.

**Next options:**
- **A.** Incremental snapshot rebuild, or deriving non-prop games from the first pass. This is item 13 and medium risk: per-game `stale_seconds` must match.
- **B.** Reuse one curl_cffi `AsyncSession` for Coral33, and one httpx client per book.
- **C.** Give the writer thread one persistent SQLite connection.

## Status — 2026-10-09 (A–C done)

**A. Snapshot rebuild.**
- `rows_to_games_with_non_prop` in `normalize.py` builds all games and non-prop games in one pass.
- On 235k live rows it gave identical output for 523/523 games and 523/523 non-prop games. Grouping time went from 1.94s to 1.11s.
- Full rebuilds went from 7–12s to about 5s.

**B. Coral33 HTTP sessions.**
- The fetcher's long-lived client now reuses one curl_cffi `AsyncSession` (`persistent_session=True`).
- One-off clients in accounts and the wager log are unchanged.

**C. Writer connection.**
- The writer thread keeps one persistent SQLite connection.
- It reopens on a cache-path change or after a SQLite error.
- Readers stay per-call on purpose: a long-lived reader connection can pin an old read snapshot, which would serve stale odds.

**Root causes found along the way:**

1. **macOS throttling.** The API's launchd agent had no `ProcessType`, so launchd applied "light resource limits", throttling CPU and I/O. That froze the whole process for 1–4s during each once-a-minute CPU burst.
   - Fix: set `ProcessType=Interactive` in `~/Library/LaunchAgents/com.mike.betting-site-api.plist`.
   - This file is outside the repo. A backup was taken first.
2. **GIL handoff convoy.** Threads making many small I/O calls waited up to 5ms per GIL handoff while the rebuild ran, which added up to 1–1.8s on `/api/health`.
   - Fix: `sys.setswitchinterval(0.001)` in `server/main.py`.

**Final numbers** (3-minute probe, 4 endpoints at once):

| | Value |
|---|---|
| p99 | 57–108ms |
| max | 288–529ms |
| Responses over 1s | 0 |
| Process freezes | 0 |
| Loop stalls over 300ms | 1 (315ms) |

`server/loop_watchdog.py` stays in place. It logs loop stalls over 300ms, whole-process freezes over 1s, and gen-2 GC passes over 100ms.
