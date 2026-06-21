# Bet Tracker — Multi-Source + CLV Dashboard (Roadmap #11)

**Date:** 2026-06-21
**Status:** Design — pending review
**Roadmap item:** Tier 2 #11 (bet tracker + auto-CLV vs Pinnacle reference)

## Context

Coral33 bet tracking + CLV is already shipped end-to-end:

- `closing_lines` table with sharp-consensus devigged close odds
- T-15..T-5 capture pipeline (`server/odds/clv_capture.py`)
- Historical backfill via Odds API archive (`server/odds/clv_backfill.py`)
- Wager → outcome address translation for all market families (`server/odds/clv.py`)
- `GET /api/coral33/accounts/bets` with `clv_pct` populated server-side
- `/accounts` page renders a bet-history table with a CLV column

The original roadmap line ("add a `bets` table, log placed bets, compute CLV") undersells what exists. The actual gaps:

1. **Coverage** — only Coral33 wagers are tracked. Bets placed at Kalshi, Polymarket, or any traditional sportsbook are invisible.
2. **Aggregations** — per-row CLV exists but no rollups (30d / 90d / lifetime CLV%, ROI%, by book / sport / market), no trend chart.
3. **Information architecture** — bet history is buried inside `/accounts`, which is already busy with balances and pending wagers.

## Goals

- Auto-track positions/fills from Kalshi and Polymarket (authenticated user endpoints; existing book modules already speak both venues for market data).
- Bulk import bets from any other book via CSV (simple documented schema, downloadable template).
- New dedicated `/bets` page with rollup tiles, CLV trend chart, breakdowns, and the unified bet history table.
- Existing `/accounts` page keeps balance views; bet history moves to `/bets`.

## Non-goals

- Manual one-bet-at-a-time entry form. CSV import is the only manual path.
- Auto-detecting bets placed at non-Coral33 traditional sportsbooks (would require book-by-book scraping; out of scope).
- Persisting CLV. Computed at query time against the existing `closing_lines` table — same pattern as today.
- Cross-book deduplication of bets a user logged twice. The `(source_book, external_id)` PK keeps things idempotent within a source; the user is trusted not to double-log across sources.

## Architecture — unified `bets` table

One new table in `cache.db`. Every source (Coral33 mirror, Kalshi sync, Polymarket sync, CSV import) writes rows with the same shape. The API and UI read only from this table.

Rejected alternatives:

- **Federated view (no new table)** — every aggregation runs in Python; trend charts and breakdowns become O(N) merges on every request.
- **Table per source + union at query time** — four schemas drift over time; normalization still happens at the API layer.

The shape genuinely is the same across sources (date, odds, stake, outcome, result), so source-as-column is the cleaner factoring.

### Schema

```sql
CREATE TABLE IF NOT EXISTS bets (
  source_book      TEXT NOT NULL,        -- 'coral33' | 'kalshi' | 'polymarket' | 'imported'
  external_id      TEXT NOT NULL,        -- ticket_number / fill_id / position_id / sha1(csv_row)
  accepted_at      TEXT NOT NULL,
  settled_at       TEXT,
  status           TEXT NOT NULL,        -- 'open' | 'win' | 'loss' | 'push' | 'void' | 'pending'
  wager_type       TEXT NOT NULL,        -- 'straight' | 'parlay' | 'teaser' | 'free_play'
  total_picks      INTEGER NOT NULL DEFAULT 1,

  sport_key        TEXT,
  event_id         TEXT,                 -- matched to closing_lines / odds_snapshot when resolvable
  home_team        TEXT,
  away_team        TEXT,
  market_key       TEXT,                 -- 'h2h' | 'spreads' | 'totals' | 'player_<stat>' | ...
  outcome_name     TEXT,
  outcome_point    REAL NOT NULL DEFAULT 0.0,

  odds_american    INTEGER,              -- as offered at placement (head leg for parlays)
  stake            REAL NOT NULL,
  to_win           REAL,
  settled_amount   REAL,                 -- net payout; null until settled; fees already netted

  is_free_play     INTEGER NOT NULL DEFAULT 0,
  raw_description  TEXT,                 -- free-text for imports and unmatched cases
  imported_at      TEXT,                 -- only set for source_book='imported'
  PRIMARY KEY (source_book, external_id)
);

CREATE INDEX IF NOT EXISTS idx_bets_accepted ON bets(accepted_at);
CREATE INDEX IF NOT EXISTS idx_bets_event    ON bets(event_id);
CREATE INDEX IF NOT EXISTS idx_bets_book     ON bets(source_book);
CREATE INDEX IF NOT EXISTS idx_bets_status   ON bets(status);
```

