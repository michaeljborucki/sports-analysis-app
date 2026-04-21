# UX Critique — Visual Design, Density, Typography, Color

Angle: visual hierarchy, density, typography, color, look-and-feel. Screenshots referenced live at repo root.

---

## 1. Three things that are already good

1. **The neutral bg ramp (`bg-0` → `bg-1` → `bg-2`, `border-subtle`) in `web/app/globals.css`.** Four steps is the right number for a data terminal — enough separation for sticky headers, row hover, card lift, and drawer elevation without needing shadows. `#0B0F14 / #131A22 / #1C2530 / #263140` is a tasteful cool-gray ramp with good 1px-border readability on dark. This is *the* thing competitors like oddsjam get wrong (they flatten to one bg and then fight with shadows).
2. **Tabular numerics are actually on** (`font-feature-settings: 'tnum' 1` body-wide plus `.tabular` helper). Look at `02c-odds-nba-expanded.png` — the `+425 / -500 / +375` column reads as a true grid, not a ransom note. Same for the dashboard's `4,569,756` quota number. This is the single biggest thing separating "looks like a spreadsheet" from "looks like a Bloomberg terminal" and they already did it.
3. **Best-price green tint in `book-matrix-table.tsx` (lines 227–234) and the MAIN chip at `bg-accent/15 text-accent`.** The best-per-side-per-row highlight in `02c` is subtle but guides the eye exactly where a bettor looks. The 9px uppercase `MAIN` pill is a good restrained use of the accent — it says "this row matters" without screaming.

---

## 2. The five biggest visual-design problems

### P1. The header is generic SaaS and the ◆ wordmark is soft

`01-dashboard.png` top-left: a cyan diamond + "betting site" in regular weight, flanked by 8 nav items in identical grey weight, with the only active-state indicator being a thin 2px cyan underline. For a daily-use terminal, the chrome should recede harder (or brand harder) — right now it occupies ~56px of permanent vertical space with no personality and no information density. The `max-w-[1600px]` in `nav-shell.tsx:54` also leaves big empty gutters on a 1920 display while the matrix inside is hitting its scroll limit.

**Better:** 40–44px header, monospace or condensed wordmark at 12px uppercase tracked, active-section indicator is a **left-of-label accent dot** instead of an underline so descenders aren't clipped. Stretch main to `max-w-none` with `px-8` — the tables want the pixels.

### P2. Color system underuses green/red and overuses cyan

`globals.css` defines `price-up: #2CB459`, `price-down: #E5484D`, `accent: #22D3EE`, `violet: #7C5CFF`, `flash: #F5A524`. In practice (`02c`, `05b`, `06b`) cyan is everywhere — nav active state, MAIN chip, LIVE chip, accent-tagged rows, focus ring, refresh button, `◆` logo — while violet never appears and flash is confined to freshness warnings. Meanwhile the *semantic* colors (up/down) only tint best-prices and don't distinguish positive-EV from negative-EV rows, fav from dog, or positive-hold from arb. The page reads cyan-monochrome with sparse green dots.

**Better:** demote cyan to a single job (current-section indicator). Use green/red with variable intensity (e.g. `price-up/30` → `price-up/100`) to encode magnitude in arbitrage %, EV %, and hold %. Reserve violet for a second semantic axis — e.g. "sharp / Pinnacle-originated" rows so the user can see sharp-vs-square at a glance.

### P3. Table typography is one size, one weight — no hierarchy inside rows

In `02c` the team name, the side label (O/U), the sport tag, the odds cell, and the kickoff time are all roughly 12px. `book-matrix-table.tsx` uses `text-xs` / `text-[11px]` / `text-[10px]` for nearly everything. The result: a row like `Raptors +425 / Cavaliers -500` reads as a uniform field of numbers — your eye has to *count columns* to figure out which side is which.

**Better:** introduce a proper micro-scale — `10 / 11 / 12 / 13 / 15 / 20` px. Team/player name at 13 medium; odds at 12 tabular regular; side label and book chip at 10 uppercase tracked; section titles at 20. Weight contrast (400 vs 600) inside the row does more than color contrast ever will.

### P4. Density is mis-allocated: dashboard is sparse, alt-matrix is punishing

`01-dashboard.png` has 4 giant KPI cards eating the top third with `131`, `24`, `5`, `0`, `4,569,756` set at ~36px — airport-departures-board scale for numbers the user glances at once a day. Meanwhile `02d-odds-nba-spread-expanded.png` crams ~60 alt-point rows × ~15 book columns into one inline block, un-zoned, with every row the same height and weight. The priorities are inverted: the page you use hourly is underdense, the drawer you use occasionally is overdense.

