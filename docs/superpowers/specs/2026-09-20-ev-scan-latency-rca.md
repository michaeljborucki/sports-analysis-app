# RCA — /api/ev takes 30–46s and the Dashboard never loads

Date: 2026-09-20. Status: **diagnosis only — no code or DB changed.**

## Symptom

`/dashboard` sits on "Loading dashboard…" forever. `/api/ev` returns an
empty result set (`{"opportunities":[]}`, 137 bytes) after 36–68s.
`/api/odds/mlb` intermittently 503s.

## Where the time goes (measured, not inferred)

`server/odds/bettingdb_source.py` already logs the split:

```
betting-db read sport=all rows=20350 fetch_ms=41718.4 map_ms=81.2 total_ms=41800.1
```

`fetch_ms` 30,000–46,000 / `map_ms` 34–213. ~99.7% of the time is inside a
single SQLite `execute().fetchall()`. Not Python, not the devig math —
the scanners themselves run in 17–70ms when their data is already in hand.

## Root cause chain

1. **betting-db never prunes `latest_odds`.** No `DELETE`, no VACUUM
   anywhere in the repo; the archiver (`betting_db/archive.py:147-195`)
   prunes `odds_ticks` only and explicitly leaves `latest_odds` alone.
   `outcome_point` is part of the upsert conflict key
   (`betting_db/store.py:212-245`), so every alt line ever posted becomes a
   permanent row. Result: **5,623,719 rows** for **2,661 events**.

2. **The betting-site query cannot use an index.**
   `_freshness_sql` (`server/odds/bettingdb_source.py:418-442`) emits
   `commence_time >= ? AND fetched_at >= CASE WHEN commence_time <= ? ...`.
   `commence_time` is unindexed, and `fetched_at >= CASE(commence_time)` is
   row-dependent, so it is not sargable. `EXPLAIN QUERY PLAN` → `SCAN
   latest_odds`, all 5.6M rows, every call.

3. **The WAL is 2.1 GB — and this is the dominant cost.** Main DB 3.1 GB,
   `odds.db-wal` 2.1 GB (~525k frames). betting-db sets `journal_mode=WAL`
   but has **no `wal_checkpoint` call and no `synchronous`/
   `wal_autocheckpoint` pragma** anywhere. Passive autocheckpoints cannot
   reset a WAL while a reader is active.

4. **Vicious cycle.** Because each read takes ~35s, betting-site has a
   reader open on this DB almost continuously → passive checkpoints never
   complete → WAL grows → reads get slower → readers stay open longer.

5. **`MEMO_TTL_SECONDS = 5` (line 181) is 7x shorter than the 35s scan it
   memoizes.** The bucket expires before the scan it is caching finishes,
   so the memo can never hit and every request re-scans from scratch.

6. **`Semaphore(1)` in `server/odds/scanner_runtime.py:19` serialises every
   scanner process-wide**, with a 30s acquire timeout. One 35s scan starves
   the rest — observed `low-hold wait_ms=36947` — and anything that waits
   >30s gets a 503. That is the `/api/odds/mlb` 503. The Dashboard needs
   several scanners, so it never finishes.

## Measurements

Identical query, identical params, identical 45,112-row result:

| Database state | Plan | Time |
|---|---|---|
| Live (3.1 GB + 2.1 GB WAL), no index | `SCAN` | **41,186 ms** |
| `VACUUM INTO` copy, no index | `SCAN` | **1,623 ms** (25x) |
| Vacuumed copy + `INDEX(commence_time)` | `SEARCH` | **515–896 ms** (46–80x) |

**The WAL bloat, not the missing index and not the 5.6M rows, is the
dominant factor.** A full scan of all 5.6M rows costs only 1.6s once the
DB is checkpointed and compact.

Also verified: an implied sargable bound (`AND fetched_at >= MIN(cutoffs)`,
logically entailed by the existing CASE) is **result-identical** — proven
under one `BEGIN DEFERRED` snapshot — but only 2.0x on the bloated DB.
(A first comparison showed a false mismatch; it was confounded by the live
writer inserting rows between the two queries. Under a single snapshot the
result sets match exactly.)

## Candidate fixes, by impact

Ordered by measured effect. Items 1–3 are writes to **betting-db's live
3.1 GB production DB** (a `launchd` daemon, `com.mike.betting-db`, is
actively writing to it) — destructive/cross-project, not to be done
without an explicit go-ahead.