- Created by extending the `SCHEMA` constant in `server/odds/cache.py`. New migrations list entry covers older DBs that pre-date the column set.
- Idempotent upsert on `(source_book, external_id)`.
- `event_id` may be NULL when a source row cannot be matched to a cache event (most CSV imports, some Polymarket positions with custom market shapes). The bet still surfaces in the UI; CLV simply shows `—`.

## Sync paths

### 1. Coral33 mirror

The existing wager-log JSON files stay as the scrape cache. A new thin function `mirror_coral33_wager_log_to_bets(cache, wager_log_by_cid)` walks the persisted entries and upserts into `bets`. Called from the same trigger that refreshes the wager log today (no new HTTP traffic, no new scheduler).

`external_id = ticket_number`. Parlays/teasers collapse to the head leg as today.

### 2. Kalshi positions + fills

New periodic task started from FastAPI's lifespan (5-minute cadence; follows the same lifespan-task pattern as the existing closing-line capture in `server/odds/clv_capture.py`). Uses the existing authenticated `KalshiClient` — both `get_portfolio_positions()` and `get_portfolio_fills()` are already implemented in `server/odds/books/kalshi/client.py`. The new work is the sync layer that consumes those methods and writes to the `bets` table.

- Hits `/portfolio/fills?after_ts=<last_seen>` incrementally
- For each fill, resolves the event via `kalshi/event_matcher.py` (used today for market-data matching) → populates `sport_key`, `event_id`, `home_team`, `away_team`
- Translates fill price → American odds, fill price × contracts → stake
- Kalshi taker fee constant already exists at `server/odds/books/kalshi/normalizer.py:KALSHI_TAKER_FEE = 0.07` along with its fee-adjustment formula (`p + KALSHI_TAKER_FEE * p * (1 - p)`). The sync path applies the same formula at settlement time so `settled_amount` is net of fee. No new fee table needed.
- `external_id = fill_id`

If `KALSHI_API_KEY` / `KALSHI_PRIVATE_KEY_PATH` are absent from env, the task no-ops at boot with a single warning log. Settings UI surfaces a "Not configured" state.

### 3. Polymarket trades

Same shape as Kalshi: 5-minute lifespan task. Uses the public `data-api.polymarket.com/trades?user=0xADDR` endpoint (no auth — positions are tied to the wallet address). Wallet address read from `user_settings.json`.

The exact `/trades` response shape is documented at https://docs.polymarket.com/developers/CLOB/trades; the sync layer expects a list of `{trade_id, market, outcome, side, price, size, timestamp, fee_rate_bps}`-shaped entries. A fixture file captured during implementation pins the contract for tests.

- Each trade → one bet row. `external_id = trade_id` (Polymarket-issued trade identifier; falls back to on-chain tx hash + log index when absent).
- Resolves event via `polymarket/event_matcher.py`.
- Polymarket taker fee constant lives at `server/odds/books/polymarket/normalizer.py:POLYMARKET_TAKER_FEE = 0.05`. The sync path applies it at settlement time so `settled_amount` is net of fee. The taker fee already captures bid/ask spread cost in Polymarket's model; gas is a withdrawal-time cost (not per-trade) and is intentionally not modelled at the bet level.
- Same no-op behavior if wallet is unconfigured.

### 4. CSV import

Synchronous endpoint, not a periodic task. Accepts multipart upload at `POST /api/bets/import`.

