# Forward-Looking Systems Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a global Systems tab that evaluates only upcoming games against all 25 primary systems and records qualifying signals going forward.

**Architecture:** A pure registry/evaluator layer consumes current cached odds and normalized point-in-time context, while adapters fetch optional free context and an idempotent SQLite store records sightings. A read-only FastAPI endpoint exposes evaluations and a SWR-backed Next.js workbench renders qualifying wagers plus the complete system audit.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLite, httpx, pytest, Next.js 16 App Router, React 19, SWR, Tailwind 4, TypeScript.

**Spec:** `docs/superpowers/specs/2026-08-29-forward-looking-systems-page-design.md`

## Global Constraints

- Evaluate only not-yet-started games on the requested `America/Denver` local date.
- Never trigger an Odds API fetch, flip `cache_mode`, or place a bet.
- Missing required inputs return `unable_to_evaluate`; they never become `no_match`.
- Football 8, 11, and 13 remain disabled.
- Preserve analytical overlaps and deduplicate wager candidates.
- Persist detections from this release forward; do not backtest or grade outcomes.
- Use `python3`, not `python`.

---

### Task 1: Registry and contracts

**Files:**
- Create: `server/systems/__init__.py`
- Create: `server/systems/models.py`
- Create: `server/systems/registry.py`
- Test: `server/tests/test_systems_registry.py`

**Interfaces:**
- Produces: `SYSTEMS`, `SystemDefinition`, `SystemEvaluation`, `SystemSignal`, `SystemsResponse`.

- [ ] Write a failing test asserting 25 primary definitions, unique IDs, disabled states for Football 8/11/13, and Football 2B nested metadata.
- [ ] Run `pytest server/tests/test_systems_registry.py -q` and confirm import/contract failure.
- [ ] Add the Pydantic contracts and immutable registry definitions with source claims and required fields.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Pure evaluator and overlap grouping

**Files:**
- Create: `server/systems/evaluator.py`
- Test: `server/tests/test_systems_evaluator.py`

**Interfaces:**
- Consumes: normalized `EvaluationGame` records containing current markets plus optional context fields.
- Produces: `evaluate_systems(games, evaluated_at, requested_date)` and `deduplicate_wagers(signals)`.

- [ ] Write failing table-driven tests for forward-only filtering, strict/inclusive thresholds, MLB price conventions, disabled rules, missing inputs, Football 2B, and Football 9/10 overlap.
- [ ] Run the focused evaluator tests and verify failures name missing behavior.
- [ ] Implement small rule predicates and a dispatcher; each predicate returns matched signals or its exact missing fields.
- [ ] Implement stable wager grouping that retains supporting system IDs.
- [ ] Re-run focused tests and refactor only while green.

### Task 3: Context assembly and signal persistence

**Files:**
- Create: `server/systems/context.py`
- Create: `server/systems/store.py`
- Modify: `server/odds/cache.py`
- Test: `server/tests/test_systems_context.py`
- Test: `server/tests/test_systems_store.py`

**Interfaces:**
- Produces: `build_evaluation_games(cache, requested_date, timezone, now)` and `SystemSignalStore.record(signals)`.

- [ ] Write failing tests proving current cache rows normalize into one event, started/off-date events are excluded, provider failures become warnings, and repeated signal recording is idempotent.
- [ ] Run focused tests and verify expected failures.
- [ ] Add the SQLite sighting schema/migration and store methods.
- [ ] Add current-odds normalization plus short-timeout, cached free-context adapters; preserve unknown fields as missing.
- [ ] Re-run focused tests and refactor only while green.

### Task 4: Read-only API

**Files:**
- Create: `server/api/systems.py`
- Modify: `server/main.py`
- Test: `server/tests/test_systems_api.py`

**Interfaces:**
- Produces: `GET /api/systems?date=YYYY-MM-DD&timezone=America/Denver` returning `SystemsResponse`.

- [ ] Write a failing API test with a temporary cache asserting 25 evaluations, future-only signals, warnings, and no fetcher/cache-mode calls.
- [ ] Run the focused API test and verify route absence.
- [ ] Implement and register the router, evaluate normalized games, and best-effort persist signals.
- [ ] Re-run the API test and related server tests.

### Task 5: Systems tab and workbench

**Files:**
- Create: `web/lib/systems.ts`
- Create: `web/app/systems/page.tsx`
- Create: `web/app/systems/loading.tsx`
- Create: `web/components/systems/systems-workbench.tsx`
- Modify: `web/lib/api.ts`
- Modify: `web/lib/sections.ts`
- Modify: `web/app/globals.css` (additive Systems stamp/tokens only if needed)

**Interfaces:**
- Consumes: `SystemsResponse` from `/api/systems`.
- Produces: global `/systems` route and navigation item.

- [ ] Add a failing pure TypeScript formatter/grouping test for status counts, nested Football 2B support, and wager rows.
- [ ] Run the focused test and verify the missing module failure.
- [ ] Add typed API helpers and the formatter.
- [ ] Build the responsive workbench with loading, error, no-game, qualified, unavailable, and disabled states.
- [ ] Add the global navigation entry between Picks and Edges.
- [ ] Run the focused test and `npx tsc --noEmit`, distinguishing known `web/app/bets/` failures.

### Task 6: OpenAPI and verification

**Files:**
- Modify: `web/openapi.json`
- Modify: `web/types/api.ts`
- Modify: `web/types/api.d.ts`

- [ ] Run the server and export fresh OpenAPI JSON.
- [ ] Run `npx openapi-typescript ./openapi.json -o ./types/api.ts` and keep the declaration mirror aligned.
- [ ] Run focused Systems tests, then `pytest server/tests` and record only known pre-existing failures.
- [ ] Run `npx tsc --noEmit` and `npm run build`, recording only known pre-existing failures.
- [ ] Verify `/systems` in the browser at desktop and mobile widths, inspect server/browser logs, and confirm page-load performance and visible status semantics.
- [ ] Run Hallmark's final slop-test and responsive checks before handoff.