1. **Checkpoint + compact the WAL** (~25x). One-time `wal_checkpoint(TRUNCATE)`
   / VACUUM, plus a periodic `PRAGMA wal_checkpoint(TRUNCATE)` in the
   betting-db writer so it cannot regrow. Biggest win by far.
2. **Add retention to `latest_odds`** — prune rows for finalized/past events.
   Stops the regrowth that causes everything else. Destructive DELETE.
3. **`CREATE INDEX ON latest_odds(commence_time)`** (~3x on top of 1).
   Cheap to build: 4.7s on the copy.
4. **betting-site: raise `MEMO_TTL_SECONDS`** so the memo can actually hit.
   Trades freshness — the target is ~1 min and stale odds are treated as
   bugs, so this is a judgement call, not a free win. Once 1–3 land the scan
   is sub-second and 5s is fine as-is.
5. **betting-site: add the implied sargable bound** to `_freshness_sql`.
   Verified result-identical; 2.0x today, marginal after 1–3.
6. **betting-site: revisit `Semaphore(1)` + 30s timeout** — it converts one
   slow scan into cross-endpoint 503s. Symptom amplifier, not the cause.

## Notes

- `cache_mode` is `live` and was left untouched. `ODDS_SOURCE=betting_db`,
  `fetcher_running: false` — no Odds API spend was involved in any of this.
- A 2.9 GB `VACUUM INTO` copy used for benchmarking is in this session's
  scratchpad (`copy.db`) and can be deleted.

---

# Outcome — what was applied on 2026-09-20

## Shipped and LIVE

**betting-site — sargable freshness floor** (`server/odds/bettingdb_source.py`,
`_freshness_sql`). Emits `fetched_at >= MIN(cutoffs)` alongside the existing
CASE. Logically entailed by the CASE, so the result set cannot change —
verified against the live DB under one `BEGIN DEFERRED` snapshot:
**identical rows, 34,848ms -> 12,282ms (2.8x)**, plan `SCAN` -> `SEARCH
latest_odds USING INDEX idx_latest_fetched`. Also verified it does NOT flip
the planner to a worse index once an index on `commence_time` exists
(re-tested on the copy: still seeks `commence_time`, 1381ms -> 720ms).
Tests added: `test_freshness_sql_emits_a_sargable_fetched_at_floor`,
`test_catch_all_band_row_survives_the_sargable_floor`. Suite: 831 passed.

**LIVE** — the launchd service `com.mike.betting-site-api` was restarted and
is running this code (pid confirmed owning :8000, health 200).

## Shipped but INERT until the poller restarts

**betting-db — `Store.maintenance()`** (`betting_db/store.py`): prunes
`latest_odds` past a retention window, then `PRAGMA wal_checkpoint(TRUNCATE)`.
Wired into the poll loop via `Scheduler._maybe_maintain`
(`betting_db/scheduler.py`), configured by a new `[maintenance]` block in
`config.toml` (`enabled = true`, `interval_minutes = 10`). Also set
`PRAGMA synchronous=NORMAL` on the writer connection.
Tests added to `tests/test_store.py`; suite: 249 passed.

**INERT** — the `com.mike.betting-db` daemon reads config at startup and is
still running the old code. It must be restarted:

```bash
launchctl kickstart -k gui/$(id -u)/com.mike.betting-db
```

On restart the 10-minute checkpoint tick truncates the 2.1GB WAL by itself.
That is the 25x win and needs no manual DB surgery.

## NOT done — blocked, needs the user

1. **Retention is OFF.** `latest_odds_retention_days` is deliberately absent
   from `[maintenance]`, so nothing is deleted. Enabling it (`= 7`) was
   blocked by the sandbox as a mass delete. Turning it on removes ~3.45M of
   5.6M rows on the next tick — 7 days is ~28x betting-site's 6h read window.
2. **The existing 2.1GB WAL is still there.** A one-time
   `wal_checkpoint(TRUNCATE)` was blocked (writes to the live betting-db).
   The daemon restart above does this automatically.
3. **No `INDEX(commence_time)`** on `latest_odds` — measured a further ~3x on
   top of a compacted DB. Blocked for the same reason; ~4.7s to build.
4. **Stopping the services for a clean VACUUM** was blocked (workload
   interference).

## Current measured state

Dashboard **renders** (302 edges) instead of hanging, and no 503s. But the DB
is still bloated, so scans are ~22s and `/api/health` is being starved to
13-25s behind the `Semaphore(1)` in `server/odds/scanner_runtime.py`.
**This is not finished until the poller is restarted.**

