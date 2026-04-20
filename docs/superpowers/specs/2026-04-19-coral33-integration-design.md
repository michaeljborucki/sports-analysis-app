# coral33.com Integration — Design Checkpoint

**Date:** 2026-04-19
**Status:** Design approved, pre-implementation
**Goal:** Mirror coral33.com sportsbook odds into our existing cache as a new book (`coral33`), so they appear alongside Odds API books in the odds grid, arbitrage, low-hold, and free-bet scanners.

---

## Scope — This Round

**Sports:** NBA, NHL, MLB, tennis, NCAA baseball
**Markets:** main lines (ML / spread / total / team totals) + periods (quarters/halves/periods) + alternates
**Deferred:** player props, game props, series markets — need a live probe to understand response shape

---

## Architecture

Pure HTTP integration — **no browser automation.** coral33 exposes a form-encoded JSON API. We use `httpx.AsyncClient` with the same async pattern as `server/odds/client.py`.

### Auth flow
1. `POST /cloud/api/System/authenticateCustomer` with form body:
   ```
   customerID=VR12509   &password=****&domain=coral33.com
   &operation=authenticateCustomer&RRO=1&response_type=code
   &client_id=<id>&multiaccount=1
   ```
2. Response contains a JWT (stored in-memory on the client instance).
3. All subsequent calls include `customerID`, `token=<JWT>`, `operation=<endpoint>`, `office=LEOOFFICE`, `agentSite=0` in the form body.
4. On `401` or token-invalid response, re-authenticate and retry once.
5. Credentials in `.env`: `CORAL33_CUSTOMER_ID`, `CORAL33_PASSWORD`.

### Captcha gating
Responses include `CaptchaRequired: bool`. When `true`, back the scraper tier off to 5 min and log a warning. If sustained, disable the book until manual intervention.

---

## File Structure

```
server/odds/books/coral33/
  __init__.py
  client.py          # Coral33Client — auth, token refresh, raw POSTs
  mapping.py         # Per-sport endpoint tuples + market key mapping
  event_matcher.py   # (sport, home, away, commence) → existing Odds API event_id
  normalizer.py      # coral33 row → list[NormalizedOddsRow]
  fetcher.py         # Coral33Fetcher — schedules per-sport pulls
server/config/
  coral33.toml       # Per-sport endpoint lists, cadences, team-name aliases
```

`Coral33Fetcher` is owned by `FetcherRegistry` (new field alongside the Odds API scheduler) so the existing `start_all` / `stop_all` / `hot_reload` controls govern it too.

---

## Event Matching (the key design call)

coral33's `GameNum` ≠ Odds API UUIDs, so we must match to existing events or the book never joins best-odds / arbitrage computations.

### Algorithm

```
match_event(sport_key, coral_home, coral_away, coral_commence, cache):
    candidates = cache.events_for_sport(sport_key)
    for c in candidates:
        if teams_match(coral_home, c.home, coral_away, c.away):
            if abs(coral_commence - c.commence_time) <= timedelta(minutes=10):
                return c.event_id
    return None  # orphan — row is dropped
```

### Team name normalization

- Lowercase, strip punctuation/extra whitespace.
- Maintain an alias map in `server/config/coral33.toml` (sparse — only where coral33 and Odds API disagree):
  ```toml
  [team_aliases.nba]
  "la clippers" = "los angeles clippers"
  ```
- Built empirically: log unmatched games and add aliases as needed. (Most majors will match identity.)

### Orphan handling

If no match found: **drop the row**, log at `info` level with the coral33 GameNum and team names. Orphan rate is our health metric — if it's high on a given tier, the alias map needs work. Never write orphan events to the cache — it pollutes arbitrage output with books that can't be compared.

### Commence-time window: 10 minutes

Generous enough to absorb schedule drift between providers, tight enough that back-to-back games don't collide. If we see collisions (rare — same two teams rarely play twice in a 20-min window), tighten.

---

## Market Shape Mapping

### `Get_LeagueLines2` response per game

Their row is flat — every market embedded as columns. Decoding per `(sportType, sportSubType, period)`:

#### Main game lines (Game period)

