# UI Audit Findings — 2026-04-20

Playwright-driven sweep of all routes. Ranked by impact × effort.

**Env:** dev server @ `localhost:3000`, FETCHER_ENABLED=off (stale cache), CORAL33 on. Dataset: 6 NBA games (3 live / 3 pre), 2 tennis picks, 60 books in registry, 10 visible.

**Playwright fix:** `allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.1.153"]` in `web/next.config.ts` — Next.js 16 silently blocks `/_next/*` assets across origins, which hung every page on "Loading…" skeletons. Playwright's `localhost` target now works end-to-end.

---

## P0 — Correctness bugs

### 1. Dashboard "API QUOTA: 4570% remaining"
Impossible — percentage > 100 means the denominator or the subtraction is flipped. Likely `remaining / used * 100` instead of `remaining / total * 100`, or a stale cached total.
- **Where:** dashboard top-bar quota chip
- **Fix scope:** one file, math tweak

### 2. Empty-data tabs in Props matrix
Tabs like **"First Team Basket"** survive the settings∩data filter (the market key is present) but the row builder finds 0 rows because outcome names don't match `"<Player> Over"` / `"<Player> Under"`. User sees an enabled tab that just shows the empty-state.
- **Where:** `web/components/props-matrix.tsx:235-249` (`isPropMarket` / `splitOutcome`)
- **Fix scope:** either (a) gate `enabledTabs` on the existence of at least one splittable outcome, or (b) render non-O/U markets with a different primitive

### 3. EV scanner reports 0 opportunities
User confirmed EV should produce results against the current arbitrage/low-hold datasets. With fetcher off the cache is 18+h stale, so this may just be staleness — but the arb/low-hold pages show hundreds of opps against the same cache, so EV pairing is suspect.
- **Where:** `server/scanners/ev.py` (3-way skip from last session may be over-filtering)
- **Verify:** turn fetcher on briefly and re-check

---

## P1 — UX friction

### 4. Alt-lines drawer dominates viewport
Expanding Spread alts on Blazers@Spurs renders a 40+ row × 9-book matrix inline above the rest of the game list. Scroll position is lost. User has to scroll past a wall of numbers to see the next game.
- **Fix ideas:** collapse to top-N alt points around the main line by default; "show all" toggle; or render in a side sheet instead of inline
- **Where:** `web/components/odds-grid/market-expansion-panel.tsx` + `alt-lines-matrix.tsx`

### 5. Props matrix: 169 rows × 9 books unvirtualized
Rebounds tab for 2 NBA games = 169 (player, point) rows. All rendered; scrolling is fine on a laptop but will thrash on lower-end devices and is going to get worse with MLB prop counts (10+ markets × 300 players).
- **Fix scope:** react-window / tanstack-virtual for the matrix body; sticky headers are already in place

### 6. 30+ enabled prop-market tabs on Props page
Settings `player_props` tier is broad; every enabled key becomes a tab. Users have to horizontally scan to find the market they want. Most users will only care about 3-5 markets.
- **Fix ideas:** star/pin markets in Settings; collapse rarely-used into an overflow menu; remember last active tab per sport

### 7. Stale-cache artifacts surface as UX glitches
With fetcher off, I see: every arbitrage opp marked `LIVE` (6/6), a 939.1% conversion on the top free-bet, ESPN BET carrying both sides of arbs. These aren't bugs in the UI, but there's no freshness indicator on those pages. User can't tell at a glance that the data is stale.
- **Fix scope:** add a `last-updated · N min ago` chip on arbitrage/low-hold/ev/free-bets (dashboard already has one)

### 8. 5 missing book logos → console 404s
`fliff.com.png`, `lowvig.ag.png`, `coral33.com.png`, `leovegas.se.png`, `betfair.com.png` — the visibility panel shows these as broken `<img>` placeholders. `leovegas.com.png` exists (wrong country suffix); the other 4 need to be added or replaced with a text fallback.
- **Where:** `web/public/logos/` + `web/lib/books.ts` (book key → logo URL mapping)
- **Fix scope:** drop 4 PNGs in and / or rename `leovegas.se` → `leovegas.com` in the registry

---

## P2 — Polish

### 9. "No changes" vs "Save changes" button copy is muted
The Settings save button reads "No changes" in disabled state, but its visual weight is the same as the enabled "Save changes" state — it took me a moment to realize Save had flipped enabled. Either dim it further or change the label to `Nothing to save` with an outline-only treatment.

### 10. Props page player filter lands stranded when no rows match
Empty state reads "No players match 'LeBron'" but there's no hint that the tab itself might be empty. If a user switches tabs with a stale filter, they see the empty state and may think the filter is broken rather than the tab.
- **Fix scope:** when filter is non-empty AND filtering ≥1 row into 0, keep the current message; when filter is empty AND 0 rows, show the tab-empty message. Already implemented for the former; just add the dual-message case.

### 11. Dashboard quota chip is the only freshness indicator
Sports chips show game counts but not timestamp. Hard to tell at a glance whether NBA counts are current.

### 12. Screenshot sweep captured at `/Users/mikeborucki/.playwright-mcp/` — not versioned
The `.playwright-mcp/` folder holds ~15 screenshots from this sweep. Consider adding it to `.gitignore` if it isn't already, or a quick `make ui-audit` target that writes into `docs/ui-snapshots/<date>/`.

---

## What's solid (verified working)

- Next.js 16 cross-origin dev fix — Playwright can drive the app from `localhost`.
- Global Live / Pre / All filter — verified: `Pre` hides 3/6 live NBA games; props page respects the same filter.
- `GameTime` same-day-vs-future rendering — no more HOU@CLE ambiguity.
- Visible-books persistence — toggle → "Save changes" enabled → dirty-tracking flips cleanly; revert → "No changes" disabled again.
- Book matrix primitive — sticky columns, best-price tint, sideMode toggle all render correctly.
- Props tab switching — 0-row tabs still honor filter (First Team Basket), non-empty tabs (Rebounds) light up with 694 odds cells.
- Player-name text filter — "Mitchell" → 20 rows (Donovan Mitchell at multiple alt points), proper empty state for non-roster names.
- Market tabs driven by Settings + data intersection — no dangling tabs for markets absent from the current dataset.

---

## Suggested next-sprint targets

1. **Fix P0 bugs** (dashboard quota math, empty-tab gate, EV scan verification) — half a day.
2. **Freshness chips** across arb/low-hold/ev/free-bets — quick win, ~1 hour.
3. **Alt-lines drawer redesign** — pick one approach (collapse-around-main, side sheet, or modal) and prototype.
4. **Market tab pinning** — user story: "let me pick 5 markets per sport and hide the rest unless I click 'All'".
5. **Virtualize the matrix body** — defer until first user report of lag or until MLB season shows the scale.
