# UX Redesign — Synthesis & Decision Doc

Consolidates five parallel critiques:

- `2026-04-20-ux-critique-visual.md` — visual hierarchy, density, color
- `2026-04-20-ux-critique-ia.md` — information architecture
- `2026-04-20-ux-critique-power-user.md` — pro-bettor workflow
- `2026-04-20-ux-critique-novice.md` — first-time-user confusion
- `2026-04-20-ux-critique-responsive.md` — narrow-width behavior

The user is a daily power user who bets real money but has explicitly asked for UI/UX polish over stack simplicity. So: the novice-persona feedback is useful as *"teach in place"* signal, not as *"dumb the app down"* signal. The power-user feedback is the north star.

---

## 1. What all five reviewers converged on

These problems were flagged by 2+ independent reviewers. High confidence, do these.

### A. Four scanner pages are one page with four modes

*IA + power user.* Arbitrage / Low-Hold / +EV / Free Bets share 80% of their shape (filters · dual-book row · metric column · stake). The 20% that differs is the metric column. The user's question is *"what's my sharpest bet right now?"* — the answer is best-of across modes. → **Consolidate into `/edges` with additive mode toggles.**

### B. Visible-books should be per-view, not global

*IA + power user.* The book subset for arbitrage (all 60, coverage) ≠ odds shopping (~10, funded accounts) ≠ free bets (3–4, promo books). One global set forces constant round-trips to Settings. → **Per-view book scopes with named presets ("My accounts", "Arb universe", "Promo books").**

### C. Alt-lines inline drawer destroys context

*Power user (scroll loss) + responsive (viewport abuse) + novice (overwhelm) + visual (density inversion).* Four of five flagged it. Already partially mitigated by the ±5 collapse in the recent audit fixes, but the inline placement is still wrong. → **Right-docked side sheet, persistent while you scan other games.**

### D. Props market tabs — 28 wraps to 4 rows

*Power user + responsive + visual.* The tab row overwhelms before you see data. Settings enablement is a blunt knob. → **Pinned markets with a compact rail: starred markets first, rest behind "more".**

### E. Developer-facing copy leaks to users

*Novice + power user (trust) + visual (noise).* "Fetcher OFF", "/api/health", "API Quota 4,570,000", "last fetch 91m ago — fetcher may be stuck" — all speak to engineers, not users. → **Rename "Fetcher" to "Live Updates". Hide quota unless <20%. "Cache 91m old · refresh to pull fresh prices."**

### F. Empty states don't explain — they blame the filter

*Novice + power user + visual.* The +EV empty state says "try lowering min EV or widening max odds" when the actual cause might be stale cache or missing Pinnacle. → **Empty states teach: "No +EV edges right now. Cache was pulled 2h ago — refresh the fetcher for fresh data. What is +EV?"**

### G. No in-place action on rows

*Power user explicit, novice implicit.* Rows are read-only text. No stake calc, no copy, no book deeplink, no ledger log. → **Row expand = workbench.** See §3.C.

---

## 2. Where reviewers disagree — you pick

### Density

- **Power user**: wants a compact-density mode, 2x rows visible.
- **Novice**: thinks existing density is intimidating.
- **Visual**: density is *mis-allocated* — dashboard sparse, alt-matrix overwhelming.

**My take:** the answer is *range, not a global setting.* Dashboard gets denser (more info per pixel), scanners get slightly more airy per row (for action buttons). Add a `Cmd-Shift-D` compact toggle for power-user preference, but default to the polished middle density.

### Sidebar vs top nav

- **IA**: collapsible left sidebar grouped by sport + tool type.
- **Responsive**: top nav with bottom tabs on mobile.

**My take:** **collapsible left rail at ≥1280, top nav at <1280, bottom tabs at <640.** The rail gives the user sport-first navigation without losing the tables' horizontal real estate (collapsed = 56px, expanded = 220px). Three-breakpoint strategy also solves the responsive critique's nav collision issue.

### Lite / Beginner mode

- **Novice**: wants it.
- **Power user**: would never touch it.

**My take:** **skip the lite toggle**, adopt novice-friendly *language* and inline explainers as defaults. The user is a power user; the lite mode would be dead code. Keep: jargon tooltips on first use, one-line page subtitles, plain-English empty states. Drop: the beginner toggle itself.

### Phone experience

- **Responsive**: separate phone-specific layout; desktop-only for settings, props matrix, scanners.
- **Others**: silent.

**My take:** phone is a Phase 3 concern, not Phase 1. Ensure the redesign doesn't actively break mobile (no hardcoded min-widths, sticky columns, overflow containers), but don't spend design effort on per-phone layouts yet. The user described a 13" MacBook as the small screen.

---

## 3. Proposed redesign — three phases

### Phase 1 — Shell + system refresh (low risk, high polish)

Pure visual + structural work. No new features. Ships in one sitting.

**Nav shell:**
- Collapsible left rail replacing top nav at ≥1280. Groups: *Overview* (Dashboard) / *By sport* (MLB/NBA/NHL/Tennis, each → Odds/Props/Picks) / *Edges* (Arbs/Low-Hold/+EV/Free-Bets placeholder, will consolidate in Phase 2) / *System* (Settings).
- Top bar keeps wordmark, global live filter, freshness chip, Cmd-K search.
- "Fetcher OFF" → "Live updates OFF" with cost-only-in-Settings warning.