`MEMO_TTL_SECONDS` was deliberately left at 5 — raising it would buy speed by
serving staler odds, and once the DB is compact the scan is sub-second and 5s
is correct. Fixing the cause beats widening the cache.

---

# Round 2 — remaining in-repo issues fixed (still 2026-09-20)

## 7. Memo was age-blind: every scanner re-scanned the same rows — FIXED, LIVE

`_mapped_rows` keyed its memo on a wall-clock BUCKET
(`int(time.time() // MEMO_TTL_SECONDS)`) captured when the scan STARTED,
then stored the result under that bucket after the scan returned. With a
34s scan and a 5s bucket the entry was filed under a window seven rolls in
the past — it arrived already expired. The next caller missed and re-scanned
data that was seconds old, so the dashboard's ev + arb + low-hold + free-bets
each paid for their own full copy.

Buckets were also wrong in principle: an entry got 0-TTL seconds of life
depending on where in the window it landed, so a memo could expire one
second after being written.

Now age-based: store `produced_at`, hit while `now - produced_at < TTL`.
Rows are still at most one TTL old relative to when they were produced —
**the freshness window is not widened**, which is why `MEMO_TTL_SECONDS`
stays at 5 and no alpha is traded for latency.

Measured after the fix: a cold `/api/dashboard` does **1** betting-db read
instead of 4, **45s -> 12.4s**.

## 8. Blocking sqlite on the event loop — FIXED, LIVE (but not the starvation cause)

`/api/health` and `/api/cache-mode` were `async def` while doing blocking
sqlite (`_inspect_db` runs `COUNT(*)` over cache.db AND cache.snapshot.db).
On the event loop that stalls every concurrent request, the SSE flush loop
and the heartbeat. Both are now plain `def`, so Starlette runs them in its
threadpool.

Honest scope note: this was measured at 0.006s on an idle server and then
re-measured at **26s with a real cold scan in flight** — so it is a genuine
correctness fix (the event loop is no longer blocked) but it was NOT the
cause of the health starvation. The starvation is GIL/CPU contention from
the scan itself, and it goes away when the scan gets cheap — which is what
items 1-3 do.

## Current measured state (all fixes live)

| | before | now |
|---|---|---|
| betting-db read (`sport=all`) | 30,000-46,000 ms | **13,445 ms** |
| reads per cold dashboard | 4 | **1** |
| `/api/dashboard` cold | ~45 s | **12.4 s** |
| `/api/health` (idle) | 12.5 s | **0.007 s** |
| `/api/cache-mode` (idle) | 23.5 s | **0.085 s** |
| Dashboard page | hung forever | **renders, "FRESH · 12s"** |

Suite: 834 passed. betting-db: 249 passed.

## Still blocked — only the user can do these

The sandbox denied every write to the live betting-db, both service
restarts, and enabling retention. These remain the largest wins:

```bash
# 1. Load the maintenance code -> truncates the 2.1GB WAL on the first
#    10-min tick. This is the ~25x win. Non-destructive.
launchctl kickstart -k gui/$(id -u)/com.mike.betting-db

# 2. Optional, destructive: prune ~3.45M of 5.6M rows.
#    Add to [maintenance] in betting-db/config.toml, then restart as above:
#      latest_odds_retention_days = 7

# 3. Optional, ~3x more on top of a compacted DB (~4.7s to build):
#    CREATE INDEX idx_latest_commence ON latest_odds(commence_time);
```

---

# Round 3 — after the user restarted the poller

The user ran `launchctl kickstart -k gui/$(id -u)/com.mike.betting-db`.

## The maintenance code is live and working as designed

betting-db's log now shows this project's own line:

```
wal_checkpoint(TRUNCATE) blocked by a reader (wal_pages=4330 checkpointed=4)
  — will retry next pass
```

It runs, it cannot get the exclusive moment TRUNCATE needs, and it retries
instead of crashing. betting-site reads this DB near-continuously, so it is
unlikely to ever win that race on its own.

## Correction to the round-1 conclusion

Round 1 said "the WAL bloat is the dominant factor." That is now doubtful.
`wal_pages=4330` is ~17MB of LIVE frames inside a 2.1GB file — the file is
mostly unreclaimed space, and `-shm` shrank 1.4MB -> 352K. So the 25x that
`VACUUM INTO` produced was probably mostly **main-DB defragmentation**, not
WAL frame count. That changes the priority: **VACUUM matters more than the
checkpoint**, and the checkpoint alone will not deliver the 25x.

