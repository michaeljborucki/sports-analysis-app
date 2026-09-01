# Betting-DB Read-Path Stabilization Design

## Purpose

Restore predictable betting-site page and API latency while `ODDS_SOURCE=betting_db` is active. The betting site remains a read consumer of the central betting database, while direct-book data from Coral33, Kalshi, and Polymarket continues to come from the site's native cache.

This is the first of two deliverables. It stabilizes the existing read path without changing the betting-db schema. A subsequent design will move EV, arbitrage, low-hold, free-bet, and profit-boost derivation into materialized betting-db result tables.

## Problem Statement

The current data flow amplifies frequent direct-book writes into expensive browser-triggered recomputation:

1. Any native `OddsCache` write increments a global cache version and marks the SSE stream dirty.
2. The SSE stream can publish a generic `tick` once per second.
3. The browser maps every generic tick to every odds and scanner SWR key.
4. Scanner endpoints synchronously read and normalize the full betting-db universe inside FastAPI `async` handlers.
5. The betting-db adapter memo expires every five seconds, while native direct-book writes continuously invalidate scanner memo keys through `cache.version`.
6. One expensive request blocks the uvicorn event loop, delaying unrelated endpoints such as `/api/health`.

The live database observed during diagnosis was approximately 942 MB plus a 480 MB WAL. `latest_odds` held 1,130,506 rows, including 757,134 MLB rows. This scale makes full-universe request-time materialization incompatible with responsive HTTP handling.

## Goals

- Keep lightweight endpoints responsive while a scanner rebuild is running.
- Prevent continuous direct-book writes from triggering full scanner fan-out once per second.
- Preserve direct-book freshness with a target browser-visible delay no greater than 15 seconds.
- Ensure concurrent identical scanner requests share one computation.
- Keep betting-db reads read-only.
- Preserve all current market types and scanner semantics.
- Preserve Kalshi and Polymarket ask-price behavior, Coral33 `wager_type`, and Kelly percentage semantics.
- Add enough timing evidence to identify database-read, normalization, scan, validation, and serialization costs.

## Non-Goals

- Do not change `cache_mode`, and never switch it to `live`.
- Do not change Odds API spending behavior.
- Do not remove direct-book pollers or their native-cache writes.
- Do not introduce betting-db schema or migration changes in this deliverable.
- Do not redesign scanner algorithms or alter opportunity calculations.
- Do not silently omit props, alternate lines, first-five markets, or other existing market types.

## Selected Approach

### 1. Separate data-change identity from the native cache version

Introduce a read-source fingerprint used by scanner memo keys. In native mode it remains the native `OddsCache.version`. In betting-db mode it combines:

- a coarse betting-db snapshot identity derived from the database files' modification state, cached briefly; and
- a separately debounced direct-book generation.

The direct-book generation advances at most once per stabilization window instead of once per row or websocket burst. This preserves direct-book updates without destroying every scanner memo continuously.

The fingerprint is an optimization identity only. It does not determine Odds API spend paths and does not mutate either database.

### 2. Publish scoped, debounced SSE invalidations

Replace the single generic browser invalidation behavior with typed events:

- `odds_changed`: invalidates odds, props, dashboard, and scanner keys.
- `direct_books_changed`: invalidates the same data consumers, but is emitted no more than once per 15-second scanner stabilization window.
- Existing non-odds event types remain independently scoped.

In betting-db mode, native direct-book cache writes produce `direct_books_changed`; they do not produce a one-per-second generic scanner tick. In native mode, existing odds-change behavior remains compatible.

The browser retains its 60-second fallback polling. SSE is a freshness accelerator, not the only recovery mechanism.

### 3. Move blocking scanner work off the event loop

Scanner routes will execute synchronous database reads, Python normalization, scanner computation, and Pydantic model construction in a bounded worker thread via the framework's threadpool helper. HTTP handlers remain asynchronous and can serve health/status/SSE traffic while the worker is busy.

The worker boundary surrounds the complete synchronous computation, not only the SQLite call, because Python normalization and scanning are also material costs.

