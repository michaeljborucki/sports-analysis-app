# Gunmetal redesign — spec (2026-10-02)

Chosen by the user from the Claude Design canvas
(https://claude.ai/artifact/REeJtfX6VPgKV8GBZVXhcU, direction C "Instrument", palette
"Gunmetal"). Background analysis: `2026-10-02-product-understanding.md`.

**Scope: visual and UX only.** No API, data, scanner, fetcher or cache-mode
behavior changes. Every page keeps its data, filters and actions unless this spec
says to remove one (only fake data and dead stubs are removed).

## 1. Palette — every color has exactly one job

| Token (Tailwind name) | Hex | Role |
|---|---|---|
| `bg-0` | `#27292C` | App ground |
| `bg-1` | `#2F3135` | Surfaces: panels, table headers, rail |
| `bg-2` | `#36393D` | Raised: hover, selected row, active segment, inputs |
| `border-subtle` | `#42454A` | Rules and borders |
| `text-1` | `#F1F0ED` | Primary text |
| `text-2` | `#AEACA7` | Secondary text |
| `text-3` | `#7F7D78` | Tertiary, column headers, units |
| `edge` | `#EDA845` | **The number to act on**: edge %, best price, EV, arb ROI, locked profit. Magnitude ramp `--edge-10…90`. |
| `gain` | `#7DCB9A` | Money won / positive P&L / positive CLV |
| `loss` | `#F0715F` | Money lost / negative P&L / negative CLV |
| `stale` | `#E58AA0` | Stale or warning only: old prices, failed scrapes, unable-to-evaluate |
| `live` | `#FF5A4E` | The live-game dot and LIVE label only |
| `sharp` | `#A99BE8` | Sharp-book marker (Pinnacle, Circa, BetOnline, LowVig) only |
| `accent` | `#F1F0ED` | Current location. Rendered as `text-1` + `bg-2`, never as a hue. |

Rules:
- **Modes (ARB / LH / EV / FB / PB) are not colors.** They're named with text labels. A mode chip is neutral (`bg-2` + `text-2`).
- Price-change flash is neutral: a white wash at 14%, not amber.
- Old tokens are aliased during migration: `price-up` → `gain`, `price-down` → `loss`, `flash` → `stale`, `violet-accent` → `sharp`. Pages must move to the new names. **No new code may use the old names.**
- No raw Tailwind palette colors (`text-amber-400`, `bg-black/40`) and no hex values in TSX, except `lib/books.ts` brand colors.

## 2. Type

- **Schibsted Grotesk** (`--font-sans`) for all UI text. **JetBrains Mono** (`--font-mono`, `.tabular`) for numbers only: prices, %, $, counts, times. Mono is never used for words or labels.
- Scale (use the tokens, not `text-[Npx]`): 11 meta · 12 table header/meta · 13 table body · 14 controls/body · 16 section title · 22 page title. Weights 400/500/600/700.
- Sentence case everywhere. No all-caps labels, no tracking-wide headers, no "A · B · C" meta strings.

## 3. Layout and shell

- **Left rail nav** (≥1024px, 184px): wordmark, ⌘K search, sections; then at the bottom the Live/Pre filter and data-source (cache mode) status. Below 1024px it collapses to a top bar.
- Main column: fluid, `max-w-[1680px]`, padding 24/32.
- Per-sport pages keep the sport switcher, placed in the page header row (not a separate bar).

## 4. Shared primitives (`web/components/ui/`)

`PageHeader`, `Segmented`, `Chip`, `Panel`, `StatTile`, `EdgeBar`, `Freshness`,
`ErrorBanner`, plus table classes `.dt-head` / `.dt-th` / `.dt-row` / `.dt-td`
(density-aware) in `globals.css`. Pages must use these. Don't hand-roll new
segmented controls, headers or freshness chips.

## 5. Page work

| Page | Changes |
|---|---|
| Edges | Mode segmented control with counts; **sentence filter bar** (each clause is a button opening the existing control); edge cell = `EdgeBar` + mono number; remove fake trend sparkline column and the workbench sparkline; remove the "Save to ledger" `alert()` stub; stale rows: `stale` tint + "price Nm old"; workbench = stake tiles + "Open both books" / "Copy legs". |
| Accounts | Stat tiles; gain/loss colors for balances and P&L; chart recolored to tokens; delete dead `BetsTable`/`BetRow` and the vestigial Bets tab; one freshness signal (account scrape age). |
| Bets | Bring onto the shell's primitives; fix `CLVChart` broken CSS vars; gain/loss; derive sport filter from `SPORT_ORDER`. |
| Odds / Props / alt lines | Best price = `edge` text + `--edge-10` wash (not green); sticky first column on the odds grid; density-aware cells; one freshness indicator (drop the duplicate banner). |
| Dashboard | **Replace the synthetic edge-volume hero** with real data: live edge counts per mode plus the top 5 edges list. Top arb/EV cards restyled. |
| Systems | Collapse raw ESPN error dumps into one `ErrorBanner` ("Football context unavailable from ESPN, 14 systems can't be evaluated", details in a disclosure); timeframe uses `Segmented`. |
| Settings / Mapping health | Restyle onto primitives; Mapping health gets real table styling. |
| ⌘K palette | Add Systems, Accounts, Bets, Profit boost, all sports; remove the dead "Refresh all" and the legacy "Fetcher on/off" commands; make the density hotkey global. |

## 6. Done means

`npx tsc --noEmit` clean apart from known `app/bets/` errors (ideally fixed),
`npm run build` passes, every page screenshot-verified in the running app
(production build on :3000), and no page loads slower than before.
