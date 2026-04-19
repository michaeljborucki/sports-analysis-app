# Betting-Site Brainstorm — Handoff State

**Last updated:** 2026-04-18
**Status:** Spec written, reviewer-approved with 6 advisory tightenings folded in. Awaiting user review before invoking `writing-plans`.
**Skill in use:** `superpowers:brainstorming` (final phase)
**Next step in this conversation:** User reviews `docs/superpowers/specs/2026-04-18-betting-site-mvp-design.md`; on approval, invoke `superpowers:writing-plans`.

---

## How to resume in a new terminal

Tell the new Claude session:

> Resume the betting-site brainstorming. Read `/Users/mikeborucki/personal_workspace/betting-site/BRAINSTORM_STATE.md` for full context. Continue from "Open Question" section. Use the `superpowers:brainstorming` skill conventions.

The new session should invoke the `superpowers:brainstorming` skill and pick up from the open question below.

---

## Project Goal

Build a betting odds aggregator website (think OddsJam / Monsterbet / Action Network):

- Shows all odds for different games, sortable by league and game
- Shows every sportsbook's offer per market in a nice UI
- Separate page section showing output from "the agent bets" — when baseball-agents pipeline runs, its output appears in a baseball section; same for soccer-agents, etc.

**Working directory:** `/Users/mikeborucki/personal_workspace/betting-site/` (currently empty — greenfield)

**Sibling agent repos:** `/Users/mikeborucki/personal_workspace/agents/` contains:
`baseball-agents`, `cricket-agents`, `esports-agents`, `nba-agents`, `ncaab-agents`, `soccer-agents`, `tennis-agents`, `ufc-agents`, plus `run_all.py`.

---

## Existing Odds API Integration (already analyzed)

Source: `/Users/mikeborucki/personal_workspace/agents/baseball-agents`

- **Provider:** The Odds API v4 (`https://api.the-odds-api.com/v4`)
- **Auth:** `ODDS_API_KEY` env var via query param, loaded with `python-dotenv`
- **Key files to study/borrow:**
  - `scrapers/odds.py` (463 lines) — Core API client. Contains `OddsData` dataclass, `get_mlb_odds()`, `get_additional_odds()`, devig math, best-odds selection across bookmakers
  - `simulation/props_edge.py` — Player props fetching
  - `config.py:16-22` — API config pattern, `TEAM_NAME_TO_ABBREV` mapping
- **Endpoints used:**
  1. `/sports/{sport_key}/odds` — Game-level (h2h, spreads, totals, F5/F3 inning markets)
  2. `/sports/baseball_mlb/events/{event_id}/odds` — Per-event (team totals, props, 1st-inning markets)
- **Params:** `regions=us,us2,eu,uk`, `oddsFormat=american`, multiple `markets=` strings
- **Resilience:** 422 fallback for unavailable F5 markets; API budget guard (skips per-event calls if `<100` requests remain); 15s timeouts; no auto-retry on transient failures
- **Reusable for site:** Devig math, best-odds selection, `OddsData` dataclass, fetcher patterns
- **Baseball-specific (will need parameterization):** Inning-market keys, 30-team abbreviation map, US/Eastern timezone

---

## Decisions Made So Far

| # | Question | Choice | Notes |
|---|----------|--------|-------|
| Q1 | MVP scope | **A — Thin slice end-to-end (MLB only)** | Full stack for one sport, then duplicate. Avoid the "full ambition" trap. |
| Q2 | Data freshness | **B — Backend cache, periodic refresh (~60s)** | Scheduled fetcher writes to cache; pages read cache. Sub-second loads, predictable API spend. |
| Q3 | Site ↔ agents relationship | **A — Site is independent, reads agent picks from output files** | Site owns its own Odds API fetcher. Agents stay untouched for v1. ~2x quota burn but bounded. Migration path to a shared `odds-core` package (option C) once proven. |
| Q3.5 | Picks delivery mechanism | **1 — JSON files** | Agents write `agents/baseball-agents/output/picks-YYYY-MM-DD.json`; site reads from filesystem. Zero network plumbing. Trivial migration to HTTP push later (swap `open()` for `requests.get()` in `picks_reader.py`). |
| Q4 | Tech stack | **Split: Python backend + Next.js/React frontend** | User stated UI polish is the primary KPI and accepts stack complexity. Python/FastAPI owns Odds API fetcher, cache, picks reader — exposes JSON. Next.js + Tailwind + shadcn/ui + TanStack Table + Framer Motion for the UI. Clean data/pixels boundary. |
| Q5 | Deployment + auth | **1 — Local only, no auth** | Runs on user's machine; no login. Upgrade to deployed+auth later is config, not a rewrite. |

