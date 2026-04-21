# UX Critique — Responsive Behavior & Cramped Viewports (2026-04-20)

Desktop-first app. `web/components/nav-shell.tsx` hardcodes `max-w-[1600px]` with `px-6`; no media queries anywhere in the shell, and `globals.css` has zero breakpoints. Below is how this holds up as the viewport narrows.

---

## 1. Per-route breakpoint analysis

**Dashboard** (`01c`). Top nav wraps first. At 1024 the `LiveStatusFilter` + `FetcherToggle` chips crowd the section links; at 768 the title "betting site" gets pushed to a second line and collides with the nav. Body is mostly text, survives to 480.

**Odds grid** (`02b`, `02c`, `/web/components/odds-grid/index.tsx`). Table is `w-full` with 4 fixed columns (Game/Side/Best/Consensus) + N book columns. **No `overflow-x-auto` wrapper.** At 1024 with 10 visible books, columns shrink past readability; team names `@` separator wraps. At 768 the whole table forces horizontal page scroll (bad — the header bar scrolls with it). At 480 it's unusable: Game column alone eats the viewport. Expanded alt-lines panel inherits the same problem — `BookMatrixTable` does have `overflow-x-auto` and sticky first/second columns, so it degrades more gracefully than the outer grid.

**Props matrix** (`03b`, `03c`). Tab row is the loudest break. At 1280 I count 28 tabs wrapping to 3 rows; at 1024 → 4 rows; at 768 → 5–6 rows of tabs before the user sees any data. Matrix body itself uses `BookMatrixTable` and scrolls horizontally, so it's okay once you get to it. `All games / O·U / OVER / UNDER` toolbar wraps awkwardly.

**Arbitrage / Low-Hold / +EV / Free Bets** (`05b`, `06b`, `08b`). 10+ columns, no horizontal scroll container at the page level that I can see in the screenshots — columns just compress. At 1024 the "side A / side B" book-and-price cells are already tight; at 768 they overlap the EDGE/STAKE columns. These scanners are the worst offenders — content density is irreducible.

**Picks** (`04-picks-tennis`). 8-column but light content — holds up to 768, breaks at 480 (AGENT · 30D column wraps).

**Settings** (`09`). 3-column book grid at 1280; it's a CSS grid so it'll reflow to 2-col at ~900, 1-col at ~600. Tier/market accordion is already vertical — fine. Row labels like "DraftKings" are short. Biggest issue: the accordion headers use `w-full` and the right-side counts will collide with the expand arrow at <400.

---

## 2. Book-matrix strategy (the core primitive)

Three viable patterns:

1. **Sticky left column + horizontal scroll with fade indicator.** Already half-built — `BookMatrixTable` has sticky first/second columns. Add a right-edge gradient + `scrollHint` dot when `scrollWidth > clientWidth`. Works phone-fine for the matrix variant. **Fails on the top-level Odds grid** because that table has no overflow container.
2. **Priority-bucket collapse.** Show top-3 books (by priority in `BOOK_ORDER`) + "Best" + "Consensus" at narrow widths; hide the rest behind a "+ 7 more" chip that opens a bottom sheet. Respects the user's visible-books set as the input.
3. **Card-per-row fallback.** Each row becomes a card with a best-price headline and a collapsed book strip. Kills the comparison affordance (the whole point of a matrix).

**Recommendation: #1 for every matrix, #2 only for Odds grid below 768.** The matrix *is* a grid — collapsing to cards betrays its purpose. But the Odds grid shows 2 rows per game (away/home), and on a phone the user cares about "show me the best price for this side" more than "compare 10 books across all 6 games." Below 768: render Odds as stacked game cards with best/consensus + a "compare books" tap that opens a sheet containing the full matrix with horizontal scroll. Above 768: existing table with `overflow-x-auto` added.

For the Props matrix: keep the horizontal-scroll matrix everywhere; it's already the cleanest of the three tables. Add a sticky-bottom scroll thumb at narrow widths.

---

## 3. Nav model

Current top nav (8 section links + global Live/Pre/All chips + Fetcher toggle + sport context bar below) is **~820px wide**. Fine at 1280, starts wrapping by 1024, unusable at 768.

**Recommendation:** at `md` (≤1024) collapse sections into an overflow menu behind the wordmark, keep Live filter visible (it's the highest-frequency control), move Fetcher into a Settings link. At `sm` (≤640) adopt **bottom tabs** for the 4 most-used: Dashboard / Odds / Props / Picks. Arbitrage/Low-Hold/EV/Free-Bets go into a "More" tab. Live filter becomes a floating segmented control pinned just above the bottom tabs. This mirrors native sportsbook app patterns and keeps the thumb zone hot.

Sport context bar (`SportContextBar`) should become a horizontal chip scroller on narrow widths, not a dropdown.

---

## 4. Must-work-on-phone flows

Ranked by "user on the couch / in a bar":

1. **Glance the dashboard** (live game count, fresh data, quota) — yes.
2. **Read Picks for the day** — yes, already lightweight.
3. **Scan Arbitrage / Free Bets for actionable opps** — yes, but as a *card list* sorted by margin, not the 10-col table. User needs: margin %, two books, two prices, stake split. Everything else is desktop-detail.
4. **Check a single game's best line** — yes, via Odds route rendered as stacked game cards (see §2).
5. **Toggle Live/Pre filter + Refresh** — yes, and cheap.

**Desktop-only (explicitly):**
- Settings (60-book grid × 4 sports × 20 markets — acknowledge and show a "open on laptop" message at `<640`).
- Props matrix deep-dive (too dense; offer a read-only "top prop per player" fallback on phone).
- Low-Hold and +EV scanners full tables (show card list, link "open on laptop for full table").
- Alt-lines expansion (desktop only, or a dedicated full-screen route on mobile).

---

## 5. Cramped-laptop polish (1280–1440)

Things that technically fit but feel tight on a 13" MBP:

- **`max-w-[1600px]` with `px-6` = only ~40px side gutters at 1280.** Drop to `px-4` at `<1440` or let content go edge-to-edge with 16px gutters. The current center-hugging layout wastes no space but the tables still feel packed because all 1280px of content is rendered.
- **Props tab row overflow.** 28 tabs × ~110px each = wraps to 3–4 lines eating 120px of vertical. Solve with pinned-markets (already in the audit backlog) *plus* a horizontally-scrollable tab rail that doesn't wrap — current wrapping hides the "market density" signal.
- **Odds grid book logos** (`BookLogo mode="header"`) — at 1280 with 10 books, logos render at ~80px columns with price + logo in the cell; feels busy. Either drop to logo-only headers at `<1440` or shrink to 14px icons.
- **Scanner tables' 11th column** (STATUS/EDGE) — always clipped or hugging the right edge at 1280. No horizontal scroll container means the rightmost column wraps into the next line. Add `min-w` per table with overflow-x on the parent.
- **Game-row expand caret** (`▶`) is 10px; at 1280 with tight columns it's easy to miss. Bump to 12px + add a full-row hover affordance.
- **`LiveStatusFilter` + `FetcherToggle`** compete with nav for horizontal space — at 1280 they're 280px, leaving nav with 900px for 8 links + wordmark. Tighten chip padding or stack Fetcher into an avatar-style icon with tooltip.

---

**Bottom line.** The app is a Bloomberg terminal; don't fight that on laptop — fix the specific claustrophobia points above. For phone, build a *separate* light experience (dashboard + picks + arb-card-list + single-game odds) routed by viewport width; don't try to make the scanner tables responsive. The 60-book settings grid and the props matrix are explicitly desktop features — say so in-product rather than shipping a broken mobile version.
