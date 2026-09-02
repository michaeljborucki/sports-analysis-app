# Systems and Odds Snapshot Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Systems and sport Odds pages from the published odds snapshot, eliminating their measured 6–8 second request-time betting-db reads.

**Architecture:** Extend `OddsSnapshot` with immutable sport-indexed non-prop games and three mainline raw-row views. Inject the existing application-scoped snapshot service into Odds and Systems while retaining optional legacy paths for isolated tests and rollback.

**Tech Stack:** Python 3.11, FastAPI, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-critical-pages-performance-design.md`

## Global Constraints

- Keep all endpoint response contracts unchanged.
- Preserve all market types and direct-book attributes.
- Do not enable the Odds API fetcher or change cache mode.
- Systems context warnings and deterministic rule behavior remain intact.
- Snapshot-backed requests perform no betting-db read.

---

### Task 1: Add sport and Systems indexes to the published snapshot

**Files:**
- Modify: `server/odds/latest_snapshot.py`
- Modify: `server/tests/test_latest_snapshot.py`

**Interfaces:**
- Produces: `OddsSnapshot.non_prop_games_by_sport: Mapping[str, tuple[dict, ...]]` and `OddsSnapshot.system_rows: tuple[dict, ...]` containing only `h2h`, `spreads`, and `totals` for MLB, NCAAF, and NFL.

- [ ] Write failing assertions that MLB non-prop games are addressable without scanning other sports and that prop rows are absent from both new views.
- [ ] Run `source .venv/bin/activate && pytest -q server/tests/test_latest_snapshot.py` and verify the new assertions fail for missing fields.
- [ ] Build both indexes during the existing worker-thread snapshot build, publish mappings through `MappingProxyType`, and retain no historical indexes.
- [ ] Run the test file and verify all tests pass.
- [ ] Commit `server/odds/latest_snapshot.py` and `server/tests/test_latest_snapshot.py` with message `perf: index snapshot views by sport and market family`.

### Task 2: Serve Odds from snapshot sport indexes

**Files:**
- Modify: `server/api/odds.py`
- Modify: `server/main.py`
- Modify: `server/tests/test_api.py`

**Interfaces:**
- `build_router(cache, snapshot_service: LatestOddsSnapshotService | None = None)`.
- Snapshot path consumes `snapshot.non_prop_games_by_sport.get(sport, ())`; legacy path remains unchanged when the dependency is absent.

- [ ] Add a failing endpoint test with a cache whose `all_current_family` raises and a fake snapshot containing one MLB game. Assert HTTP 200 and the existing `OddsResponse` shape.
- [ ] Run the new test and verify it fails on the legacy cache read.
- [ ] Obtain the snapshot before entering the worker computation, filter only the requested sport/time window, and preserve stale-seconds calculation and Pydantic validation.
- [ ] Inject the shared service from `main.py`.
- [ ] Run `source .venv/bin/activate && pytest -q server/tests/test_api.py server/tests/test_latest_snapshot.py`.

### Task 3: Serve Systems base games from snapshot mainline rows

**Files:**
- Modify: `server/systems/context.py`
- Modify: `server/api/systems.py`
- Modify: `server/main.py`
- Modify: `server/tests/test_systems_api.py`
- Modify: `server/tests/test_systems_context.py`

**Interfaces:**
- `build_evaluation_games(..., source_rows: tuple[dict, ...] | None = None)` uses supplied rows without calling `cache.all_current_markets`.
- `systems.build_router(..., snapshot_service: LatestOddsSnapshotService | None = None)` keys memoization on snapshot generation when present.

- [ ] Add a failing context test passing literal MLB mainline rows and a cache that raises on reads; assert one evaluation game is built.
- [ ] Add a failing API test with a fake snapshot service and no-op context enricher; assert the endpoint reads the snapshot and never the cache odds source.
- [ ] Run both focused tests and verify failures occur on missing interfaces or legacy reads.
- [ ] Implement the optional source-row path, obtain snapshots outside synchronous evaluation, and use snapshot generation in response cache keys.
- [ ] Inject the service from `main.py` and preserve the legacy test path.
- [ ] Run all Systems tests and the full server suite.

### Task 4: Live verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-critical-pages-performance-design.md`

**Interfaces:**
- Consumes: `python3 scripts/benchmark_critical_pages.py` and browser loads of `/edges`, `/accounts`, `/systems`, and `/odds/mlb`.

- [ ] Restart the launchd API service and wait for snapshot publication.
- [ ] Run the critical-page benchmark twice, recording warm results.
- [ ] Verify in the browser that Edges, Accounts, Systems, and MLB Odds render real data without console errors.
- [ ] Run `source .venv/bin/activate && pytest -q server/tests` and `cd web && npx tsc --noEmit`, treating only documented pre-existing failures as non-regressions.
- [ ] Record measured results in the design document and commit only performance-owned files that do not absorb unrelated work.
