# Persistent Systems Context Cache Design

## Goal

Complete the forward-looking Systems evaluator with the remaining MLB, college-football, NFL, and weather context while avoiding repeated provider requests and repeated derivation work on every page load.

The implementation must remain free by default. It must never switch `cache_mode` to `live` or spend Odds API credits.

## Current problem

The Systems endpoint currently reads current odds and enriches games on demand. A five-minute in-process cache reduces some duplicate MLB requests, but it is lost on restart and does not cache individual source payloads or derived values. Football weather and several NFL fields have no provider. A single slow source can make a request wait, and the endpoint repeats evaluation even when neither odds nor context has changed.

## Architecture

Add a persistent SQLite context cache and split context acquisition into provider adapters. Each adapter reads cached source data first, refreshes only expired entries, derives normalized fields, and returns additions keyed by odds event ID.

The Systems endpoint will also cache its final response in memory using a fingerprint composed of the requested date, timezone, current odds-cache version, and context-cache generation. Repeated requests with the same fingerprint return the same analysis without rereading or rederiving context. The response cache expires after 30 seconds even if the fingerprint is unchanged.

Provider failures are isolated. A failed refresh uses a previously successful stale entry when available and emits a warning containing the provider, age, and refresh failure. It never replaces good cached data with an error or empty payload.

## Persistent schema

Create `system_context_cache` in the existing odds-cache SQLite database:

```sql
CREATE TABLE IF NOT EXISTS system_context_cache (
    provider TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_timestamp TEXT,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_error TEXT,
    PRIMARY KEY (provider, cache_key, effective_date)
);
```

Create `system_context_meta` for a monotonic cache generation:

```sql
CREATE TABLE IF NOT EXISTS system_context_meta (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
```

Every successful payload insert or material payload change increments the `generation` value. Error-only updates do not increment it.

All cache operations use parameterized SQL and short-lived connections. JSON serialization uses sorted keys for deterministic equality checks. Date-specific historical entries may share the same database indefinitely because they are small and valuable for future signal audits.

## Cache behavior

The cache exposes one async operation:

```python
async def get_or_refresh(
    provider: str,
    cache_key: str,
    effective_date: date,
    ttl: timedelta,
    loader: Callable[[], Awaitable[dict]],
    *,
    allow_stale: bool = True,
) -> CachedContext
```

`CachedContext` contains `payload`, `fetched_at`, `expires_at`, `is_stale`, and an optional warning.

Behavior:

1. A fresh row returns immediately without calling the loader.
2. A missing or expired row invokes the loader once per process/key using an async keyed lock.
3. A successful loader result is persisted and returned.
4. A failed loader with a prior successful row returns that stale payload and a warning.
5. A failed loader without prior data returns an empty payload and a provider-specific warning.
6. Empty successful payloads are valid only when the adapter explicitly marks them authoritative; transport errors are never cached as successful empties.

## Provider adapters

### MLB schedule and results

- Source: MLB Stats schedule endpoint.
- Cache key: the requested date range.
- Current/future schedule TTL: 5 minutes.
- Completed dates: immutable after a 12-hour settlement delay; cache indefinitely.
- Lookback: 35 days, enough to recover complete prior series boundaries, road trips, streaks, and previous results without relying on a fixed 12-day assumption.
- Join teams by MLB team ID. Display names are labels only.

Derived fields:

- previous runs scored and run margin;
- previous-game venue;
- winning and losing streaks;
- current series game number and scheduled length;
- series losses before the current game;
- whether the opponent is playing its first home game after a road trip;
- whether the road team was swept in its immediately preceding completed home series.

A sweep requires a completed multi-game series where the team was home for every counted game, lost every played game, and the next game belongs to a different series. Postponements and standalone makeup games do not count as a sweep unless MLB identifies them as part of that series.

### MLB standings and season calendar

- Source: MLB Stats standings and schedule endpoints.
- Standings TTL: 15 minutes.
- Team/division alignment TTL: 24 hours, keyed by season.
- All-Star break dates: derive from the season schedule rather than month inference; cache for the season.

Derived fields:

- pregame winning percentage for both teams;
- season-specific divisional relationship;
- exact `after_all_star_break` value.

### College-football schedule and classification

- Source: ESPN college-football scoreboard and team metadata endpoints.
- Schedule TTL: 15 minutes.
- Team/conference classification TTL: seven days, keyed by season.
- Matching: normalized home/away team pair plus scheduled-date tolerance. ESPN event ID is retained in cached metadata.

Derived fields:

- Week 0/1 value;
- confirmed FBS status;
- season-aware Power 4 or Group of 5 classification.

Unknown teams or games absent from the schedule remain `UNABLE_TO_EVALUATE`; they cannot trigger an FBS system. Independents have an explicit `independent` classification and never silently count as Power 4 or Group of 5.

