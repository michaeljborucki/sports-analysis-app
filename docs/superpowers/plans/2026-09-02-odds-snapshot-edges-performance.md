# Odds Snapshot and Edges Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve all Edges scanners from one generation-aware, normalized odds snapshot so a page load does not repeat six-figure SQLite reads and normalization.

**Architecture:** Add one application-scoped `LatestOddsSnapshotService` that builds immutable row and game views in a worker thread, coalesces concurrent builds, and serves the previous snapshot while refreshing. Inject it into the five Edges routers and key their existing result caches by snapshot generation.

**Tech Stack:** Python 3.11, FastAPI lifespan, Starlette thread pool, SQLite, pytest, httpx/TestClient.

**Spec:** `docs/superpowers/specs/2026-09-02-critical-pages-performance-design.md`

## Global Constraints

- Keep `ODDS_SOURCE=betting_db` and `ODDS_API_FETCHER_ENABLED=false`; do not enable any metered Odds API path.
- Preserve Coral33/Kalshi/Polymarket direct-book overlays and direct-book-wins collision behavior.
- Preserve all supported market types; player props remain EV-only.
- Snapshot freshness target is approximately one minute.
- Retain at most the published snapshot and one snapshot under construction.
- Existing endpoint response contracts remain unchanged.
- Perform no Go rewrite, Redis installation, monorepo migration, or real-money placement change.

---

### Task 1: Snapshot value model and one-build concurrency contract

**Files:**
- Create: `server/odds/latest_snapshot.py`
- Create: `server/tests/test_latest_snapshot.py`

**Interfaces:**
- Consumes: `OddsCache.all_current()` and `server.odds.normalize.rows_to_games(rows, now=...)`.
- Produces: `OddsSnapshot(generation: int, built_at: datetime, source_version: tuple, rows: tuple[dict, ...], games: tuple[dict, ...])` and `LatestOddsSnapshotService.get() -> Awaitable[OddsSnapshot]`.

- [ ] **Step 1: Write failing model/build tests**

Create tests using a fake cache whose `all_current()` records calls. Assert that one `get()` returns tuples of rows/games, sets generation `1`, and captures `cache.read_version`. Assert two simultaneous first calls receive the same snapshot and call `all_current()` exactly once. Assert returned data includes mainline and prop rows so EV retains props.

- [ ] **Step 2: Run the tests and verify RED**

Run: `source .venv/bin/activate && pytest -q server/tests/test_latest_snapshot.py`

Expected: collection fails because `server.odds.latest_snapshot` does not exist.

- [ ] **Step 3: Implement the minimal snapshot service**

Create a frozen dataclass `OddsSnapshot`. Implement `LatestOddsSnapshotService` with an `asyncio.Lock`, a single `_build_task`, and `run_in_threadpool(self._build_sync)`. `_build_sync` calls `cache.all_current()` once, normalizes once, copies the outer collections to tuples, increments generation under publication, and records source version and UTC build time. `get()` returns the current snapshot when its source version still matches; otherwise it coalesces callers onto one build.

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `source .venv/bin/activate && pytest -q server/tests/test_latest_snapshot.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/latest_snapshot.py server/tests/test_latest_snapshot.py
git commit -m "feat: add shared latest odds snapshot service"
```

### Task 2: Stale-while-revalidate and bounded publication

**Files:**
- Modify: `server/odds/latest_snapshot.py`
- Modify: `server/tests/test_latest_snapshot.py`

**Interfaces:**
- Consumes: Task 1's `OddsSnapshot` and `LatestOddsSnapshotService`.
- Produces: `LatestOddsSnapshotService.get(allow_stale: bool = True)`, `start()`, `stop()`, and status fields `age_seconds`, `last_error`, and `refreshing`.

- [ ] **Step 1: Write failing refresh/error tests**

Add tests proving: a changed source version returns the published snapshot immediately while exactly one refresh runs; a failed refresh retains the published snapshot and records the error; `stop()` cancels and awaits the background loop; and repeated generations leave only `_current` plus the active build task rather than a history collection.

- [ ] **Step 2: Run the tests and verify RED**

Run: `source .venv/bin/activate && pytest -q server/tests/test_latest_snapshot.py`