## The load grew, so wall-clock went back up

The restarted poller refreshed the whole book, so far more rows now pass the
freshness filter: reads went from `rows=20,350` to `rows=347,178`. Same code,
~17x the rows.

| | earlier today | now |
|---|---|---|
| rows per read | 20,350 | 347,178 |
| `fetch_ms` | 13,445 | ~28,000 |
| `/api/dashboard` | 12.4 s | 46.6 s |

The betting-site fixes are still doing their job (one shared read instead of
four; the sargable floor still seeks rather than scans) — there is simply far
more data flowing now. The structural fixes are what is left.

## Checked and rejected

Pushing `disabled_sports` into the SQL: only **6.6%** of fetched rows belong
to the five disabled sports. NFL (165k) and MLB (141k) are the bulk and are
wanted. Not worth the correctness risk.

## The remaining work needs a quiet window

Added `betting-db/scripts/compact_odds_db.py`. It refuses to run if anything
still has the DB open, then optionally prunes, creates
`idx_latest_commence`, TRUNCATEs the WAL, VACUUMs and ANALYZEs.

Caveat: only its syntax and `--help` are verified — the sandbox blocked
running it, so its refuse-path and its real run are **untested**.

```bash
launchctl bootout gui/$(id -u)/com.mike.betting-site-api
launchctl bootout gui/$(id -u)/com.mike.betting-db

cd ~/personal_workspace/betting-db
python3 scripts/compact_odds_db.py --prune-days 7     # omit the flag to delete nothing

launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mike.betting-db.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mike.betting-site-api.plist
```

VACUUM needs free disk ~= the final DB size; the volume was at 89% when this
was written. The 2.9GB `copy.db` in the session scratchpad is a pre-prune
snapshot of the data and is worth keeping until after the run.

---

# Round 4 — compaction run. RESOLVED.

User authorised stopping everything and running the compaction. Services
stopped (`com.mike.betting-site-api`, `com.mike.betting-db`,
`com.mike.betting-db-archive`), verified zero holders on `odds.db`, then:

```
python3 scripts/compact_odds_db.py --prune-days 7
  before    db=  3258.6MB  wal=  2172.6MB
  pruned   3,522,609 row(s) older than 2026-09-13T16:35:58Z (72.9s)
  indexed  idx_latest_commence (9.0s)
  ckpt     busy=0 wal_pages=0 checkpointed=0 (0.6s)
  vacuum   (38.1s)
  after     db=  1380.3MB  wal=     0.0MB
```

~4GB reclaimed. All three services restarted and verified.

## Final measured state

| | at the start | now |
|---|---|---|
| `latest_odds` rows | 5,623,719 | **2,101,110** |
| DB on disk | 3.26GB + 2.17GB WAL | **1.38GB + 61MB WAL** |
| `fetch_ms` (`sport=all`, ~345k rows) | 30,000-46,000 | **1,447-1,886** |
| reads per cold dashboard | 4 | **1** |
| `/api/dashboard` cold | ~45s (page never loaded) | **4.3-4.8s** |
| `/api/ev` (novel params, real scan) | 36-68s | **0.28-0.71s** |
| `/api/health` | 12.5-28s | **0.007-0.44s** |
| `/api/cache-mode` | 23.5s | **0.09s** |
| Dashboard page | hung forever | **renders, "FRESH · 17s"** |

`fetch_ms` improved ~20-30x; the endpoints 10-100x.

## Residual, being watched

`wal_checkpoint(TRUNCATE)` still reports `blocked by a reader` on its
10-minute tick — betting-site's reads, though now ~1.5s, still overlap it.
This is no longer harmful: the WAL rose to 61MB during the poller's startup
burst and then held **flat at 61MB over 4.5 minutes**, i.e. SQLite is
recycling space inside the file instead of extending it. The 2.1GB was the
product of 22 days of ever-slower reads, and that feedback loop is broken.
Worth a glance in a few days; if it climbs, the lever is a PASSIVE
checkpoint before the TRUNCATE attempt.

Note: with `idx_latest_commence` in place the sargable floor is no longer
load-bearing (537ms with it vs 376ms without — the difference is noise at
this scale). It is kept because it is correct, tested, and keeps the query
off a full scan if that index is ever dropped.
