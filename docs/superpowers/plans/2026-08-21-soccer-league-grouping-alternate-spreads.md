# Soccer League Grouping and Alternate Spreads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch five-region soccer alternate spreads for near-term matches and present soccer odds in collapsible league sections.

**Architecture:** Preserve the provider competition alongside the app-level sport on each cached odds row, aggregate it onto `Game`, and group only the soccer UI by that metadata. Add a soccer per-event alternates tier and make every per-event tier honor its configured event window.

**Tech Stack:** Python 3.11, FastAPI/Pydantic, SQLite, pytest/pytest-asyncio, Next.js/React/TypeScript, SWR, Node test runner.

**Spec:** `docs/superpowers/specs/2026-08-21-soccer-league-grouping-alternate-spreads-design.md`

## Global Constraints

- Soccer alternate spreads use `us`, `us2`, `us_ex`, `uk`, and `eu`.
- Alternate refresh interval is 300 seconds and the event window is 12 hours.
- App-level `sport_key` remains `soccer`; provider competition is stored separately.
- Missing competition metadata is nullable and renders under `Other Soccer`.
- Other sports retain the current flat odds grid.
- Do not add alternate totals, soccer props, leagues, routes, or dependencies.
- Preserve all unrelated changes in the dirty worktree and stage only task-owned hunks.

---

### Task 1: Soccer alternates configuration and bounded per-event fetching

**Files:**
- Modify: `server/config/markets.soccer.toml`
- Modify: `server/odds/fetcher.py` (`_run_per_event`)
- Modify: `server/tests/test_fetcher.py`
- Create: `server/tests/test_soccer_market_config.py`

**Interfaces:**
- Consumes: `TierConfig.games_window_hours: int | None` from `server/odds/market_config.py`.
- Produces: every non-main tier calls `cache.distinct_events(within_hours_ahead=tier.games_window_hours or 36, sport_key=...)`; soccer exposes an `alternates` tier containing only `alternate_spreads`.

- [ ] **Step 1: Write failing configuration tests**

```python
from server.odds.market_config import MarketConfig


def test_soccer_alternates_cover_all_regions_and_twelve_hours():
    cfg = MarketConfig.load("markets.soccer.toml")
    tier = cfg.tiers["alternates"]
    assert tier.enabled is True
    assert tier.interval_seconds == 300
    assert tier.regions == ["us", "us2", "us_ex", "uk", "eu"]
    assert tier.markets == ["alternate_spreads"]
    assert tier.games_window_hours == 12
```

- [ ] **Step 2: Write the failing fetch-window test**

Add an async test in `test_fetcher.py` that constructs an `alternates` `TierConfig` with `games_window_hours=12`, makes `cache.distinct_events` return `[]`, calls `await reg._run_per_event(sport, tier)`, and asserts:

```python
reg.cache.distinct_events.assert_called_once_with(
    within_hours_ahead=12,
    sport_key="soccer",
)
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run: `.venv/bin/pytest server/tests/test_soccer_market_config.py server/tests/test_fetcher.py -q`

Expected: configuration test fails because `alternates` is absent; fetcher test reports `within_hours_ahead=36`.

- [ ] **Step 4: Implement the configuration and window**

Append to `markets.soccer.toml`:

```toml
[alternates]
enabled            = true
interval_seconds   = 300
regions            = ["us", "us2", "us_ex", "uk", "eu"]
markets            = ["alternate_spreads"]
games_window_hours = 12
```

At the start of `_run_per_event`, replace the hard-coded window with:

```python
window = tier.games_window_hours or 36
events = self.cache.distinct_events(
    within_hours_ahead=window,
    sport_key=sport.key,
)
```

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest server/tests/test_soccer_market_config.py server/tests/test_fetcher.py -q`

Expected: PASS.

```bash
git add server/config/markets.soccer.toml server/odds/fetcher.py server/tests/test_fetcher.py server/tests/test_soccer_market_config.py
git commit -m "feat: fetch soccer alternate spreads"
```

---

### Task 2: Preserve league metadata through normalization and SQLite

**Files:**
- Modify: `server/odds/normalize.py`
- Modify: `server/odds/cache.py`
- Modify: `server/tests/test_cache.py`
- Create: `server/tests/test_soccer_league_metadata.py`

**Interfaces:**
- Consumes: Odds API event fields `sport_key` and `sport_title`.
- Produces: normalized/cache row keys `league_key: str | None` and `league_title: str | None`; `rows_to_games` emits the same keys at game level.

- [ ] **Step 1: Write a failing normalization test**

Create a minimal Odds API fixture with `sport_key="soccer_epl"`, `sport_title="EPL"`, one bookmaker, and one `spreads` outcome. Assert:

```python
rows = normalize_odds_response(fixture, fetched_at=now, sport_key="soccer")
assert rows[0]["sport_key"] == "soccer"
assert rows[0]["league_key"] == "soccer_epl"
assert rows[0]["league_title"] == "EPL"
```