Expected: failures for missing lifecycle/status and blocking refresh behavior.

- [ ] **Step 3: Implement background refresh**

Add a configurable refresh interval defaulting to 15 seconds and hard-stale age defaulting to 90 seconds. `start()` performs one coordinated initial build, then creates one loop that checks `cache.read_version`. `get()` serves `_current` immediately and schedules a refresh on version mismatch. Refresh failure logs structured timing without clearing `_current`. `stop()` cancels only this service's task.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `source .venv/bin/activate && pytest -q server/tests/test_latest_snapshot.py`

Expected: all tests pass without pending-task warnings.

- [ ] **Step 5: Commit**

```bash
git add server/odds/latest_snapshot.py server/tests/test_latest_snapshot.py
git commit -m "feat: refresh odds snapshots without blocking readers"
```

### Task 3: FastAPI lifecycle and dependency wiring

**Files:**
- Modify: `server/main.py`
- Modify: `server/api/arbitrage.py`
- Modify: `server/api/low_hold.py`
- Modify: `server/api/ev.py`
- Modify: `server/api/free_bets.py`
- Modify: `server/api/profit_boost.py`
- Create: `server/tests/test_snapshot_lifecycle.py`

**Interfaces:**
- Consumes: `LatestOddsSnapshotService(cache)` from Tasks 1–2.
- Produces: Edges router constructors accepting `snapshot_service: LatestOddsSnapshotService | None = None`; `None` preserves the legacy test and rollback path.

- [ ] **Step 1: Write failing lifecycle and injection tests**

Test `create_app()` with a fake snapshot service and patched fetchers. Enter `TestClient` lifespan and assert `start()` is awaited once; exit and assert `stop()` is awaited once. Add one router test showing an injected service is accepted without invoking the cache source directly.

- [ ] **Step 2: Run tests and verify RED**

Run: `source .venv/bin/activate && pytest -q server/tests/test_snapshot_lifecycle.py`

Expected: failures because the application does not construct or manage the service and routers do not accept it.

- [ ] **Step 3: Wire the application-scoped service**

Construct one service next to `OddsCache` in `create_app`. Start it in lifespan after cache initialization and stop it before cache-dependent background resources shut down. Pass the same instance to all five Edges routers. Keep optional constructor defaults so isolated endpoint tests remain compatible.

- [ ] **Step 4: Run lifecycle and existing API tests**

Run: `source .venv/bin/activate && pytest -q server/tests/test_snapshot_lifecycle.py server/tests/test_odds_api_fetcher_gate.py server/tests/test_arbitrage_depth.py server/tests/test_ev.py`

Expected: all pass except the documented pre-existing `test_three_way_markets_are_skipped` failure when included by the local suite.

- [ ] **Step 5: Commit**

```bash
git add server/main.py server/api/arbitrage.py server/api/low_hold.py server/api/ev.py server/api/free_bets.py server/api/profit_boost.py server/tests/test_snapshot_lifecycle.py
git commit -m "feat: wire odds snapshot through FastAPI lifespan"
```

### Task 4: Move all Edges scanners onto the shared normalized snapshot

**Files:**
- Modify: `server/api/arbitrage.py`
- Modify: `server/api/low_hold.py`
- Modify: `server/api/ev.py`
- Modify: `server/api/free_bets.py`
- Modify: `server/api/profit_boost.py`
- Create: `server/tests/test_edges_snapshot.py`

**Interfaces:**
- Consumes: `await snapshot_service.get()` returning `OddsSnapshot.games` and `.generation`.
- Produces: unchanged JSON response models; result memo keys use `snapshot.generation`.

- [ ] **Step 1: Write failing scanner-sharing tests**

Build all five routers against one fake snapshot service containing literal game dictionaries with mainline and prop markets. Request each endpoint and assert the source cache's `all_current()` is never called, the service is shared, each endpoint preserves its response schema, and non-EV scanners emit no player-prop opportunity.

- [ ] **Step 2: Run tests and verify RED**

Run: `source .venv/bin/activate && pytest -q server/tests/test_edges_snapshot.py`

Expected: requests still call the legacy cache or router constructors reject the service.

