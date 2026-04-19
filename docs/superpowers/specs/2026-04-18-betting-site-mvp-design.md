# Betting Site MVP — Design

**Date:** 2026-04-18
**Status:** Draft (pending spec review + user approval)
**Author:** Brainstormed with Claude
**Scope:** MLB only. Laptop only. Local-only runtime. No auth.

---

## 1. Overview

A personal betting odds aggregator website in the style of OddsJam / Action Network, with two primary pages:

1. **`/odds/mlb` — The Grid.** Live odds from ~8 major US sportsbooks for today's MLB games, side-by-side in a dense table. Best-price-per-line highlighted. Line-movement flashes.
2. **`/picks/mlb` — The Feed.** Output from the sibling `baseball-agents` prediction pipeline rendered as a dense table of picks with probability, edge, stake, and expandable LLM-generated reasoning.

UI polish is the primary quality bar. The aesthetic target is "Bloomberg Terminal for sports betting" — dense, restrained, trading-desk-feeling; explicitly not casino, not affiliate-site.

## 2. Non-Goals (deliberately excluded from v1)

- **Multi-sport.** Site is MLB-only for v1. Directory structure is sport-parameterized so adding NBA/Soccer/etc. is additive, not a refactor.
- **Mobile.** Laptop-only runtime. No responsive-parity effort. Desktop breakpoint only.
- **Deployment.** Runs on the user's laptop via `uvicorn` + `next dev`. No Vercel/Fly/Docker in v1.
- **Authentication.** No login. Site binds to `localhost`; nobody else can reach it.
- **Realtime via WebSockets.** Polling only (SWR on the frontend, APScheduler on the backend). WebSocket upgrade is a v2 option if polling lag becomes visibly bad.
- **Drag-to-reorder sportsbook columns.** Sportsbook column order is fixed (best-odds first, then alphabetical) for v1. Drag-reorder is a v2 feature.
- **Bet-slip / bet placement.** This is a read-only viewer — clicking an odds cell opens the sportsbook's site in a new tab at most. No in-site bet construction.
- **Arbitrage / middle detection.** Only "best odds" is surfaced, not arb opportunities.
- **User preferences persistence.** No user accounts means no saved book list, saved filters, etc. All UI state is ephemeral.
- **Agent pipeline changes.** Agents under `~/personal_workspace/agents/` are untouched. Site reads their existing output files without modification.

## 3. Architecture

Two independent processes on the user's laptop, communicating over HTTP.

```
┌─────────────────────────────┐           ┌──────────────────────────────┐
│  Python backend (FastAPI)   │           │  Next.js frontend (App Router)│
│  localhost:8000             │ ← HTTP →  │  localhost:3000              │
│                             │           │                              │
│  • Odds fetcher (scheduled) │           │  • /odds/mlb  (grid)         │
│  • Odds cache (SQLite)      │           │  • /picks/mlb (feed)         │
│  • Picks reader (filesystem)│           │  • SWR polling               │
│  • JSON API endpoints       │           │                              │
└──────────▲──────────────────┘           └──────────────────────────────┘
           │
           │ reads
           ▼
   ┌───────────────────────┐           ┌────────────────────────────┐
   │  The Odds API         │           │  agents/baseball-agents/   │
   │  api.the-odds-api.com │           │  output/picks-*.json       │
   └───────────────────────┘           └────────────────────────────┘
```

**Boundary:** The frontend talks only to the backend over JSON. It never reads agent output files directly; it never calls The Odds API directly. This keeps a clean seam for any future deployment story.

### 3.1 Why this shape

- **Single responsibility per service.** Python does data; Next.js does pixels. Each service has one thing to be good at.
- **The fetcher runs in-process.** APScheduler inside the FastAPI app, not a separate cron or worker. One process to start, one to crash.
- **SQLite, not Postgres.** A single file. No DB to install.
- **Polling, not WebSockets.** SWR re-fetches `/api/odds/mlb` every 15 seconds. Odds movements appear with a worst-case 15s lag, which the yellow-fade line-flash animation masks well. WebSockets would be nicer but cost 10x the complexity for marginal perceived-responsiveness gain.

## 4. Backend

### 4.1 Process

Single `uvicorn server.main:app` command boots everything: FastAPI app, APScheduler, odds fetcher job, picks reader. No separate worker.

### 4.2 Directory structure