CSV format (downloadable template at `GET /api/bets/import/template`):

```csv
date,book,sport,event,market,side,odds,stake,result
2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W
2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending
2026-06-20,Pinnacle,tennis,Sinner vs Alcaraz,h2h,Alcaraz,+105,100,L
```

- Required columns: `date, book, sport, market, side, odds, stake, result`
- Optional: `event` (free text — used for best-effort event-id match against `closing_lines`)
- `result` values: `W | L | P | void | pending`
- `external_id = sha1(date|book|sport|event|side|odds|stake)` — re-importing the same CSV is idempotent (no duplicates, no overwrites of settled rows by the same row).

Response shape:

```json
{
  "accepted": 14,
  "rejected": [
    {"row": 6, "reason": "missing required column: stake"},
    {"row": 11, "reason": "invalid date: 'last tuesday'"}
  ]
}
```

Parse errors do not abort the import — good rows are accepted, bad rows surfaced for the user to fix and re-upload.

## CLV generalization

`server/odds/clv.py` keeps the existing Coral33 path. Add one new function:

```python
def lookup_clv_for_bet(bet: dict, cache: OddsCache) -> CLVResult | None:
    """Compute CLV for a unified bet row. Requires the bet row to carry
    event_id + market_key + outcome_name + outcome_point already
    resolved by its source's sync path. Returns None when any address
    field is missing or no closing line was captured for that outcome.
    """
```

- Each sync path is responsible for resolving the outcome address at sync time using its book's `event_matcher.py`. This keeps the CLV function dumb and pure.
- The existing `lookup_clv(wager, cache, config, subtype_map)` keeps working — Coral33 uses it internally, and the mirror function populates the same fields on the `bets` row.
- CSV imports without a matchable `event` field skip CLV (event_id stays NULL).

## API surface

| Endpoint | Purpose |
|----------|---------|
| `GET /api/bets` | List with filters: `status, book, sport, market, from, to, limit`. Each row carries `clv_pct` computed at query time. |
| `GET /api/bets/rollups` | One request returns `window_30d`, `window_90d`, `lifetime`, `by_book[]`, `by_sport[]`, `by_market[]`. One SQL pass; ~50 LOC. |
| `POST /api/bets/import` | Multipart CSV upload; per-row status response. |
| `GET /api/bets/import/template` | Returns the example CSV as `text/csv`. |
| `GET /api/coral33/accounts/bets` | Kept as a thin wrapper around `/api/bets?book=coral33` so existing UI doesn't break during cutover. |

Rollup math (single SQL pass via `GROUP BY` over the `bets` table):

- **CLV %** — average of `clv_pct` over rows where it's non-null
- **ROI %** — `sum(settled_amount - stake) / sum(stake)` over settled non-free-play rows
- **Wagered** — `sum(stake)` over the window
- **Bet count** — `count(*)` over the window

## UI — new `/bets` page

Layout: rollup tiles + CLV trend chart on top, filter bar, full bet history table below. Existing `/accounts` page table moves here.

```
┌─────────────────────────────────────────────────────────┐
│  BETS                              [ Import CSV ▾ ]     │
├─────────────────────────────────────────────────────────┤
│ ┌─30 DAY──┐ ┌─90 DAY──┐ ┌─LIFETIME─┐ ┌─OPEN──────┐      │
│ │CLV +2.1%│ │CLV +1.7%│ │CLV +1.4% │ │$340 @ risk│      │
│ │ROI +4%  │ │ROI +2%  │ │ROI +1.8% │ │12 tickets │      │
│ │64 bets  │ │210 bets │ │ 894 bets │ │           │      │
│ └─────────┘ └─────────┘ └──────────┘ └───────────┘      │
│ ┌────────── CLV % over time (90d) ──────────┐           │
│ │           ╱╲      ╱╲                       │           │
│ │    ╱╲   ╱  ╲   ╱╲╱  ╲    ╱╲                │           │
│ │ ──╱──╲─╱────╲─╱─────────╱──╲──────         │           │
│ └────────────────────────────────────────────┘           │
│ [Book ▾] [Sport ▾] [Market ▾] [Status ▾] [Date range]   │
├─────────────────────────────────────────────────────────┤
│ DATE  BOOK  SPORT  PICK         ODDS  STAKE  RESULT CLV │
│ 6-20  FD    MLB    LAD -1.5    +155   $25    PEND   —   │
│ 6-19  DK    NBA    BOS         -145   $50    W +$34 +3% │
│ 6-19  Kal   NFL    PHI O 50.5  -107   $50    W +$47 +1% │
└─────────────────────────────────────────────────────────┘
```