A process-wide bounded concurrency guard permits one full-universe scanner rebuild at a time. Identical requests continue to coalesce through the existing single-flight mechanism; different scanner types queue instead of competing for memory and CPU with simultaneous million-row materializations.

### 4. Use targeted odds-page reads

The odds and props routes already know the requested sport and whether they need prop or non-prop markets. The betting-db adapter will expose source-side inclusion/exclusion filters so these routes do not first materialize irrelevant sports or market families.

Filtering must preserve every market belonging to the requested page. The change moves an existing classification predicate toward SQL; it does not create a reduced hard-coded list of market types.

### 5. Instrument the read pipeline

Add structured timing logs for cache misses only, recording:

- source and filter identity;
- returned row count;
- SQLite fetch duration;
- row-mapping duration;
- `rows_to_games` duration;
- scanner duration;
- response-model construction duration; and
- total computation duration.

Slow-operation logs must not contain credentials, JWTs, proxy details, or wager-account data.

## Data Flow

```text
betting-db writer ───────────────┐
                                ├─> read-source fingerprint
direct-book native cache writes ┘          │
                                           ├─> debounced typed SSE event
                                           │        │
browser SWR key <──────────────────────────┘        │
       │                                            │
       └─> FastAPI route ─> single-flight/concurrency guard
                               │
                               └─> bounded worker thread
                                      ├─> filtered read-only SELECT
                                      ├─> normalization
                                      ├─> scanner
                                      └─> response model
```

## Failure Handling

- An unreadable betting-db remains a loud request failure; it must not silently fall back to empty odds.
- Worker exceptions propagate through the existing FastAPI error handling and are logged once with operation context.
- If SSE disconnects, EventSource reconnection plus 60-second SWR polling restores freshness.
- If the betting-db fingerprint cannot be read, the request bypasses the result memo rather than serving an indefinitely stale result.
- Concurrency waiting is bounded. A request that cannot acquire scanner capacity within the configured timeout returns HTTP 503 with a retryable message instead of freezing the server.

## Testing Strategy

### Unit tests

- Betting-db mode native writes produce debounced `direct_books_changed` events.
- Native mode retains compatible invalidation behavior.
- Multiple writes inside 15 seconds advance the direct-book generation once.
- A later write after the window advances it again.
- Scanner fingerprint changes when betting-db state changes or the debounced direct-book generation changes.
- Sport and prop/non-prop filters preserve representative mainline, alternate, first-five, and player-prop markets.
- Scanner concurrency guard serializes different full-universe rebuilds while identical requests coalesce.

### Integration tests

- Start one deliberately slow scanner computation and verify `/api/health` responds before it completes.
- Fire concurrent identical scanner requests and assert the underlying computation runs once.
- Verify typed SSE events revalidate only expected SWR key prefixes.
- Compare filtered route results with the pre-change Python-filtered result set using fixtures containing all supported market families.

### Live verification

Run against the configured read-only betting-db without changing `cache_mode`:

- cold and warm `/api/odds/mlb` timing;
- cold and warm `/api/low-hold` timing;
- `/api/health` latency while low-hold is rebuilding;
- browser load of Odds and Edges pages;
- browser/network inspection confirming scanner requests are no longer emitted once per second;
- server logs confirming scheduler missed-run warnings do not spike during page loads.

## Acceptance Criteria

- `/api/health` completes in under 500 ms while a scanner rebuild is active on the development machine.
- No mounted page causes the same scanner endpoint to refetch more than once per 15 seconds from SSE updates.
- Concurrent identical scanner requests execute one underlying computation.
- Odds and Edges pages render successfully from `ODDS_SOURCE=betting_db` and remain interactive during refresh.
- Representative market-family parity tests show no silently dropped market types.
- Existing server tests pass except the documented pre-existing `test_three_way_markets_are_skipped` failure.
- Web type checking introduces no errors beyond the documented pre-existing errors under `web/app/bets/`.

## Follow-Up Deliverable

After stabilization is verified, design and implement betting-db-owned materialized current/result tables. That design will define table ownership, atomic refresh semantics, schema versioning, freshness metadata, site compatibility during rollout, and rollback. Once deployed, betting-site scanner endpoints will become indexed result-table reads instead of request-time analytical computations.