### Football venue and weather

- Venue source: ESPN event/venue metadata.
- Geocoding source: Open-Meteo geocoding API.
- Forecast source: Open-Meteo forecast API.
- Venue coordinates TTL: indefinite unless the venue identity changes.
- Forecast TTL: 15 minutes until kickoff; no refresh after the game begins.

Use the hourly forecast nearest scheduled kickoff at the stadium coordinates. Store temperature in Fahrenheit and sustained 10-meter wind in mph. Do not use gusts. Indoor venues return no qualifying outdoor weather values and explicitly set `weather_applicable: false`.

Derived fields:

- `temperature_f`;
- `sustained_wind_mph`;
- venue and forecast source timestamps.

### NFL schedule, division, and week

- Source: ESPN NFL scoreboard and team metadata.
- Schedule TTL: 15 minutes.
- Division alignment TTL: seven days, keyed by season.

Only regular-season games can qualify Football 6 and Football 12. Preseason and postseason games evaluate as no-match rather than missing when the season type is known.

Derived fields:

- regular-season week;
- season type;
- season-aware divisional relationship.

### NFL previous-season playoffs

- Source: prior-season ESPN postseason scoreboard.
- Cache key: prior season.
- TTL: indefinite after the Super Bowl is final.

The set contains every team that participated in the prior postseason. Football 12 tests the current road team against that cached set.

### NFL head coaches

- Source: a current team staff page or feed that exposes an attributable head-coach value. ESPN team news text is not an authoritative coach source.
- TTL: 24 hours during the season and seven days during the offseason.
- Store team ID, coach name, source URL, source timestamp, and effective date.

If a structured provider cannot confirm the coach, Football 7 stays unable to evaluate. The implementation must not hardcode Baltimore or infer a coach from news text. A season-dated local override is allowed only when it contains the same attribution fields and is visibly marked as an override.

## Evaluation behavior

Every CFB rule requires `is_fbs_game == true`. An explicitly false value is a no-match for that game. An unknown value is missing context.

System-level status follows coverage:

- `qualified`: at least one upcoming game qualifies;
- `no_match`: every applicable upcoming game was fully evaluated and none qualified;
- `unable_to_evaluate`: at least one potentially applicable game lacks a required field and no game qualified;
- `disabled`: source rule remains intentionally inactive.

The response will add optional coverage metadata with evaluated-game and skipped-game counts so the UI can distinguish a genuine no-match from partial coverage.

## Response caching and invalidation

Add a 30-second in-process Systems response cache. Its key contains:

- requested date;
- timezone;
- odds cache version/fingerprint for MLB, NCAAF, and NFL mainlines;
- persistent context-cache generation.

A changed price, line, event, schedule payload, weather payload, or derived context entry creates a new key. A browser refresh within the same unchanged 30-second window returns the cached response. Signal persistence remains idempotent and runs only when a newly computed response contains signals.

No full response is persisted across process restarts; persistent source/context rows make recomputation after restart inexpensive.

## Concurrency and performance

Independent provider requests run concurrently with bounded timeouts. Requests for the same provider key share one in-flight async task. SQLite reads happen before network work and never hold a transaction across an await.

Targets on the existing machine:

- unchanged warm Systems request: under 250 ms;
- changed-odds request with fresh context rows: under 1 second;
- cold request: bounded by provider timeouts and returns partial/stale data rather than waiting for every failed source;
- no duplicate network call for the same provider key during concurrent page loads.

## Error reporting

Warnings name the provider and failure type. Blank exception strings use the exception class name. When stale data is served, the warning includes its age. The UI continues to show missing fields for genuinely unavailable context.

Provider payloads and warnings must not include credentials. These sources require no paid keys.

## Testing

Backend tests cover:

- fresh cache hit without loader execution;
- expired refresh and generation increment;
- stale-on-error behavior;
- concurrent request coalescing;
- MLB team-ID joins and previous-home-series sweep derivation;
- exact All-Star break boundary;
- FBS/P4/G5/independent classification;
- exclusion of unconfirmed or FCS events;
- venue geocoding and nearest-kickoff weather selection;
- sustained wind rather than gusts;
- NFL regular-season week/division and preseason exclusion;
- previous-season playoff membership;
- coach source attribution and expiration;
- response-cache hit and invalidation from odds/context changes.

Integration verification runs the endpoint twice: the first response may load providers, while the second must reuse cache and satisfy the warm-response target. Existing Systems evaluator, store, and API tests remain green.

## Operational constraints

- Do not switch `cache_mode` to `live`.
- Do not call a paid Odds API endpoint.
- Use point-in-time values and retain source timestamps.
- Never replace known context with fabricated defaults.
- Keep incomplete Football 8, Football 11, and Football 13 disabled.
- Preserve all analytical matches while deduplicating execution-layer wagers.
