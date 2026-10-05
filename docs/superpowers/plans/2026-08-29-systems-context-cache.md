# Persistent Systems Context Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist forward-looking Systems context, fill derivable MLB/CFB/NFL/weather fields, and avoid repeated enrichment and evaluation when source state is unchanged.

**Architecture:** A SQLite context repository owns TTL, stale-on-error, generation, and request coalescing. Focused provider adapters normalize free MLB Stats, ESPN, and Open-Meteo payloads. The Systems route memoizes complete responses by date, timezone, odds fingerprint, and context generation.

**Tech Stack:** Python 3.11, FastAPI, SQLite, `httpx`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-systems-context-cache-design.md`

## Global Constraints

- Never change `cache_mode` or invoke paid Odds API endpoints.
- Preserve point-in-time source timestamps and never fabricate missing values.
- Keep Football 8, Football 11, and Football 13 disabled.
- Work in the current dirty workspace and preserve unrelated user changes.

---

### Task 1: Persistent context repository

**Files:**
- Create: `server/systems/context_cache.py`
- Create: `server/tests/test_systems_context_cache.py`

**Interfaces:**
- Produces: `SystemContextCache.get_or_refresh(...)`, `SystemContextCache.generation`, and `CachedContext`.

- [ ] Write failing tests for fresh hits, expired refresh, generation changes, stale-on-error, and concurrent request coalescing.
- [ ] Run `pytest server/tests/test_systems_context_cache.py -q` and confirm failures describe missing behavior.
- [ ] Implement schema, deterministic JSON writes, keyed async locks, and stale fallback.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Complete MLB derivations

**Files:**
- Modify: `server/systems/context.py`
- Modify: `server/tests/test_systems_context.py`

**Interfaces:**
- Consumes: `SystemContextCache`.
- Produces: cached MLB standings/schedule fields, exact season break boundary, and prior-home-series sweep state.

- [ ] Write failing fixture-driven tests for previous completed home-series sweep and team-ID joins.
- [ ] Confirm the new tests fail for missing sweep derivation.
- [ ] Extend MLB history entries with series identity, series number, venue, and team IDs; derive the prior completed home-series result.
- [ ] Route schedule and standings loads through the persistent cache with their specified TTLs.
- [ ] Run all Systems context tests.

### Task 3: Football metadata and weather adapters

**Files:**
- Modify: `server/systems/context.py`
- Modify: `server/tests/test_systems_context.py`

**Interfaces:**
- Produces: CFB FBS/conference/week, NFL regular-season week/division/playoff membership, and kickoff weather.

- [ ] Write failing tests using complete ESPN/Open-Meteo fixtures for regular-season classification, FBS exclusion, venue matching, nearest-hour temperature, and sustained wind.
- [ ] Confirm failures before production changes.
- [ ] Cache ESPN scoreboard/team metadata, Open-Meteo geocoding, and forecasts with provider-specific keys and TTLs.
- [ ] Derive NFL prior postseason membership from cached prior-season events.
- [ ] Keep coach identity unavailable unless an attributable structured source exists; cache any confirmed result for 24 hours.
- [ ] Run evaluator and context tests.

### Task 4: Systems response memoization and coverage

**Files:**
- Modify: `server/api/systems.py`
- Modify: `server/systems/models.py`
- Modify: `server/tests/test_systems_api.py`

**Interfaces:**
- Consumes: odds fingerprint and context generation.
- Produces: 30-second memoized `SystemsResponse` and per-system coverage counts.

- [ ] Write failing tests proving a repeated unchanged request enriches once and odds/context changes invalidate the response.
- [ ] Confirm the tests fail against the uncached route.
- [ ] Implement bounded response memoization without caching endpoint failures.
- [ ] Preserve idempotent signal writes only on newly computed responses.
- [ ] Run API and store tests.

### Task 5: Verification and live restart

**Files:**
- Verify only.

- [ ] Run `git diff --check`.
- [ ] Run all focused Systems tests plus betting-db source tests.
- [ ] Run `npx tsc --noEmit` and distinguish documented unrelated failures.
- [ ] Restart the backend, request `/api/systems` twice, and verify the warm request target and cache warnings.
- [ ] Confirm `/systems` returns HTTP 200 while both services remain running.