| coral33 fields | Our rows |
|---|---|
| `MoneyLine1`, `MoneyLine2` | `h2h` / team1 name / — / ML1,  `h2h` / team2 / — / ML2 |
| `Spread` + `FavoredTeamID` + `SpreadAdj1`/`SpreadAdj2` | `spreads` / team1 / ±Spread / Adj1,  `spreads` / team2 / ∓Spread / Adj2 |
| `TotalPoints` + `TtlPtsAdj1`/`TtlPtsAdj2` | `totals` / Over / TotalPoints / Adj1,  `totals` / Under / TotalPoints / Adj2 |
| `Team1TotalPoints` + `Team1TtlPtsAdj1`/`Team1TtlPtsAdj2` | `team_totals` / team1 Over / pt,  `team_totals` / team1 Under / pt |
| `Team2TotalPoints` + `Team2TtlPtsAdj1`/`Team2TtlPtsAdj2` | `team_totals` / team2 Over / pt,  `team_totals` / team2 Under / pt |
| `MoneyLineDraw` + `MoneyLineDecimalDraw` | 3rd outcome in `h2h_3_way` (soccer only) |

#### Spread sign convention

- `FavoredTeamID == Team1ID` → team1_point = `Spread` (negative), team2_point = `-Spread`.
- `FavoredTeamID == Team2ID` → team1_point = `-Spread` (positive), team2_point = `Spread`.
- `SpreadAdj1` is the price for Team1's line, `SpreadAdj2` for Team2's.

#### Price handling

- Use `*Adj*` American odds as canonical. Ignore `Decimal`/`Numerator`/`Denominator` duplicates.
- Skip any market where the `Adj` value is `0` or missing (market not posted).
- Skip rows with `Status != 'O'` (C = circled/closed).

### Period markets → market-key suffix

| coral33 period | our suffix | applies to |
|---|---|---|
| `Game` | (none) | `h2h`, `spreads`, `totals`, `team_totals` |
| `1st Half` | `_h1` | `h2h_h1`, `spreads_h1`, `totals_h1`, `team_totals_h1` |
| `2nd Half` | `_h2` | … |
| `1st Quarter` … `4th Quarter` | `_q1` … `_q4` | NBA only |
| `1st Period` … `3rd Period` | `_p1` … `_p3` | NHL only (**new suffix** — NHL config currently uses custom names; align) |
| `1st 5 Innings` (MLB) | `_f5` | (confirm current MLB tier naming) |

**Naming rework noted:** NHL's current `markets.nhl.toml` may use different period suffixes than `_p1/_p2/_p3`. Audit and align so coral33 rows land in the same market_key as Odds API NHL periods.

### Alternate lines — bounded, not open-ended

Unlike mainstream books (DK/FD) that post 20+ alt points per market, coral33 posts a **fixed small count of alts per sport.** Each alt is effectively a "one step off the main line, both directions."

**MLB:**
- Main spread: favorite at `-1.5` (standard run line)
- Alt spreads: one at `-2.5` (favorite, harder), one at `+1.5` (underdog, easier). **2 alt rows per game.**
- Alt totals: **1 alt total per game** (one step off the main total, direction TBD — confirm with example)

**NHL:**
- Main spread: puck line `±1.5`
- Alt spreads: usually around `±0.5` and `±2.5` (5 each way per user — ~~confirm~~ clarify tomorrow). **2 alt rows per game.**
- Alt totals: **1 alt total per game**

**NBA:**
- Main spread: standard game spread
- Alt spreads: **2 alt rows per game** (one step each direction)
- Alt totals: **2 alt totals per game**

**Implication:** response shape is likely flat fields (`AltSpread1Point`, `AltSpread1Adj1/2`, `AltSpread2Point`, …) rather than an unbounded array. Normalizer iterates a small named-field list per sport, not an array walk. Still maps to our existing `alternate_spreads` / `alternate_totals` market keys — one row per (point, outcome).

**Competitive note:** coral33's alt universe is narrow vs. DK/FD. Still useful for arbitrage/free-bet hedges when their alt price is off-market, but not a deep alt-line source.

**Deferred:** exact field names — waiting on examples from user tomorrow.

---

## Sport → Endpoint Mapping (config-driven)