**Visual system:**
- Type scale `10/11/12/13/15/20/28`; weights `400/500/600` only.
- Dashboard KPIs: 36px → 28px, 50% shorter cards, recover vertical.
- Color reassignment: cyan → current-location only. Green/red get opacity ramps for magnitude on arb/EV/hold %. Violet → "sharp book" marker (Pinnacle/Circa).
- Fourth elevation `bg-3` for sticky columns and drawer surfaces.
- Empty states: bordered `bg-1` panel + icon + headline + CTA.

**Copy pass:**
- Remove dev-facing strings. "API Quota" hidden unless <20%. "Fetcher" → "Live updates". "/api/health" error link nuked.
- Every page title gets a one-sentence subtitle explaining what it does.
- Jargon gets dotted-underline + hover tooltip on first occurrence per page: `EV`, `hold`, `edge`, `consensus`, `Pinnacle`, `de-vig`, `unit`.

**Est. scope:** ~600 LOC across `nav-shell.tsx`, `globals.css`, `book-matrix-table.tsx`, all page `<h1>`s.

### Phase 2 — Structural IA (medium risk, high value)

The big rearrangement. Ships in two or three sessions.

**Edges consolidation:**
- New `/edges` route replacing `/arbitrage`, `/low-hold`, `/ev`, `/free-bets` (keep redirects for bookmarks).
- Mode chip group: `Arb · Low-Hold · +EV · Free Bets` (additive, not exclusive — "show me anything ≥1% edge regardless of kind").
- Shared filter bar: sport, live/pre, book scope, min-edge, max-odds, stake.
- One freshness chip, one refresh button, one keyboard loop.
- Row shape adapts per mode (arb: two legs; EV: one offered + one fair; free-bet: leg + conversion).

**Book-scope refactor:**
- Per-view state (not global). Named presets on a lightweight dropdown per page.
- Default presets seeded at first login: "My accounts" (current 10), "Arb universe" (all 60), "Promo books" (free-bet-eligible subset).
- Global Visible Books in Settings becomes the "My accounts" preset.

**Props market pinning:**
- Star icon per tab. Starred tabs pin to the left; unstarred go behind an overflow chip at the right. Per-sport storage.
- Defaults for each sport (NBA: Points / Rebounds / Assists / Threes). User starring overrides.

**Alt-lines side sheet:**
- Expansion caret opens a right-docked sheet (~40% viewport width), persistent across game-row clicks. Close button returns to grid.
- `BookMatrixTable` primitive reused inside.

**Est. scope:** ~1500 LOC, new route, schema migrations for saved views / pinned markets.

### Phase 3 — Workbench row (ambitious, highest user impact)

The feature the power-user critique called out as "the one thing that would make me switch." Do this last — it depends on Phase 2 being stable.

**Workbench row:**
- Every `/edges` row is expandable (chevron left of the % cell).
- Expanded state: bankroll input (global, persisted), Kelly fraction, computed stakes per leg, rounded to $5/$25/$100 toggle, net-profit preview, "Open both books" buttons with deeplinks (requires per-book bet-slip URL schema — builds on existing book registry), and **"Log to ledger"** — writes to a new `bets` table.

**Ledger / portfolio:**
- New `/ledger` route under *Overview*: what I staked today, per-game exposure, running CLV, per-book stake totals vs configured limits.
- Per-book stake-limit input in Settings ("Fanatics max $250 NBA spreads").
- CSV/JSON export.

**Est. scope:** ~2000 LOC backend + frontend. Needs a real DB migration for bets/ledger.

---

## 4. What the reports explicitly said NOT to change

(From visual critique, confirmed by power user in passing.)

- `MAIN` chip at 9px uppercase — load-bearing tertiary.
- Sticky first-column opaque seam — keep, translucent breaks horizontal-scroll readability.
- Live-pulse keyframe intensity — intentionally halved; louder would hurt on 6-live-game pages.
- `tnum` + `ss01` font features — non-negotiable for a data terminal.
- Tennis Picks layout — cited by power user as the cleanest view; use it as the template for Phase 2 row redesign.

---

## 5. Decisions I need from you before I build

Answer each with a quick direction and I'll execute in order.

1. **Nav model** — left rail grouped by sport (my rec) vs keep top nav and just reorganize? Left rail eats ~220px; tables may want it.
2. **Edges consolidation** — yes / no / keep separate but share a filter bar?
3. **Visible books per-view** — yes (with presets) / no (keep global) / yes-but-not-yet?
4. **Phase ordering** — my rec is `1 → 2 → 3`. Alternative: do Phase 3 workbench first because it's the biggest impact, defer IA restructure?
5. **Novice guardrails** — adopt jargon tooltips + plain-English empty states + copy pass (my rec, all flavor, no real cost)? Or skip because you're the user and you know the vocab?
6. **Ledger / portfolio** — in scope for this pass, or out-of-scope (new Phase 4)?
7. **Mobile** — strictly "don't break it" now, or commit to a phone-optimized pass? My rec is the former.

Once you've answered these, I'll write a concrete Phase-1 plan (component-by-component changes) and start executing.