```
server/
├── main.py                # FastAPI app entry; registers routes + starts scheduler
├── config.py              # Env vars (ODDS_API_KEY, poll intervals, agent paths)
├── models.py              # Pydantic domain models: Game, BookOdds, Pick, Agent
├── odds/
│   ├── client.py          # The Odds API HTTP client
│   ├── fetcher.py         # APScheduler job: call client every 30s → write cache
│   └── cache.py           # SQLite-backed store
├── picks/
│   └── reader.py          # Watches agents/baseball-agents/output/picks-*.json
├── api/
│   ├── odds.py            # GET /api/odds/mlb
│   ├── picks.py           # GET /api/picks/mlb
│   └── health.py          # GET /api/health
└── tests/
    ├── test_devig.py
    ├── test_best_odds.py
    ├── test_picks_reader.py
    └── test_api_odds.py
```

### 4.3 Odds fetcher

**Source:** The Odds API v4 (`https://api.the-odds-api.com/v4`). Auth via `ODDS_API_KEY` env var, query-param style.

**Patterns lifted from `agents/baseball-agents/scrapers/odds.py`:**
- `OddsData` dataclass shape
- Devig math (two-way + three-way markets)
- Best-odds selection across bookmakers
- 422 soft-fallback for unavailable F5/F3 markets
- API budget guard: skip per-event calls if remaining quota < 100
- 15s HTTP timeouts

**What it fetches each tick:**
1. `GET /sports/baseball_mlb/odds?regions=us,us2&oddsFormat=american&markets=h2h,spreads,totals` — returns all today's games with core markets from all US books.
2. (Optional, gated by budget) `GET /sports/baseball_mlb/events/{event_id}/odds?markets=team_totals,alternate_spreads,alternate_totals` — only for games referenced by today's picks. The picks reader exposes a `get_todays_event_ids() -> set[str]` method; the fetcher calls it once per tick to determine which events to enrich. This keeps the fetcher dependent on the picks reader, but not the other way around.

**Interval:** 30s default, env-configurable.

**Error handling:**
- 422 (market unavailable) → soft-skip, log, keep serving prior cache for that market.
- 429 / 5xx → exponential backoff (1s → 2s → 4s), cap at 3 retries. On final failure, keep serving stale cache and expose `stale_seconds` in the API response so the UI can render a "X seconds old" indicator.
- API budget < 100 → skip per-event enrichment, continue with core markets only.

### 4.4 Odds cache (SQLite)

One file: `server/cache.db`.

**Schema:**
```sql
CREATE TABLE odds_snapshot (
  fetched_at     TIMESTAMP NOT NULL,
  event_id       TEXT NOT NULL,
  home_team      TEXT NOT NULL,
  away_team      TEXT NOT NULL,
  commence_time  TIMESTAMP NOT NULL,
  bookmaker_key  TEXT NOT NULL,
  market_key     TEXT NOT NULL,         -- 'h2h' | 'spreads' | 'totals' | 'team_totals' | ...
  outcome_name   TEXT NOT NULL,         -- team name | 'Over' | 'Under'
  outcome_point  REAL,                  -- line for spreads/totals
  price_american INTEGER NOT NULL,
  PRIMARY KEY (event_id, bookmaker_key, market_key, outcome_name, outcome_point)
);

CREATE TABLE fetcher_status (
  key            TEXT PRIMARY KEY,
  last_fetch_at  TIMESTAMP NOT NULL,
  requests_used  INTEGER,
  requests_remaining INTEGER,
  last_error     TEXT
);
```

Each fetch overwrites the current row for a given `(event_id, bookmaker_key, market_key, outcome_name, outcome_point)` tuple and updates its `fetched_at`. No history table in v1. Line-move detection happens client-side by diffing consecutive SWR responses (see §5.4).

**Stale computation:** `stale_seconds` in the API response is computed **per-row** as `now - odds_snapshot.fetched_at` for that specific book × market × outcome, then aggregated to the game level as `max(stale_seconds across its cells)`. The response-level `stale_seconds` is `max(game.stale_seconds)`. This is more honest than a single fetcher-wide timestamp when only some markets succeeded on a given tick.

### 4.5 Picks reader

**Source:** `~/personal_workspace/agents/baseball-agents/output/picks-YYYY-MM-DD.json` (exact path configurable).

