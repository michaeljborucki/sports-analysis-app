# Betting-DB Read-Path Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep betting-site responsive and stop continuous scanner recomputation while `ODDS_SOURCE=betting_db` reads the central database.

**Architecture:** Debounce the native direct-book generation and publish typed SSE invalidations, key scanner memos by the active read source rather than raw native-cache churn, and run all full-universe scanner work behind a single bounded worker-thread gate. Push sport and prop-family filters into the betting-db SQL read and record cache-miss phase timings.

**Tech Stack:** Python 3.11, FastAPI/Starlette threadpool, asyncio, SQLite, pytest, Next.js 16, SWR, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-01-betting-db-read-path-stabilization-design.md`

## Global Constraints

- Never change `cache_mode` or switch it to `live`.
- Do not change Odds API spending behavior.
- Keep betting-db access read-only.
- Preserve every existing market family, Kalshi/Polymarket ask prices, Coral33 `wager_type`, and Kelly percentage semantics.
- Preserve the user's unrelated dirty-worktree changes.
- Use `python3`, never `python`.

---

### Task 1: Debounced source identity and typed invalidations

**Files:**
- Modify: `server/odds/cache.py`
- Modify: `server/odds/events.py`
- Modify: `server/odds/bettingdb_source.py`
- Modify: `server/tests/test_events.py`
- Modify: `server/tests/test_bettingdb_source.py`

**Interfaces:**
- Produces: `OddsCache.read_version` returning a hashable active-source fingerprint.
- Produces: `bettingdb_source.source_fingerprint() -> tuple` based on read-only DB/WAL stat identity.
- Produces: `events.mark_dirty(event_type: str = "tick")` with per-type debounce.
- Consumes: existing `OddsCache.version_flush_loop()` lifecycle.

- [ ] **Step 1: Write failing tests** for betting-db `read_version`, 15-second direct generation coalescing, typed `direct_books_changed` delivery, and native `tick` compatibility.
- [ ] **Step 2: Run focused tests and confirm failures** with `pytest -q server/tests/test_events.py server/tests/test_bettingdb_source.py`.
- [ ] **Step 3: Implement minimal source fingerprint, direct generation, and typed debounce behavior** without changing write or spend paths.
- [ ] **Step 4: Run focused tests and confirm they pass.**
- [ ] **Step 5: Inspect the diff for accidental changes to cache mode, fetching, or book-price semantics.**

### Task 2: Bounded off-event-loop scanner runtime

**Files:**
- Create: `server/odds/scanner_runtime.py`
- Create: `server/tests/test_scanner_runtime.py`
- Modify: `server/api/arbitrage.py`
- Modify: `server/api/low_hold.py`
- Modify: `server/api/ev.py`
- Modify: `server/api/free_bets.py`
- Modify: `server/api/profit_boost.py`

**Interfaces:**
- Produces: `run_scanner(name: str, compute: Callable[[], T]) -> Awaitable[T]`.
- Consumes: `OddsCache.read_version` in scanner memo keys.
- Preserves: existing `memoized_coalesced()` identical-request single-flight.

- [ ] **Step 1: Write failing runtime tests** proving blocking work runs off the event-loop thread, different scanner keys serialize through one capacity slot, and capacity timeout raises a retryable exception.
- [ ] **Step 2: Run `pytest -q server/tests/test_scanner_runtime.py` and confirm failures.**
- [ ] **Step 3: Implement a process-wide one-slot asyncio guard plus Starlette threadpool execution and timeout.**
- [ ] **Step 4: Convert each scanner's `_compute` into a synchronous closure executed through `run_scanner`, and replace `cache.version` with `cache.read_version` in memo keys.**
- [ ] **Step 5: Run runtime, coalescing, and scanner API tests.**

### Task 3: Source-side odds and props filtering

**Files:**
- Modify: `server/odds/cache.py`
- Modify: `server/odds/bettingdb_source.py`
- Modify: `server/api/odds.py`
- Modify: `server/api/props.py`
- Modify: `server/tests/test_bettingdb_source.py`
- Modify: `server/tests/test_api.py`

**Interfaces:**
- Produces: `OddsCache.all_current_family(sport_key: str, prop_family: bool) -> list[dict]`.
- Betting-db SQL classifies props using the exact prefixes from `market_config.PROP_MARKET_PREFIXES`.
- Native mode applies the same classifier without changing returned shapes.

- [ ] **Step 1: Write failing parity tests** containing h2h, alternates, first-five totals/moneylines, pitcher, batter, and player markets.
- [ ] **Step 2: Run focused adapter/API tests and confirm failures.**
- [ ] **Step 3: Implement SQL prefix inclusion/exclusion plus direct-book/native parity filtering.**
- [ ] **Step 4: Switch odds and props routes to the targeted interface and execute their synchronous build work through the worker runtime.**
- [ ] **Step 5: Run focused tests and confirm market-family parity.**

### Task 4: Browser invalidation scope and request cadence

**Files:**
- Modify: `web/lib/use-live-updates.ts`
- Create or modify: `web/lib/__tests__/live-update-prefixes.test.mjs`

**Interfaces:**
- Consumes SSE types: `tick`, `odds_changed`, `direct_books_changed`.
- Produces exported pure prefix mapping/matcher helpers for Node tests.

- [ ] **Step 1: Write failing Node tests** proving heartbeat/unknown behavior is unchanged and typed odds events target only odds-derived keys.
- [ ] **Step 2: Run the focused Node test and confirm failure.**
- [ ] **Step 3: Add typed mappings without introducing a second EventSource or removing 60-second fallback polling.**
- [ ] **Step 4: Run focused Node tests and `npx tsc --noEmit`, recording only documented pre-existing bets errors.**

### Task 5: Timing instrumentation and full verification

**Files:**
- Modify: `server/odds/bettingdb_source.py`
- Modify: `server/odds/scanner_runtime.py`
- Modify: tests for those modules as needed

**Interfaces:**
- Produces cache-miss logs with source/filter, row count, fetch/mapping/compute/total milliseconds.
- Logs contain no credentials, JWTs, account identifiers, or proxy details.

- [ ] **Step 1: Write failing log-capture tests** for cache-miss timing fields and absence on memo hits.
- [ ] **Step 2: Run focused tests and confirm failures.**
- [ ] **Step 3: Add `perf_counter()` phase instrumentation on cache misses and scanner runs.**
- [ ] **Step 4: Run `pytest server/tests`, distinguishing only the documented pre-existing EV failure.**
- [ ] **Step 5: Run web focused tests, `npx tsc --noEmit`, and `npm run build`, distinguishing only documented pre-existing errors.**
- [ ] **Step 6: Restart the local API and web app safely, without changing money-gated configuration.**
- [ ] **Step 7: Measure cold/warm odds and low-hold latency plus concurrent `/api/health`; require health under 500 ms during a scanner rebuild.**
- [ ] **Step 8: Verify Odds and Edges in the browser/network panel and confirm scanner SSE cadence is no faster than once per 15 seconds.**
- [ ] **Step 9: Review `git diff --check`, `git status`, and the final scoped diff before reporting results.**