- [ ] **Step 2: Write failing cache migration and round-trip tests**

In `test_cache.py`, assert `PRAGMA table_info(odds_snapshot)` contains `league_key` and `league_title`. Upsert two rows for one event—one row with both values and one with `None`—then assert `all_current("soccer")` retains the values and `rows_to_games(...)` emits:

```python
assert game["league_key"] == "soccer_epl"
assert game["league_title"] == "EPL"
```

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `.venv/bin/pytest server/tests/test_soccer_league_metadata.py server/tests/test_cache.py -q`

Expected: missing row fields/columns and no game-level league metadata.

- [ ] **Step 4: Implement normalization and schema migration**

In `normalize_odds_response`, read provider metadata once per event:

```python
league_key = game.get("sport_key") if sport_key == "soccer" else None
league_title = game.get("sport_title") if sport_key == "soccer" else None
```

Include both values in `base_row`. Add nullable columns to `SCHEMA`, plus idempotent migration statements alongside existing odds migrations:

```sql
ALTER TABLE odds_snapshot ADD COLUMN league_key TEXT
ALTER TABLE odds_snapshot ADD COLUMN league_title TEXT
```

Extend the `INSERT ... ON CONFLICT DO UPDATE` column/value lists so non-empty incoming values win without erasing existing provider metadata:

```sql
league_key = COALESCE(excluded.league_key, odds_snapshot.league_key),
league_title = COALESCE(excluded.league_title, odds_snapshot.league_title)
```

- [ ] **Step 5: Implement aggregation**

When `rows_to_games` initializes a game, include `league_key` and `league_title`. While consuming later rows, fill either field only when the game value is empty and the row value is non-empty. This lets Odds API metadata enrich a game even if a Coral33 row is encountered first.

- [ ] **Step 6: Run tests and commit**

Run: `.venv/bin/pytest server/tests/test_soccer_league_metadata.py server/tests/test_cache.py -q`

Expected: PASS.

```bash
git add server/odds/normalize.py server/odds/cache.py server/tests/test_cache.py server/tests/test_soccer_league_metadata.py
git commit -m "feat: preserve soccer league metadata"
```

---

### Task 3: Extend the API contract

**Files:**
- Modify: `server/models.py`
- Modify: `server/tests/test_api.py`
- Regenerate: `web/openapi.json`
- Regenerate: `web/types/api.d.ts`

**Interfaces:**
- Consumes: game dictionaries containing nullable league metadata.
- Produces: `Game.league_key: str | None` and `Game.league_title: str | None` in FastAPI and generated TypeScript types.

- [ ] **Step 1: Write a failing API schema test**

Extend `test_openapi_schema_accessible` or add a focused test:

```python
game = r.json()["components"]["schemas"]["Game"]
assert "league_key" in game["properties"]
assert "league_title" in game["properties"]
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `.venv/bin/pytest server/tests/test_api.py::test_openapi_game_includes_league_metadata -q`

Expected: FAIL because both properties are absent.

- [ ] **Step 3: Add nullable model fields**

Add to `Game`:

```python
league_key: str | None = None
league_title: str | None = None
```

- [ ] **Step 4: Run backend test and regenerate clients**

Regenerate from the running FastAPI schema:

```bash
curl -sS http://127.0.0.1:8000/openapi.json -o web/openapi.json
cd web
npx openapi-typescript openapi.json -o types/api.d.ts
cd ..
```

Verify generated `web/types/api.d.ts` defines both fields as nullable/optional according to the generator.

Run: `.venv/bin/pytest server/tests/test_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/models.py server/tests/test_api.py web/openapi.json web/types/api.d.ts
git commit -m "feat: expose soccer league metadata"
```

---

### Task 4: Add deterministic soccer grouping and alternate-spread wiring

**Files:**
- Create: `web/lib/soccer-leagues.ts`
- Create: `web/lib/__tests__/soccer-leagues.test.mjs`
- Modify: `web/lib/sports.ts`

**Interfaces:**
- Consumes: generated `Game` objects with optional `league_key`, `league_title`, `is_live`, and `commence_time`.
- Produces: `groupSoccerGames(games)` returning `{ key, title, games, hasLive, earliestKickoff }[]` in display order.

- [ ] **Step 1: Write the failing grouping test**

Cover three leagues: a later live EPL match, an earlier pre-match MLS match, and a metadata-free match. Assert group titles/order are `EPL`, `MLS`, `Other Soccer`; assert games inside a league sort by `commence_time`.

```javascript
assert.deepEqual(groups.map(group => group.title), ["EPL", "MLS", "Other Soccer"]);
assert.deepEqual(groups[0].games.map(game => game.event_id), ["epl-early", "epl-late"]);
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `cd web && node --test lib/__tests__/soccer-leagues.test.mjs`

Expected: FAIL because `soccer-leagues.ts` does not exist.

