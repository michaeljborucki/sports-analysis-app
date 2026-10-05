# betting-site — what it is, what it does, what's broken (2026-10-02)

Groundwork for the visual redesign. Built from a full read of `web/`, `server/`,
ROADMAP.md, all specs/plans, git history, and live screenshots of every page
(`.playwright-mcp/audit/*.png`).

## 1. The product in one paragraph

A local, single-user **trading terminal for a sharp sports bettor**. It pulls
prices from ~15 sportsbooks (Odds API via the separate `betting-db` poller),
plus direct feeds from **Coral33** (offshore book, 7–8 sub-accounts),
**Kalshi** and **Polymarket**. It scans every market, including player
props, for **arbitrage, low-hold, +EV, free-bet conversion and profit-boost**
opportunities. It also watches the owner's real money: Coral33 balances and
open parlay slots, and a unified bet ledger with CLV. The money loop: find an
edge → size it with Kelly ($10k bankroll, half-Kelly) → **place by hand**
(auto-bet sidecar was built then deliberately removed) → hedge/middle at
regulated books → track balances and CLV. Nothing in the app places bets.

## 2. Pages, ranked by real importance

| # | Page | Job | State |
|---|---|---|---|
| 1 | **Edges** (`/edges`) | Find and size the bet. Five modes: ARB / LH / EV / FB / PB. Expandable row "workbench" with Kelly calc + deeplinks | Core page. 995-line file; 8–10 mixed-style filters whose meaning changes per mode; **fake trend sparkline**; "Save to ledger" is an `alert()` stub |
| 2 | **Accounts** (`/accounts`) | Coral33 sub-accounts: balance, available, pending, free play, open-parlay-slot status | 1,631 lines (~280 dead); two conflicting freshness signals; vestigial "Bets" tab |
| 3 | **Systems** (`/systems`) | Which of 53 VSiN-style trend systems qualify today (MLB / CFB / NFL) | Newest feature. **Dumps raw ESPN 400 errors on screen**; ~10s API |
| 4 | **Odds** (`/odds/[sport]`) | Line shopping grid: game × book, best price highlighted, alt lines side sheet | 13 sports. Not density-aware; double stale indicators |
| 5 | **Props** (`/props/[sport]`) | Player-prop matrix (O/U × book), pinned market tabs | Sport switcher offers sports that have no props |
| 6 | **Bets** (`/bets`) | Unified ledger (Coral33 + Kalshi + Polymarket + CSV), ROI rollups, CLV chart | Most off-system page visually; CLV chart uses CSS vars that don't exist |
| 7 | **Dashboard** (`/dashboard`) | Triage: top arb, top EV, sport rail, starting soon, system stats | **Hero chart is fake (seeded random data)**; slow first load |
| 8 | **Settings** (+ Mapping health) | Sports/markets/books config, density | Crowded header; Mapping health page is essentially unstyled |

Removed: **Picks** (2026-10-02, this session), **Sidecar auto-bet** (in the
uncommitted working tree), and `/arbitrage` `/ev` `/low-hold` `/free-bets`
(now redirects into Edges).

## 3. What the user cares about (from history and specs)

- **Freshness = trust.** Stale-looking-fresh data (+239% stale arb, 4570% quota bug) is the worst failure. Target ~1 min.
- **Never silently drop markets.** He audits.
- **Speed.** A page-load regression halts all other work.
- **Density with legibility.** "Bloomberg terminal for betting", explicitly *not casino*: no neon, no glassmorphism, no NASCAR logo walls.
- **Workbench, not viewer.** Sizing, deeplinks, ledger, keyboard (⌘K, `?`).
- UI polish is explicitly worth extra complexity.

## 4. Design system today and why it feels generic

`web/app/globals.css` defines the tokens: slate-navy surfaces (`#0B0F14` /
`#131A22` / `#1C2530`), Geist Sans + Geist Mono, cyan accent `#22D3EE`, violet
`#7C5CFF`, green/red price colors, amber flash. That's the default dark-SaaS
palette. On top of that, the rules are documented but not followed:

- **Color roles are violated everywhere.** Docs: cyan = "current location
  only", violet = "sharp books only", amber = "stale only". Reality: violet =
  EV and PB mode color and snapshot mode, cyan = LH mode, Systems tabs, Save
  button; amber = FB mode. Green means both "ARB mode" and "best price".
  Result: color carries no reliable meaning.
- **Type scale exists but isn't used.** 7 token uses vs `text-[11px]` ×123,
  `text-[10px]` ×95, `text-[9px]` ×24.
- **No shared primitives.** 4 different page-header styles; table headers
  copy-pasted; 7+ hand-rolled segmented controls (Systems' is solid cyan,
  unlike all others); 3 different freshness components with 90s vs 300s
  thresholds; 2 chart systems (hand-rolled SVG + Recharts).
- **Density only half-wired.** Only edges + matrix tables honor it; Odds,
  Accounts, Bets and Systems use hard-coded padding. The ⌘⇧D hotkey only works on /settings.
- **Wave 2 TODO list in globals.css is mostly undone.**

## 5. Fake / dead / broken things to resolve during the redesign

- Fake: dashboard edge-volume hero (seeded PRNG), Edges trend sparklines (×2).
- Stubs/no-ops: "Save to ledger" `alert()`, palette "Refresh all" (no listener), palette "Fetcher on/off" (superseded by cache mode).
- Dead code: `arbitrage-table.tsx`, `book-filter.tsx`, `fetcher-toggle.tsx`, `props-table/`, Accounts `BetsTable`.
- Missing from ⌘K: Systems, Accounts, Bets, Profit Boost, most sports.
- Cache-mode chip renders "LATEST" until its first poll, then flips to "LIVE".
- Systems page prints raw ESPN error URLs; one ESPN-backed test also fails on the live 400.
- `web/types/api.d.ts` is a stale duplicate of `types/api.ts`.

## 6. Implications for the redesign

1. **Color must mean something again.** Pick a small role set (edge
   magnitude, best price, stale/warning, live, sharp book, current location)
   and give modes a non-color identity (label/glyph), or a palette that doesn't
   collide with the roles.
2. **Build primitives before re-skinning pages.** PageHeader, DataTable (density-aware),
   Segmented, FreshnessChip (one threshold), Chip/Badge, StatTile, one chart kit.
   Re-theming without these means touching every page by hand.
3. **Edges and Accounts get first design attention.** That's where the money
   decisions happen.
4. **Remove fake data rather than prettify it.** The dashboard hero needs a
   real time series or a different job.
5. **Personality comes from typography + number rendering + restraint,** not
   neon. A terminal aesthetic with a distinctive numeric face and a committed,
   minimal palette.