---

## Q6 — Competitor Research (COMPLETE)

Four parallel agents researched four clusters. Full reports preserved at:
`/private/tmp/claude-501/-Users-mikeborucki-personal-workspace-betting-site/d179a415-1a92-4215-b0e2-90b1dac9300a/tasks/`
(IDs: `abfa58fc…` aggregators, `a7d2b03c…` picks, `ab1af0b8…` sportsbooks, `a1657dfdff…` alt)

### Synthesized Design Direction

**Overall mood:** "Bloomberg Terminal for sports betting." Not casino. Not affiliate-marketing. Trading-terminal-meets-consumer-fintech.

**Palette (dark mode first, confirmed by all four streams):**
- `surface-0` #0B0F14, `surface-1` #131A22, `surface-2` #1C2530
- `border` #263140
- `text-primary` #F5F7FA, `text-secondary` #9AA5B4
- `semantic-positive` #2CB459 (best price / edge)
- `semantic-negative` #E5484D (worse / line moved against)
- `semantic-flash` #F5A524 (just-moved, ~30s fade)
- `accent` TBD — violet #7C5CFF or electric teal #22D3EE (avoids collision with any major sportsbook)

**Typography:** Inter, weights 400/500/600/700. Tabular figures (`font-feature-settings: 'tnum' 1`) for every odds/money column — non-negotiable. No monospace for row data; monospace only for timestamps/clocks.

**Two primary pages:**

1. **`/odds/mlb` — The Grid.** Dense table. Sport tab bar (just MLB for v1) + left rail for filters (market type toggles, book visibility, best-odds-only). Columns: team / start time / spread+odds / total+odds / ML+odds, with 8–10 sportsbook columns. Dedicated "Best Odds" column with colored book logo inline. All other book logos desaturated to monochrome, color on hover. Yellow fade on line movement, green tint on best price, red tint on worse-than-consensus. Drag-to-reorder columns, user preference saved.

2. **`/picks/mlb` — The Feed.** Vertical feed of cards, Action Network anatomy. Each card: agent identity + trailing 30d unit record, game/market/odds/units stake, **big dual-number display (Probability % + Edge %)** as the visual anchor, named confidence tier badge ("High Conviction / Lean / Sweet Spot"), 2–3 key stats strip, collapsed reasoning with in-place expand. Graded picks muted with W/L/Push badge; fresh picks full color.

**Key killer features to borrow:**
- Yellow-fade on line moves (cheap, huge signal)
- Dedicated "Best Odds" column with logo inline
- Drag-to-reorder sportsbook columns, saved
- Debounced odds-flash animation (150–220ms) with directional color
- Skeleton loaders with zero layout shift
- Pulsing red-dot + halo for live games (1.5s ease-in-out, respects `prefers-reduced-motion`)
- Client-side market tabs (no route change)

**Anti-patterns confirmed to avoid:**
- NASCAR column headers (loud multicolor sportsbook logos)
- Overloaded coloring (e.g., green for both "best price" AND "+" odds)
- Layout-shifting odds animations
- Neon gradients, glassmorphism, chrome bevels (reads offshore/grey-market)
- Paywall/blur on picks feed
- Multi-paragraph reasoning on the card face without collapse
- Lifetime/cherry-picked track records instead of rolling windows

---

## Design Decisions (in progress)

- **Proposal style:** Hybrid (text architecture + visual mockups for layouts) — user approved.
- **Architecture sections 1–5 approved:** Two-service split (FastAPI + Next.js), APScheduler in-process, SQLite cache, polling (SWR 15s for odds, 60s for picks), standard error handling + testing stack.
- **Odds-grid layout:** **Option A — Ultra-dense Trading Terminal.** ~36px rows, 8 sportsbook columns inline, "Best Odds" column with inline book logo, monochrome book headers with color-on-hover, yellow-fade on line moves. Rendered at `.superpowers/brainstorm/67342-1776574509/odds-grid-density.html`.

## Layout Decisions Locked

- **Odds-grid layout:** Option A — Ultra-dense Trading Terminal
- **Picks-page layout:** Option A — Dense Table Rows with click-to-expand reasoning

Both pages share the same Bloomberg-Terminal-for-Betting aesthetic. Rendered mockups at:
- `.superpowers/brainstorm/67342-1776574509/odds-grid-density.html`
- `.superpowers/brainstorm/67342-1776574509/picks-layout.html`

## Open Question (resume here)

### Final scope decisions before design doc