**Better:** dashboard KPIs → 20px numeral + 11px uppercase label, half the card height, put *sparklines* or last-15-min deltas in the recovered space. Alt matrix → zebra bands every 5 rows, bold the main line row, fade alt rows >±3 points from main to `text-3` so the eye snaps to the neighborhood that matters. The audit doc's P1 #4 also calls out scroll-dominance — collapse-to-top-N-around-main is the right default.

### P5. The loading skeleton and empty states are the same shade of "nothing"

`02-odds-nba.png` (skeleton) and `07b-ev-loaded.png` (empty state) both render as a near-identical field of grey on bg-0. The EV page says "No +EV edges match current filters" in `text-text-2` (`#9AA5B4`) centered on a void — it looks like the page failed to load rather than "your filters are too tight." Shimmer skeleton is fine but should be visibly shimmering; empty states need an illustration or at least a dashed container + primary CTA.

**Better:** empty states get a bordered `bg-1` panel with an icon, headline at 15 medium, dim explanation at 12, and a **primary** suggested action button (cyan fill, not ghost). The shimmer needs higher contrast between `bg-1` and `bg-2` stops — currently so subtle it reads as static.

---

## 3. Proposed visual system refresh

**Type scale** (currently ad-hoc `text-xs`, `text-[10px]`, `text-[11px]`): adopt **10 / 11 / 12 / 13 / 15 / 20 / 28** px. Body default 13. Table cells 12 tabular. Micro-labels 10 uppercase tracked +0.06em. Page titles 20 semibold. Hero KPI 28 semibold — not 36.

**Weight scale**: 400 / 500 / 600 only. No thins, no blacks. Inter's 500 is the workhorse for row labels; 600 is reserved for section titles and best-price cells.

**Spacing scale**: collapse to a 4-based rhythm `4 / 8 / 12 / 16 / 24 / 32 / 48`. Current CSS uses a mix of `px-2 py-1.5`, `px-3 py-2`, `py-4` — fine, just audit against the scale. Table row padding should be 6v/10h, not 8v/12h (Bloomberg-dense, not Notion-airy).

**Color — reassignment, not new tokens**:
- `accent` (cyan) — *only* current-section / current-tab indicator. Remove from: logo diamond, MAIN chip, LIVE dot (use `price-down` — it's already red), focus ring (use `text-1` outline).
- `price-up / price-down` — add 20/40/60/100 opacity ramps. Use the ramp to encode magnitude on EV%, arb%, hold% cells. Bad cell at 20% red bg, great cell at 60% green bg.
- `violet` — currently dead. Assign it a job: "sharp-book origin" (Pinnacle, Circa) row marker. Gives users a second semantic axis.
- `flash` (amber) — keep for stale/warn, don't expand.

**Dark theme working?** Mostly yes. The ramp is correct; the problem is *variety within it*. Add one more elevation tier — `bg-3: #242F3D` — for sticky first-columns and drawer surfaces so they read as lifted without needing a border. The 1px `border-subtle` lines in the matrix are doing work that elevation should do.

**Accent uses (target three max)**: (1) cyan = current-location, (2) green/red ramp = price/EV magnitude, (3) violet = sharp-origin. Everything else is greyscale.

---

## 4. What NOT to change

- **The `MAIN` chip's 9px uppercase +0.1em tracking** (`book-matrix-table.tsx:192-197`). Looks "too small" but it's load-bearing tertiary metadata that has to coexist with a player name without competing. Leave it.
- **The sticky first column's opaque `bg-bg-1` on a bg-0 table** (`book-matrix-table.tsx:110, 186-188`). Looks unattractive at the seam but breaks the instant you make it translucent — numbers bleed through on horizontal scroll. Keep the hard edge.
- **`max-w-[1600px]` on narrow pages (dashboard, settings, +EV)**. Looks empty on 27" monitors, but expanding it would push the KPI cards apart and break alignment with the nav. Let those pages stay constrained; only the matrix routes (`odds`, `props`, `arbitrage`, `low-hold`, `free-bets`) need full-bleed.
- **The live-pulse keyframes** (`globals.css:37-52`). The "halved intensity + infinite" note in the comment is deliberate — a louder pulse on a page with 6 live games would be migraine-inducing. The restraint is correct.
- **Tabular-numerics and the `ss01` stylistic set** (`globals.css:23`). Non-negotiable for this product. Any font swap must preserve both.