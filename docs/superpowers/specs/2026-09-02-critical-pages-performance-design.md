# Critical Pages Performance Design

**Date:** 2026-09-02

## Objective

Make the betting application responsive enough for routine use, prioritizing
the pages in this order:

1. Edges
2. Accounts
3. Systems
4. Odds

Optimize the existing Python, FastAPI, Next.js, and SQLite architecture first.
Add a dedicated latest-odds serving layer inside the FastAPI process. Do not
combine this project with the proposed monorepo migration or a Go rewrite.

Only the MLB `baseball-agents` pipeline is operationally relevant. The other
sport-agent repositories are outside this project's scope. This does not mean
that non-MLB odds must disappear from the site; it means performance work must
not preserve or optimize unused non-MLB prediction-agent integrations.

## Measured Baseline

Measurements on the running local application established the following:

- Initial dashboard DOM load: approximately 16 seconds.
- `GET /api/dashboard`: 14.75 seconds.
- Dashboard response size: approximately 1.19 MB.
- An unrestricted betting-db read returned approximately 170,000 mapped rows.
- Individual unrestricted reads took approximately 5 to 10.7 seconds.
- `betting-db/data/odds.db` was approximately 1.0 GB.
- `betting-db/data/odds.db-wal` was approximately 480 MB.
- `betting-site/server/cache.db` was approximately 444 MB.
- `latest_odds` contained approximately 1.33 million physical rows.
- Foreground reads coincided with delayed APScheduler jobs and degraded
  unrelated requests.

The Edges page can issue five scanner requests in one load: arbitrage,
low-hold, EV, free-bet conversion, and profit boost. Those endpoints can each
materialize and normalize the same odds universe. Existing endpoint-local
caches do not prevent distinct scanners from duplicating that work.

These measurements indicate a data-access, duplicate-computation, event-loop,
and payload-shaping problem. They do not justify a language rewrite.

## Success Criteria

Measure both cold and warm behavior from a real browser against the locally
running services.

### Edges

- All enabled modes render usable results within 1 second on a warm snapshot.
- A cold application start renders enabled modes within 2 seconds once a first
  snapshot is available.
- One page load performs no more than one source snapshot refresh.
- Parallel scanner requests never initiate duplicate SQLite source scans.

### Accounts

- Current balances and twelve-week history render within 500 ms under normal
  cached operation.
- Opening the bets tab does not perform one SQLite closing-line query per bet.
- Ordinary page loads never wait for Coral33 authentication or remote network
  requests.
- Manual refresh remains asynchronous and clearly reports freshness/error
  state.

### Systems

- A cached Systems request completes within 500 ms.
- A cold evaluation with already-available context completes within 1 second.
- MLB Stats or football context network requests never block an ordinary page
  request.
- Context age and refresh failures remain visible; stale data is not silently
  represented as fresh.
- Existing system rules, including all market types, retain their behavior.

### Odds

- An MLB odds page becomes usable within 1 second on a warm snapshot.
- The request reads only the selected sport and needed market family.

### Runtime

- `GET /api/health` completes within 100 ms under foreground page load.
- Foreground requests do not cause scheduler jobs to miss their normal cadence.
- The serving layer meets the approximately one-minute freshness requirement.
- Memory remains bounded to the current serving snapshot plus one replacement
  snapshot during an atomic refresh.

## Architecture

### Source and serving layers

`betting-db/latest_odds` remains the durable current-value source for Odds API
books. `betting-site/server/cache.db` remains the source for directly polled
Coral33, Kalshi, and Polymarket rows.

FastAPI gains one application-scoped `LatestOddsSnapshotService`. It builds an
immutable, indexed serving snapshot in a worker thread and swaps it atomically
when complete. Request handlers never build this snapshot and never wait for a
refresh when an earlier usable snapshot exists.

The snapshot contains:

- Source generation/fingerprint and build timestamps.
- Rows partitioned by application sport.
- Rows partitioned into mainline/non-prop and prop families.
- Event indexes.
- Market indexes needed by the current scanners.
- A normalized game representation shared by all scanner endpoints.
- Direct-book rows overlaid with the existing direct-book-wins collision rule.

Only the current snapshot and the snapshot under construction may be retained.
Snapshots and nested values are treated as read-only after publication.

### Refresh behavior

The service refreshes in the background when either source changes, subject to
a short coalescing window so high-frequency direct-book writes do not cause
continuous rebuilds. Only one build may run at a time.

Request behavior is stale-while-revalidate:

- If a usable snapshot exists, return it immediately and refresh separately.
- If no snapshot exists during startup, allow one coordinated initial build;
  concurrent requests await the same build rather than starting their own.
- If a build fails, retain the prior snapshot, record the error, and expose its
  age.
- If snapshot age exceeds the configured hard freshness limit, APIs must expose
  a stale warning or fail explicitly according to their existing contract.
  They must not silently emit apparently current betting opportunities.

No Redis or additional network service is introduced initially. The snapshot
service defines an interface that can later be moved behind a Go or standalone
service only if post-optimization profiling proves that necessary.

## Page Designs

### Edges

Arbitrage, low-hold, EV, free-bet, and profit-boost scanners consume the same
published normalized snapshot. They retain independent result caches because
their user parameters differ, but result-cache invalidation keys use the
snapshot generation rather than the native cache's broad mutation counter.

Scanner computations continue to run outside the event loop. Simultaneous
identical requests use the existing coalescing behavior. Distinct scanner
requests share source data and normalization even though their calculations
remain independent.