**Behavior:** On each HTTP request to `/api/picks/mlb`, check the mtime of today's picks file. If it's changed since the last read (or this is the first read of the day), reparse into memory. Otherwise serve from in-memory cache.

**Expected JSON shape:** Picks are generated by `baseball-agents` in their existing format; the reader adapts them into the site's domain model (see §6). **Step 1 of implementation is capturing a sample of the current `picks-*.json` format into `server/tests/fixtures/picks_example.json` and diffing it against the `Pick` model in §6.** Any fields the agent output doesn't currently carry (e.g., `agent_record_30d`, `stats`, `tier`) must either be added to the agent output or derived/defaulted in the reader, and the decision recorded in the implementation plan before the reader is built.

**Missing file:** If today's picks file doesn't exist yet (e.g., the agent hasn't run yet), the API returns `{picks: [], status: "no_picks_today", last_checked_at: "..."}`. The UI renders an empty state.

### 4.6 API endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/odds/mlb` | Today's games with all cached books × markets, with best-odds marked per line. Includes `stale_seconds`. |
| GET | `/api/picks/mlb` | Today's picks with agent identity, pick details, reasoning, key stats. Includes `status`. |
| GET | `/api/health` | Fetcher status: last fetch timestamp, requests remaining, last error. |

OpenAPI schema is auto-generated by FastAPI at `/openapi.json` and consumed by the frontend's `openapi-typescript` codegen step.

## 5. Frontend

### 5.1 Process

`next dev` on port 3000. App Router (not Pages Router).

### 5.2 Directory structure

```
web/
├── app/
│   ├── layout.tsx                 # Root: theme, font loading, nav shell
│   ├── page.tsx                   # Landing → redirects to /odds/mlb
│   ├── odds/
│   │   └── mlb/page.tsx           # Server component shell + OddsGrid (client)
│   └── picks/
│       └── mlb/page.tsx           # Server component shell + PicksTable (client)
├── components/
│   ├── odds-grid/
│   │   ├── index.tsx              # TanStack Table wrapper
│   │   ├── columns.tsx            # Column config (best-odds, books)
│   │   ├── cell-flash.tsx         # Yellow-fade animation on value change
│   │   └── best-cell.tsx          # Green "best odds" cell with inline book label
│   ├── picks-table/
│   │   ├── index.tsx              # TanStack Table wrapper
│   │   ├── columns.tsx            # Column config (tier, game, pick, prob, edge, stake)
│   │   ├── expanded-row.tsx       # Inline expand with stats strip + reasoning
│   │   └── tier-badge.tsx         # High Conviction / Sweet Spot / Lean badges
│   ├── ui/                        # shadcn/ui primitives (button, badge, etc.)
│   └── layout/
│       ├── nav-shell.tsx          # Top tab bar (Odds / Picks) + sport selector
│       └── stale-indicator.tsx    # "Odds 12s old" pill
├── lib/
│   ├── api.ts                     # Typed fetcher (uses generated types)
│   ├── swr.ts                     # SWR config
│   └── format.ts                  # American odds, units, time-ago
├── styles/
│   ├── globals.css                # Tailwind base + design tokens
│   └── tokens.css                 # CSS custom properties for palette/scale
└── types/
    └── api.ts                     # Generated from FastAPI /openapi.json
```

### 5.3 Key library choices

| Library | Purpose | Why |
|---|---|---|
| **Next.js 15 (App Router)** | Framework | Modern React, server components for initial paint, zero-config TS |
| **TypeScript** | Language | Non-negotiable for a data-heavy UI |
| **Tailwind CSS** | Styling | Design token system via CSS variables; no runtime cost |
| **shadcn/ui** | Primitives | Unstyled, copy-in components; not a dependency — we own the code |
| **TanStack Table v8** | Odds/picks grid | Column config, sorting, virtualization, expandable rows |
| **Framer Motion** | Animations | Yellow-fade on line moves, row-expand transition, live-dot pulse |
| **SWR** | Data fetching | Polling, dedup, keep-last-data-on-error |
| **Inter (self-hosted)** | Font | Tabular figures via `font-feature-settings` |
| **openapi-typescript** | Codegen | Generates TS types from FastAPI schema — no type drift |

### 5.4 Data fetching

- **Odds:** SWR with `refreshInterval: 15_000`, `dedupingInterval: 5_000`, `revalidateOnFocus: true`, `keepPreviousData: true`.
- **Picks:** SWR with `refreshInterval: 60_000` (picks change rarely within a day).
- **Line-move detection:** Client keeps previous `odds_snapshot` response in a `useRef`; on each new response, diff cells keyed by `(event_id, bookmaker_key, market_key, outcome_name, outcome_point)` — the same tuple as the backend primary key. A cell whose `price_american` changed triggers the yellow flash. A cell that disappeared (e.g., total line moved from 7.5 to 8.0) counts as a move on both the old and new rows — both flash briefly to communicate the change.

## 6. Data Model

Pydantic on the backend, mirrored in TypeScript via `openapi-typescript`.

```python
class BookPrice(BaseModel):
    bookmaker_key: str           # 'draftkings' | 'fanduel' | ...
    price_american: int          # -138 | +112
    point: float | None          # line for spreads/totals, None for h2h

class MarketOutcome(BaseModel):
    outcome_name: str            # 'Yankees' | 'Over'
    prices: list[BookPrice]      # one per book
    best_price: BookPrice        # shortcut for the best-odds cell

class Market(BaseModel):
    market_key: str              # 'h2h' | 'spreads' | 'totals' | ...
    outcomes: list[MarketOutcome]

class Game(BaseModel):
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    is_live: bool
    markets: list[Market]

class OddsResponse(BaseModel):
    games: list[Game]
    stale_seconds: int
    fetched_at: datetime

# Picks
class PickTier(str, Enum):
    HIGH = "high"                # High Conviction
    SWEET = "sweet"              # Sweet Spot
    LEAN = "lean"                # Lean

class PickStat(BaseModel):
    label: str                   # 'Cole ERA'
    value: str                   # '2.91'

class Pick(BaseModel):
    id: str
    tier: PickTier
    game_label: str              # 'NYY @ BOS'
    market_label: str            # 'Yankees ML' | 'Over 7.5'
    odds_american: int
    best_book: str               # 'draftkings'
    stake_units: float           # 1.5
    probability_pct: float       # 62.4
    edge_pct: float              # 4.8
    stats: list[PickStat]        # 2–4 rows
    reasoning: str               # full LLM-generated paragraph(s)
    agent_key: str               # 'baseball-agents'
    agent_record_30d: str        # '18-12 (+6.1u)'
    commence_time: datetime

class PicksResponse(BaseModel):
    picks: list[Pick]
    status: Literal["ok", "no_picks_today"]
    last_checked_at: datetime
```

## 7. Design System

### 7.1 Palette (dark mode only — no light mode in v1)

| Token | Hex | Usage |
|---|---|---|
| `surface-0` | `#0B0F14` | App background |
| `surface-1` | `#131A22` | Cards, table headers |
| `surface-2` | `#1C2530` | Elevated rows, input backgrounds |
| `border` | `#263140` | Dividers, subtle borders |
| `text-primary` | `#F5F7FA` | Body |
| `text-secondary` | `#9AA5B4` | Secondary labels |
| `text-tertiary` | `#6B7685` | Disabled / deep meta |
| `semantic-positive` | `#2CB459` | Best price, positive edge |
| `semantic-negative` | `#E5484D` | Worse price, line moved against |
| `semantic-flash` | `#F5A524` | Just-moved; 30s decay |
| `accent` | `#22D3EE` | Brand / selected / interactive |

**Sportsbook logos:** Desaturated monochrome in table headers and default cells. Full color only in the dedicated "Best Odds" cell and on hover of a header.

### 7.2 Typography

**Family:** Inter (self-hosted via `next/font`). No fallback UI font — always assume Inter loads.

**Feature settings applied globally:** `font-feature-settings: 'tnum' 1, 'ss01' 1;` — tabular figures everywhere, and stylistic set 1 (cleaner `a` and `g`).

**Scale:**
| Role | Size | Weight | Notes |
|---|---|---|---|
| Table body | 12px | 400 / 500 | Odds always 500-600, tabular |
| Table header | 11px | 500 | Uppercase, tracking `0.05em` |
| Page title | 24px | 700 | Rare — mostly empty states |
| Stat value | 12px | 600 | Bold for emphasis in stats strip |
| Stat label | 11px | 400 | Secondary color |
| Badge | 10px | 600 | Uppercase, tracking `0.05em` |

No italics on odds. No true monospace for body — monospace only for timestamps / game clocks.

### 7.3 Motion

- **Yellow-fade on line change:** `background-color` from `rgba(245, 165, 36, 0.3)` to `transparent` over 30s (exponential decay, `ease-out`). Debounced so a cell that flickers rapidly doesn't strobe.
- **Live-game dot:** 6px red dot with a pulsing halo (`opacity` 0.3 → 0.1 loop, 1.5s `ease-in-out`, respects `prefers-reduced-motion`).
- **Row expand (picks table):** `height: auto` with Framer Motion's `layout` prop, 180ms `ease-out`.
- **No odds-value slide/flicker** — value just changes in place + gets the yellow backdrop. No layout shift allowed.

## 8. Page Designs

### 8.1 `/odds/mlb` — The Grid

Reference mockup: `.superpowers/brainstorm/67342-1776574509/odds-grid-density.html` (Option A).

**Shell:**
- Top nav: `[◆ Odds] [Picks] [Health]` — selected underlined in `accent`. Right side: "Updated Xs ago" + a small pulsing dot when fetcher is healthy.
- Breadcrumb / sport bar: `MLB · Apr 18 · N games` header strip.

**Grid columns** (left to right):
| Column | Width | Notes |
|---|---|---|
| Game (team abbrevs + status) | 180px | `NYY @ BOS · LIVE 3rd` or `· 7:10 PM` |
| Best Odds | 90px | Price + inline colored book abbrev |
| DK / FD / MGM / CZR / FAN / HRB / ESPN / PB | ~75px each | American odds, tabular figures |

**Row height:** ~36px. Alternating row color (`surface-0` / `surface-1` at 40% opacity).

**Market type tabs:** Client-side toggle above the grid — `[Moneyline] [Run Line] [Total]`. No route change. Default Moneyline.

**Cell states:**
- Default: `text-primary` at 500 weight.
- **Best price:** `semantic-positive` color + small inline book label underneath (e.g., "`DK`" at 10px, `text-tertiary`).
- **Just moved:** yellow backdrop with 30s exponential decay (see §7.3).
- **Worse than consensus by ≥5¢:** subtle `semantic-negative` tint (opacity 0.15). "Consensus" here is the **median American-odds price across all books offering that exact outcome/point**, computed server-side and included in the API response as `market_outcome.consensus_price_american`. Median (not mean, not devigged) keeps the comparison robust to outlier books.

**Empty state:** "No MLB games today." centered, with the last-known games from yesterday struck through in muted text.

**Stale state:** If `stale_seconds > 90`, a yellow pill appears top-right: "Odds last updated 2m 14s ago — fetcher may be stuck." Clicking opens `/api/health` output in a dialog.

### 8.2 `/picks/mlb` — The Feed

Reference mockup: `.superpowers/brainstorm/67342-1776574509/picks-layout.html` (Option A).

**Shell:**
- Same top nav, but `[Picks]` tab selected.
- Header strip: `MLB · Apr 18 · N picks · Agent: baseball-agents · Last run 6:02 AM ET`.

**Table columns** (left to right):
| Column | Width | Notes |
|---|---|---|
| Tier badge | 70px | `High` / `Sweet` / `Lean` pill |
| Game | 100px | `NYY @ BOS` |
| Pick | 140px | `NYY ML` / `Over 7.5` |
| Odds | 60px | Right-aligned, tabular |
| Prob% | 70px | Right-aligned, tabular, 500 weight |
| Edge% | 70px | Right-aligned, green, 600 weight |
| Stake | 60px | Right-aligned, tabular, accent color |
| Agent · 30d | 200px | `baseball-agents · 18-12 (+6.1u)` |

**Row expand:**
- Click anywhere on a row → row expands in-place with a subtle `accent`-colored left border.
- Expanded body contains:
  - **Stats strip** — a horizontal row of `label: value` pairs, 2–4 stats. Example: `Starter ERA · NYY Cole 2.91 / BOS Bello 4.22`.
  - **Reasoning** — the full LLM-generated paragraph(s) in `text-secondary` at 12px, line-height 1.55.
  - A `▴ Collapse` link at the bottom-right of the expanded body.
- Only one row expanded at a time (click another row to switch).

**Tier badge colors:**
| Tier | Background | Text |
|---|---|---|
| High Conviction | `rgba(44, 180, 89, 0.15)` | `semantic-positive` |
| Sweet Spot | `rgba(124, 92, 255, 0.15)` | violet `#7C5CFF` |
| Lean | `rgba(245, 165, 36, 0.15)` | `semantic-flash` |

Note: Violet is a secondary semantic color used only for the Sweet Spot badge. It's not a general accent.

**Graded picks (past picks, resolved):** When a pick has a resolution (`win` / `loss` / `push`), the entire row is rendered at 60% opacity with a `W` / `L` / `P` badge replacing the Tier column. V1 only surfaces today's fresh picks; graded picks listing is v2.

**Empty state:**
- `status: "no_picks_today"` → "The agent hasn't run yet today. Last picks were for Apr 17." with a relative timestamp.

## 9. Error Handling & Resilience

| Surface | Failure | Behavior |
|---|---|---|
| Odds API | 422 (market unavailable) | Soft-skip, log, keep prior cache |
| Odds API | 429 / 5xx | Exp backoff (1s/2s/4s), 3 tries, serve stale + `stale_seconds` |
| Odds API | Budget < 100 | Skip per-event calls, core markets only |
| Fetcher | Unhandled exception | Log; job skips this tick; next tick retries |
| Picks file | Missing | `/api/picks/mlb` returns `status: "no_picks_today"` |
| Picks file | Malformed JSON | `/api/picks/mlb` returns 500 with the parse error; UI shows a diagnostic card |
| Frontend fetch | Network error | SWR keeps last good data + shows "reconnecting..." pill |
| Frontend fetch | Backend 500 | Same — never blank the page |

## 10. Testing Strategy

### 10.1 Backend

- **Pure-function units** (pytest): devig math, best-odds selection across books, American ↔ decimal conversion. Small, fast.
- **Picks reader** (pytest with fixtures): feed fixture JSON files (sampled from real agent output); assert domain model shape.
- **API endpoints** (pytest with `httpx.AsyncClient`): assert response shape, empty-state behavior, `stale_seconds` computation.
- **Odds API client** (pytest with VCR.py): record one real response per endpoint, replay in CI. Fixtures are **committed to the repo** under `server/tests/cassettes/`, with the API key and any rate-limit/quota headers scrubbed by a VCR `filter_headers` / `filter_query_parameters` hook. Refresh cadence: re-record manually when the schema changes; don't bake fixture refresh into CI.

### 10.2 Frontend

- **Formatters / utilities** (Vitest): American-odds formatting, unit formatting, time-ago.
- **Component tests** (Vitest + React Testing Library): tier badge renders correct color; best-odds cell shows the book; flash animation triggers on price change.
- **End-to-end** (Playwright): two page smoke tests against a mocked backend (MSW). Screenshot diff of the grid and the picks table committed to repo.

### 10.3 What is not tested

- No integration test against the live Odds API (requires API quota, network).
- No visual-regression for animations (flaky; tested by eye).

## 11. Open Questions / Future Work

1. **Historical odds / line-movement chart.** SQLite schema currently overwrites on each fetch. A `odds_snapshot_history` table is a small addition but out of scope for v1. Revisit when we want Unabated-style line-history hover.
2. **Multi-sport.** Directory structure (`odds/mlb`, `picks/mlb`) is sport-parameterized. Adding NBA is: (a) new sport_key in the fetcher config, (b) new picks reader path, (c) new route. No refactor needed.
3. **Deployed version.** Upgrading from local to Vercel+Fly is a config exercise: backend URL becomes an env var, picks reader switches from filesystem to an HTTP endpoint the agent pipelines POST to, auth gets added.
4. **Real-time line moves via WebSocket.** Polling works but 15s lag is visible. If the yellow-flash becomes less useful, upgrade to a backend-pushed SSE or WS stream.
5. **Graded picks history.** v2 picks page adds a "Past Picks" tab with W/L/Push resolution. Requires a separate agent-output format (or post-processing of existing output).

## 12. References

- The Odds API v4 documentation
- `agents/baseball-agents/scrapers/odds.py` — source of devig math, best-odds, 30-team abbrev map
- Competitor research reports (4 subagent outputs, archived under `/private/tmp/claude-501/.../tasks/`)
- Visual mockups:
  - `.superpowers/brainstorm/67342-1776574509/odds-grid-density.html`
  - `.superpowers/brainstorm/67342-1776574509/picks-layout.html`