- "Import CSV" header button opens a drawer with file picker + a "Download template" link. After upload, shows the accepted/rejected summary inline.
- Tile values are SSE-aware via the existing `useLiveUpdates` hook (rollups revalidate on tick — at the new 1Hz cadence post-#8-fix).
- Chart bins by day. **New dependency**: `recharts` to be added to `web/package.json` (no chart library is currently installed; SWR + framer-motion + react-table are the dominant deps today). Chosen over visx/chart.js for the React-idiomatic component model and small bundle hit; revisit if bundle size becomes a concern.
- Breakdown sub-tiles (by book / by sport / by market) sit below the chart on wide viewports; collapse below the chart on narrow ones.
- `/accounts` keeps its balance summary + pending-wager list. A link in the header points to `/bets`.

## Error handling

| Failure | Behavior |
|---------|----------|
| Kalshi auth env missing | Sync task no-ops, single warning at boot, settings UI shows "Not configured". |
| Polymarket wallet missing | Same pattern. |
| Kalshi/Polymarket API 5xx | Log, retry next cycle. Partial fills already upserted persist. |
| CSV row parse error | Row rejected, included in response, other rows still accepted. |
| Duplicate `(source_book, external_id)` on re-sync | Upsert overwrites `status` + `settled_amount`; `accepted_at` stays. |
| CLV lookup raises | Caught, `clv_pct = null`, endpoint never breaks (same pattern as today). |
| Event-id unmatched at sync time | Row stored with `event_id = NULL`; CLV is `—` in UI. |
| Coral33 ticket appears in an imported CSV | Import row rejected with reason "coral33 tickets are auto-synced". |

## Testing

Unit tests:

- Schema migration runs cleanly against an existing `cache.db` with prior schema versions.
- `bets` upsert idempotency on `(source_book, external_id)`.
- `mirror_coral33_wager_log_to_bets`: input wager log → expected rows; running twice produces identical state.
- Kalshi fill → bet row translation (fixture-driven; mock client).
- Polymarket trade → bet row translation (fixture-driven).
- CSV parser: happy path, missing required column, bad date, bad odds, bad result, mixed good/bad.
- `lookup_clv_for_bet`: event_id populated → returns CLV; event_id NULL → returns None; closing_lines miss → returns None.
- Rollup SQL: known fixture → known rollup values across all windows.

Integration tests:

- Existing `/api/coral33/accounts/bets` (the wrapper) returns the same shape as before, populated from the new `bets` table.
- `POST /api/bets/import` round-trip: upload CSV → query `/api/bets?book=imported` → all accepted rows visible.

## Open questions

- (Resolved during brainstorm) — auto-track Kalshi/Polymarket + CSV import; new dedicated `/bets` page; tiles+chart+table layout.
- (Deferred) — manual one-bet entry form. Not in scope; can be added later as a thin wrapper around the CSV path (single-row form posts to `/api/bets/import`).
- (Deferred) — bet-tagging / notes. Useful for retention but not required for #11 to be "shipped".

## Out of scope

- Auto-track from traditional sportsbooks (DraftKings, FanDuel, etc.) — no public APIs; would require book-by-book scraping.
- DuckDB / columnar store (Tier 5 roadmap item). The unified `bets` table in SQLite scales fine for years of single-user history.
- Push notifications on settled bets (Tier 2 #12 — explicitly excluded by the user during brainstorm).
- Multi-user / shared bet tracking. Single-user assumption holds throughout.