The initial frontend API contracts stay unchanged. A combined Edges endpoint is
not required for the first rollout; it can be evaluated later if five HTTP
responses remain materially expensive after backend duplication is removed.

Player props remain EV-scanner-only. No optimization may route props into
arbitrage or silently remove supported mainline, first-five, or total markets.

### Accounts

Accounts uses a separate `AccountRollupService`; it does not depend on the odds
snapshot for balances or history.

The service precomputes current rollups and twelve-week history after Coral33
refreshes and after persisted balance/wager-log changes. Ordinary GET requests
read the last successful rollup from memory or local persistence. They do not
authenticate with Coral33.

The bets-tab CLV path replaces per-bet lookups with a batch query/index keyed by
the event, market, outcome, and relevant close time. The response preserves
`null` when CLV is unavailable.

Manual account refresh continues to trigger asynchronous work and returns
immediately. The page exposes captured time, refresh-in-progress state, and
per-account errors from the last refresh.

### Systems

Systems consumes mainline rows from the latest-odds snapshot. Context acquisition
is separated from evaluation:

- MLB schedule, standings, series state, and prior results refresh in a
  background context service with explicit timestamps and errors.
- Football context may remain registered for existing system visibility, but
  it must not be fetched or evaluated when the requested games contain no
  relevant football events.
- A Systems request combines the current odds snapshot with the newest usable
  context snapshot and performs deterministic evaluation locally.
- The response cache keys on odds snapshot generation, relevant context
  generation, requested date/timeframe, and timezone.

Broad native-cache updates that do not affect the relevant odds or context must
not invalidate a Systems response. Signal persistence remains best-effort and
must not delay the response path.

### Odds

Odds endpoints consume the serving snapshot's sport and market-family indexes.
They must not materialize all sports or props before filtering. Existing
alternate-line and direct-book behavior remains intact, including Coral33
`wager_type` and ASK-side prediction-market pricing.

## Database Work

Before adding indexes, capture `EXPLAIN QUERY PLAN` and wall-clock measurements
for the exact live queries. Add only indexes justified by those plans.
Candidate indexes include combinations of sport, market, commence time, and
fetched time, but final column order must follow measured predicates and
selectivity.

Review WAL growth and checkpoint behavior in `betting-db`. Any checkpoint
change must preserve writer safety and must be tested against concurrent
read-only consumers. Archival remains digest-verified before deletion.

The existing `latest_odds` table is already a current-value materialization; it
is not replaced with another redundant durable table unless measurements show
that an independently shaped table is necessary. Phase 2 primarily adds a
serving snapshot optimized for application access.

## Instrumentation

Add structured duration and size metrics at these boundaries:

- Source SQLite query
- Direct-book query
- Row mapping and collision overlay
- Snapshot indexing and normalization
- Individual scanner calculation
- Context refresh and Systems evaluation
- Account rollup and batch CLV lookup
- Pydantic serialization
- Endpoint total duration and response bytes where available

Logs must identify snapshot generation and whether a request was a snapshot hit,
initial-build wait, or stale serve. Metrics must not log credentials, JWTs,
account secrets, or private keys.

## Delivery Sequence

1. Add reproducible browser/API performance measurements and server timing
   instrumentation.
2. Push existing dashboard and odds filters into current SQL paths where this
   produces an immediate measured improvement.
3. Implement the snapshot service with atomic publication, bounded retention,
   single-flight startup, and freshness reporting.
4. Move Edges source reads and normalization onto the snapshot.
5. Implement account rollup caching and batched CLV lookup.
6. Implement background Systems context snapshots and generation-aware caching.
7. Move Odds endpoints onto indexed snapshot views.
8. Measure all acceptance targets in the browser and under a parallel request
   burst.
9. Remove superseded endpoint-local source caches only after parity is proven.

Each step must use regression tests and preserve a rollback path. Performance
work must be landed in small stages so a page-load regression halts the rollout
without stranding unrelated changes.

## Testing

- Unit tests for snapshot partitioning, overlay collision rules, generations,
  bounded retention, and stale/error behavior.
- Concurrency tests proving multiple requests cause one initial build.
- Integration tests against temporary betting-db and native-cache SQLite files.
- Scanner parity tests comparing old and snapshot-backed results from the same
  fixture, including first-five markets and props boundaries.
- Accounts tests proving cached GETs perform no Coral33 network work and CLV is
  batch-loaded.
- Systems tests proving context refresh is not request-blocking and irrelevant
  cache mutations do not invalidate results.
- Browser verification of Edges, Accounts, Systems, and Odds in priority order.
- Load tests for simultaneous Edges modes while health and scheduler work remain
  responsive.

## Rollout and Rollback

Introduce the serving layer behind an environment flag while parity and latency
are verified. The existing betting-db read path remains available during the
transition. Do not change `cache_mode`, enable the site's Odds API fetcher, or
alter real-money placement behavior.

After the snapshot path meets correctness and performance targets, make it the
default and retain the legacy path for one short rollback window. Remove the
legacy path only in a separately approved cleanup.

## Explicit Non-Goals

- Rewriting FastAPI or betting-db in Go.
- Migrating repositories into a monorepo.
- Activating or optimizing non-MLB prediction-agent pipelines.
- Changing betting rules, Kelly interpretation, or wager placement behavior.
- Adding Redis or another externally managed service before profiling proves a
  need.
- Changing Odds API spend gates or enabling any metered fetch path.