- [ ] **Step 3: Use snapshot games without renormalizing**

In each async handler, obtain the snapshot before forming its result-cache key. Pass `snapshot.games` into scanner functions from the worker-thread computation and remove endpoint-local `cache.all_current()` and `rows_to_games()` calls on the snapshot path. Use generation in the cache key. Retain the old path only when no service was injected.

- [ ] **Step 4: Run parity and scanner tests**

Run: `source .venv/bin/activate && pytest -q server/tests/test_edges_snapshot.py server/tests/test_arbitrage_depth.py server/tests/test_ev.py server/tests/test_bettingdb_source.py`

Expected: new tests pass; only the documented pre-existing EV test may fail.

- [ ] **Step 5: Commit**

```bash
git add server/api/arbitrage.py server/api/low_hold.py server/api/ev.py server/api/free_bets.py server/api/profit_boost.py server/tests/test_edges_snapshot.py
git commit -m "perf: share one normalized snapshot across edge scanners"
```

### Task 5: Measure Edges acceptance and document the next bottleneck

**Files:**
- Create: `scripts/benchmark_critical_pages.py`
- Modify: `docs/superpowers/specs/2026-09-02-critical-pages-performance-design.md`
- Test: `server/tests/test_latest_snapshot.py`

**Interfaces:**
- Consumes: running FastAPI on `127.0.0.1:8000` and the five existing Edges endpoints.
- Produces: a read-only benchmark command printing status, time-to-first-byte, total duration, and response bytes per endpoint plus a parallel Edges burst total.

- [ ] **Step 1: Write the benchmark contract test**

Test the script's pure result formatter with literal measurements and assert stable tabular output. Keep network execution under `main()` so importing the module performs no requests.

- [ ] **Step 2: Run the test and verify RED**

Run: `source .venv/bin/activate && pytest -q server/tests/test_latest_snapshot.py`

Expected: import failure for the benchmark formatter.

- [ ] **Step 3: Implement the read-only benchmark**

Use the Python standard library to issue individual and simultaneous GETs with a 30-second timeout. Include `/api/health`, all five Edges endpoints, `/api/coral33/accounts`, `/api/coral33/accounts/history?weeks=12`, `/api/systems?timeframe=today`, and `/api/odds/mlb`. Do not call refresh or placement endpoints.

- [ ] **Step 4: Verify tests and live performance**

Run server tests relevant to modified files, restart the local server, run `python3 scripts/benchmark_critical_pages.py`, and load `/edges` in the browser. Confirm health remains under 100 ms during the parallel burst and record which acceptance targets pass. If Edges remains above target, use the stage timings to define the next measured task rather than changing architecture speculatively.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_critical_pages.py server/tests/test_latest_snapshot.py docs/superpowers/specs/2026-09-02-critical-pages-performance-design.md
git commit -m "test: benchmark critical betting pages"
```

### Task 6: Create follow-on plans from measured results

**Files:**
- Create: `docs/superpowers/plans/2026-09-02-accounts-performance.md`
- Create: `docs/superpowers/plans/2026-09-02-systems-odds-performance.md`

**Interfaces:**
- Consumes: Task 5 measurements and the approved architecture spec.
- Produces: executable TDD plans for Accounts and Systems/Odds with concrete query plans and measured baselines.

- [ ] **Step 1: Capture Accounts and Systems/Odds stage evidence**

Use the benchmark output and server timing logs to identify whether Accounts is dominated by history reconstruction, CLV N+1 queries, or serialization, and whether Systems is dominated by odds loading, external context, evaluation, or persistence.

- [ ] **Step 2: Write both implementation plans**

Each plan must specify exact files, interfaces, failing tests, verification commands, rollback flags, and browser acceptance steps. It must preserve ASK prices, Kelly percentage units, supported first-five markets, and asynchronous account refresh.

- [ ] **Step 3: Self-review the plans**

Check both plans against the parent spec for coverage, placeholders, and type consistency. Remove any action not supported by Task 5 evidence.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-09-02-accounts-performance.md docs/superpowers/plans/2026-09-02-systems-odds-performance.md
git commit -m "docs: plan accounts and systems performance phases"
```