```toml
# server/config/coral33.toml

[sports.nba]
sport_type = "BASKETBALL"
subtypes_main = ["NBA"]
subtypes_alt  = ["NBA+ALT+LINE"]
subtypes_prop = ["NBAPLAYERPRO"]  # deferred
periods       = ["Game", "1st Half", "2nd Half", "1st Quarter", "2nd Quarter", "3rd Quarter", "4th Quarter"]

[sports.nhl]
sport_type = "HOCKEY"
subtypes_main = ["NHL"]
subtypes_alt  = ["HOCKEY+ALTER"]
periods       = ["Game", "1st Period", "2nd Period", "3rd Period"]

[sports.mlb]
sport_type = "BASEBALL"
subtypes_main = ["MLB"]
subtypes_alt  = ["MLB+ALT+LINE"]  # confirm with probe
periods       = ["Game", "1st 5 Innings"]  # plus any others discovered

[sports.tennis]
sport_type = "TENNIS"
subtypes_main = []  # populate after probe — each ATP/WTA tour may be its own subtype
periods       = ["Game"]

[sports.baseball_ncaa]
sport_type = "BASEBALL"
subtypes_main = ["NCAABASEBALL"]
periods       = ["Game"]
```

Empty/unconfirmed lists get populated via a probe script before first production tick.

---

## Cadence

One APScheduler job per `(sport, tier)`, independent of the Odds API scheduler:

| Tier | Interval | Rationale |
|---|---|---|
| main + periods | 60s | Match Odds API main cadence |
| alternates | 90s | Lower priority, reduces load |
| player props | 180s (deferred) | Expensive, less time-sensitive |
| captcha backoff | 300s | Set when `CaptchaRequired=true` |

Total request volume roughly: (5 sports × 1 main + avg 3 periods + 1 alt call) ≈ 25 endpoint calls per 60s tick. Well below any plausible rate limit on a residential user account.

---

## Integration Points

- **`BOOK_ORDER`** — add `coral33` to `server/odds/books.py` (or wherever the list lives) and to `web/lib/books.ts`.
- **Logo** — add `coral33.png` to the books asset directory. Source: coral33.com favicon or a generic square.
- **Commissions** — `coral33` = 0% (not an exchange). Add to `commissions.py` as explicit entry.
- **Settings page** — add per-sport `coral33` toggle alongside existing books? **Deferred** — not a true market toggle, just a source toggle. Likely a single "coral33 enabled" master toggle in a new "Sources" section.

---

## Open Questions / Deferred

- [ ] Exact response shape for `NBAPLAYERPRO` / `MLBPLAYERPRO` (player props)
- [ ] Exact response shape for alternate-lines endpoints (one row per alt or one row with arrays?)
- [ ] Tennis subtypes (ATP/WTA tour breakdown in coral33)
- [ ] Soccer/other sports (`MEX+-+PR+DIV`, `CR+PRI+DIV` seen in HAR — not in our current sports list)
- [ ] Token TTL — HAR only shows login once; don't know refresh cadence. Assume 401-and-retry pattern works.
- [ ] Rate-limit headers — probe for any `X-RateLimit-*` headers on response.

---

## Build Order (task list)

1. Create directory + empty modules
2. Add `.env` vars to `Config`, add `coral33` to `BOOK_ORDER`, commissions, logo
3. `Coral33Client` — auth + `post_form(operation, params)` helper + 401 retry
4. Smoke test: login from a script, call `Get_SportsLeagues`, print league count
5. `mapping.py` — per-sport endpoint lists + period→suffix function
6. `event_matcher.py` — with alias map read from `coral33.toml`
7. `normalizer.py` — main + period response → rows. Unit test with HAR fixture.
8. `Coral33Fetcher` — one tier for main+periods, one for alts. Writes via `cache.upsert`.
9. Wire into `FetcherRegistry.start_all`. Honors `user_settings` disabled-sports.
10. Live tick — verify NBA rows appear in cache, compare to Odds API rows for same game.
11. Alternates — probe live response, extend normalizer.
12. Commit, ship.

---

## Revert plan

Everything new lives in `server/odds/books/coral33/` + `server/config/coral33.toml` + 3 `.env` vars + 1 entry in `BOOK_ORDER`. To revert: delete the directory, remove the `coral33` book from `BOOK_ORDER` and commissions, unregister the fetcher from `FetcherRegistry`. No schema changes, no DB migration, no UI changes (book just appears/disappears in the filter).