- [ ] **Step 3: Implement the pure grouping helper**

Use a `Map` keyed by `game.league_key ?? "__other_soccer__"`. Title is `game.league_title || "Other Soccer"`. Sort each group's games by ISO commence time, then sort groups by: `hasLive` descending, `earliestKickoff` ascending, title ascending; always force `__other_soccer__` last.

- [ ] **Step 4: Wire alternate spreads in the registry**

Change soccer's Spread entry to:

```typescript
{ label: "Spread", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" }
```

Add a test assertion that `SPORTS.soccer.marketGroups` exposes that exact `altKey`, either in the new Node test or the existing sports registry test location.

- [ ] **Step 5: Run tests and commit**

Run: `cd web && node --test lib/__tests__/soccer-leagues.test.mjs`

Run: `cd web && npx eslint lib/soccer-leagues.ts lib/__tests__/soccer-leagues.test.mjs lib/sports.ts`

Expected: PASS with zero errors.

```bash
git add web/lib/soccer-leagues.ts web/lib/__tests__/soccer-leagues.test.mjs web/lib/sports.ts
git commit -m "feat: group soccer games by league"
```

---

### Task 5: Render collapsible soccer league sections

**Files:**
- Modify: `web/components/odds-grid/index.tsx`
- Create: `web/components/odds-grid/league-section.tsx`

**Interfaces:**
- Consumes: `groupSoccerGames(games)` and the current global `activeGroup`, visible books, expansion-sheet state, and filtered games.
- Produces: expanded-by-default league sections only for soccer; unchanged flat table for every other sport.

- [ ] **Step 1: Extract the existing table body without changing behavior**

Create a focused `OddsGamesTable`/`LeagueSection` boundary that accepts the already-filtered games and existing market/book props. Keep the current flat render path using this component. Run targeted lint before adding grouping to prove the extraction is behavior-neutral.

- [ ] **Step 2: Add the soccer section render**

After applying the All/Pre/Live filter, call `groupSoccerGames(games)` only for soccer. Render each group in a semantic `<section>` with an expanded-by-default `<details open>` header containing the league title and match count. Reuse the extracted table for group games; keep one global market tab strip above all sections.

- [ ] **Step 3: Preserve expansion behavior**

Keep `sheetEventId` global to `OddsGrid`. Derive the selected game from the full filtered soccer game list so opening an alternate-spread sheet inside any league works exactly like the former flat table.

- [ ] **Step 4: Run frontend checks**

Run:

```bash
cd web
node --test lib/__tests__/soccer-leagues.test.mjs
npx eslint components/odds-grid/index.tsx components/odds-grid/league-section.tsx lib/soccer-leagues.ts lib/sports.ts
npx tsc --noEmit
```

Expected: new tests and targeted lint pass. If the full TypeScript command reports only previously documented unrelated Bets-page errors, record them explicitly; no new error may reference files in this task.

- [ ] **Step 5: Commit**

```bash
git add web/components/odds-grid/index.tsx web/components/odds-grid/league-section.tsx
git commit -m "feat: render soccer odds by league"
```

---

### Task 6: End-to-end verification and runtime activation

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: runtime evidence that alternate rows and league metadata reach the live UI API.

- [ ] **Step 1: Run the complete relevant backend suite**

```bash
.venv/bin/pytest \
  server/tests/test_soccer_market_config.py \
  server/tests/test_soccer_league_metadata.py \
  server/tests/test_fetcher.py \
  server/tests/test_cache.py \
  server/tests/test_api.py -q
```

Expected: all pass.

- [ ] **Step 2: Run frontend and repository checks**

```bash
cd web
node --test lib/__tests__/soccer-leagues.test.mjs
npx eslint components/odds-grid/index.tsx components/odds-grid/league-section.tsx lib/soccer-leagues.ts lib/sports.ts
cd ..
git diff --check
```

Expected: all exit 0.

- [ ] **Step 3: Restart or hot-reload the fetcher**

Use the app's existing fetcher-control endpoint or restart the backend service, then trigger one refresh. Do not expose the Odds API key in command output.

- [ ] **Step 4: Verify live API data**

Query `/api/odds/soccer` and assert with `jq` that at least one game contains non-null `league_key`/`league_title`. After the alternates cycle finishes, assert at least one market has `market_key == "alternate_spreads"`; if the provider returns no current coverage, report that as live-provider state while relying on the mocked integration tests for correctness.

- [ ] **Step 5: Verify the page serves**

Request `http://127.0.0.1:3000/odds/soccer` and confirm HTTP 200. If the connected browser is available, inspect that league sections are expanded, ordered correctly, and the Spread expansion shows alternate points. If unavailable, state that visual browser verification could not be performed.

- [ ] **Step 6: Review task-owned diff**

Run `git status --short`, then inspect each implementation commit with `git show --stat --oneline <commit-sha>`. Confirm no unrelated dirty-worktree changes were staged or overwritten.