1. **Accent color:** Electric teal `#22D3EE` (what's in the mockups) vs. violet `#7C5CFF`. Claude's rec: teal (cleaner against the dark Bloomberg aesthetic, doesn't collide with any major book).
2. **Markets scope for MVP:** (a) All MLB markets the agents currently fetch (ML, RL, totals, team totals, F5/F3 inning markets, alt lines, props) or (b) Core only (ML, RL, totals + whatever markets the picks happen to reference). Claude's rec: (b) — thin-slice discipline; expanding is additive.
3. **Mobile:** (a) Full responsive parity; (b) Simplified mobile view (one market per screen, scroll for books); (c) Desktop-first, mobile deferred. Claude's rec: (b) — usable on phone without broken horizontal scroll, but don't burn budget on a full mobile-optimized grid for v1.

**User has not yet answered these.**

---

## Remaining Questions to Ask (after Q3.5)

These are tentative — refine based on answers above:

- **Q4. Tech stack** — Python (matches agents: FastAPI + Jinja or HTMX), Next.js/React (richer UI), or something else? Tradeoffs around team familiarity vs. UI ambition.
- **Q5. Deployment + auth** — Run locally only, or deploy somewhere (Vercel/Fly/Railway/own VPS)? Public, password-gated, or auth-required?
- **Q6. UI inspiration** — Offer to dispatch a subagent that browses OddsJam, Monsterbet, Action Network and synthesizes UI patterns worth borrowing. Then push visual mockups to the visual companion.
- (Possibly Q7) **Markets/sports scope for MVP** — All MLB markets the agents fetch, or just core (ML/RL/totals)?

---

## Architecture Sketch (forming, not approved)

Based on decisions so far:

```
betting-site/
├── server/                   # Backend (likely Python, lifted patterns from baseball-agents/scrapers/odds.py)
│   ├── fetcher.py            # Scheduled odds fetcher — calls The Odds API every ~60s
│   ├── cache.py              # Storage (SQLite or JSON file initially)
│   ├── picks_reader.py       # Reads agents/baseball-agents/output/picks-*.json
│   └── api.py                # HTTP endpoints / page routes
├── web/                      # Frontend
│   ├── pages/odds/mlb.html   # Aggregator page
│   └── pages/picks/mlb.html  # Agent picks page
└── docs/superpowers/specs/   # Design doc lands here
```

**Data flow:**
1. Fetcher (cron/APScheduler) → The Odds API → cache
2. Agent pipeline runs → writes JSON to `agents/baseball-agents/output/`
3. Site picks reader → reads JSON → exposes to picks page
4. Browser → site backend → cache (odds) + picks reader (agent bets)

---

## Brainstorming Process Status

Tasks (from TaskCreate):

- [x] #1 Explore project context — done
- [ ] #2 Clarify MVP scope, data, agent integration, deployment — **in progress** (Q1, Q2, Q3 done; Q3.5 open; Q4-Q6 pending)
- [ ] #3 Propose 2-3 architecture approaches with tradeoffs
- [ ] #4 Present design sections for approval
- [ ] #5 Write design doc to `docs/superpowers/specs/2026-04-18-betting-site-mvp-design.md`
- [ ] #6 Spec review loop with `spec-document-reviewer` subagent
- [ ] #7 User reviews written spec
- [ ] #8 Invoke `writing-plans` skill

The brainstorming skill's hard gate still applies: **no implementation skills, no code, no scaffolding** until the design is approved by the user and a spec is written + reviewed.

---

## Visual Companion (currently running, may auto-exit)

- **URL:** http://localhost:65323
- **Screen dir:** `/Users/mikeborucki/personal_workspace/betting-site/.superpowers/brainstorm/56333-1776556488`
- **Server info file:** `<screen_dir>/.server-info`
- **Auto-exits after 30 min idle.** New session can restart with:
  ```bash
  /Users/mikeborucki/.claude/plugins/cache/superpowers-marketplace/superpowers/5.0.5/skills/brainstorming/scripts/start-server.sh \
    --project-dir /Users/mikeborucki/personal_workspace/betting-site
  ```
- Used so far: nothing rendered yet (haven't hit a visual question). UI mockups will start at Q6.

**Reminder:** Add `.superpowers/` to `.gitignore` once a git repo exists.

---

## User Profile Notes

- User's email: mborucki24@gmail.com
- Owns/runs the agent pipelines under `~/personal_workspace/agents/`
- Familiar with Python ecosystem (the agents are Python)
- Prefers concise communication, recommendations over open-ended questions
- Picked option A for MVP scope on first ask — comfortable making decisive product calls
