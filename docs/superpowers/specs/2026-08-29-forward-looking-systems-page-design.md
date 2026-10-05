# Forward-Looking Systems Page Design

## Goal

Add a global **Systems** tab that evaluates the application's upcoming MLB, CFB, and NFL games against the 25 primary betting systems, displays every system's evaluation state, and records newly observed signals from the day this feature ships forward.

## Scope

- Evaluate only games whose scheduled start is after the evaluation timestamp and whose local date is the requested date in `America/Denver`.
- The default requested date is today. This release is not a historical backtester.
- A rule may inspect the minimum prior context it explicitly requires: a previous game, current record or streak, current series state, current alignment, prior-season playoff status, active coach, and game-time weather.
- Persist qualifying signals with the exact evaluated market line and timestamp. Outcome grading is outside this release.
- Show all 25 primary systems. Football 2B is a nested subset signal under Football 2 and therefore does not increase the primary-system count.
- Football 8, Football 11, and Football 13 remain disabled because their source rules are incomplete.
- Never trigger an Odds API fetch, change `cache_mode`, or place a bet.

## Architecture

`server/systems/registry.py` owns immutable system definitions and source-claim metadata. `server/systems/evaluator.py` is a pure rule engine that accepts normalized upcoming games plus point-in-time context. It returns one evaluation per primary system and zero or more qualifying signals. Missing inputs produce `unable_to_evaluate`, never `no_match`.

`server/systems/context.py` assembles free/current context. Current prices always come from `OddsCache`; MLB state comes from MLB's public Stats API with short timeouts and an in-memory TTL. Football schedule/alignment and weather are optional context providers: if they cannot supply a required field, only the affected systems become unable to evaluate. Provider failures do not fail the endpoint.

`server/systems/store.py` persists qualifying signals idempotently in SQLite. A stable key includes system ID, event ID, market, selection, point, and evaluation date. Re-evaluation updates the latest line/timestamp without duplicating the sighting.

`GET /api/systems?date=YYYY-MM-DD&timezone=America/Denver` returns the complete registry evaluations, qualifying signals, deduplicated wager candidates, status counts, and freshness. The endpoint reads the cache and context providers only.

The Next.js `/systems` route uses SWR so navigation is immediate and evaluations refresh without a full page reload. It presents qualifying wagers first, followed by the full 25-system audit grouped by sport.

## API contract

Statuses are `qualified`, `no_match`, `unable_to_evaluate`, and `disabled`.

Each system evaluation includes its ID, display name, sport, rule status, source claim, evaluation status, match count, and missing fields. Each signal includes the system identity, event, scheduled time, bet type, selection, line, book, qualification explanation, evaluation timestamp, and supporting IDs. Deduplicated wagers preserve every supporting signal while producing one executable candidate.

## Rule handling

- Strict inequalities and inclusive boundaries follow the master library exactly.
- Football 2B may emit a separate signal when Football 2 qualifies, but the library renders it nested beneath Football 2.
- Football 9/10 and Football 2/2B signals are analytically preserved and execution candidates are deduplicated.
- MLB “-150 or better” means prices from -150 through plus money; “+140 or shorter” excludes prices above +140.
- Second half uses the season's actual All-Star break when supplied by context; it is not guessed.
- Series numbering and sweeps require explicit series metadata. Doubleheaders or makeup games without reliable series metadata remain unable to evaluate for affected systems.

## Interface

The page follows the existing dark trading-desk design and top navigation. Its structure is a compact workbench:

1. Page heading, requested date, last evaluation time, and manual refresh.
2. Status strip for qualifying wagers, qualifying systems, no-match systems, unable systems, and disabled systems.
3. Forward-looking wager table showing matchup, start, system support, market, selection, current line/book, and reason.
4. System audit grouped into MLB, CFB, and NFL with concise status, missing-field disclosure, source claim, and match count.

At phone widths tables become stacked records without horizontal page overflow. Status is never communicated by color alone.

## Error and freshness behavior

- No upcoming cached games yields a valid response with all enabled systems marked unable due to `upcoming_games`, while disabled systems remain disabled.
- A context provider failure is included in `context_warnings`; unaffected line-only systems still evaluate.
- Current odds timestamps are returned per signal. Stale odds remain visible but are marked stale using the application's existing freshness convention.
- Persisting sightings is best-effort after evaluation; a persistence failure is surfaced as a warning and does not hide the live result.

## Testing

- Unit tests cover every implemented boundary and disabled rule.
- Contract tests cover 25 primary evaluations, Football 2B nesting, future-only filtering, missing-field semantics, overlap deduplication, and idempotent persistence.
- API tests prove the endpoint performs no paid fetch or mutation.
- Web type checking/build and browser verification cover loading, empty, qualified, unavailable, mobile, and desktop states.

