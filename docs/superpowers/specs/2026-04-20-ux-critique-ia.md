# UX Critique — Information Architecture & Flow

Angle: how the pages relate, what's findable, and whether the nav model fits the job.

---

## 1. The top-level nav model

The current flat list of nine tabs mixes two orthogonal concepts: **market views** (Odds, Props, Picks) which are per-sport, and **cross-sport scanners** (Arbitrage, Low Hold, +EV, Free Bets) which are sport-agnostic. The Dashboard is a fifth shape, and Settings is a sixth. Nine peers is already at the edge of scannable, and every new scanner or sport-scoped tool makes it worse.

**Replace with a two-rail layout**, split by question:

- **Left rail — "What are you looking at?"** A persistent sidebar with three groups:
  - *Overview:* Dashboard
  - *By sport:* MLB / NBA / NHL / Tennis — each expands to Odds, Props, Picks
  - *Find edges:* Edges (consolidated), Free Bets
  - *System:* Settings
- **Top bar — "What's the state of the world?"** Global Fetcher indicator + last-refresh, and a compact search/command palette (Cmd-K) that jumps to any `sport × view × market`.

Why sidebar over tabs: nine flat tabs lose their hierarchy; a grouped rail communicates that Odds-NBA and Odds-MLB are siblings while Arbitrage is a different axis. A rail also scales — a fifth sport or a sixth scanner is a new row, not a cram.

Why sport-first inside the rail rather than tool-first: the user's mental loop is "I care about tonight's NBA slate — show me odds, then props, then edges for those games." Today they cross the tool boundary four times (Odds → Props → Arbitrage → +EV) and each crossing re-enters from the top. A sport-scoped sub-view keeps context.

## 2. Scanner consolidation

Arbitrage, Low Hold, +EV, and Free Bets are four pages with the same table shape: filter strip, opportunity rows with two book columns, a percentage/metric, a stake. Users don't think "let me check arbs, then low-hold, then EV" — they think **"what's the sharpest bet I can make right now?"** and the answer is whichever of those four has the best row.

**Consolidate into one `Edges` page with a mode toggle.** A single pill-group (`Arb · Low-Hold · +EV · Free Bets`) in the filter bar, shared sort/filter/stake controls, shared freshness chip. Additive toggles ("also show +EV ≥ 2%") are even better than exclusive modes — today there's no way to ask "show me anything above a 1% edge, whatever kind."

Trade-offs:

- *Cost:* Free Bets has a divergent column (conversion %) and a stake-input assumption; it'd need a mode-specific column slot, not full column homogeneity. Arbitrage needs a two-leg row; EV needs one.
- *Benefit:* one set of filters, one freshness chip, one keyboard loop. A user comparing a 1.8% arb vs a 3.2% EV can see both without a page change.
- *Risk:* a single page with four modes can become cluttered. Mitigation: keep direct URLs (`/edges?mode=arb`) so the nav rail can still deep-link and bookmark.

Recommendation: consolidate. The pages are currently four copies of the same spreadsheet; the 20% that differs is column shape, which is a renderer concern, not an IA one.

## 3. Settings sprawl

Settings today conflates three kinds of state:

1. **System config** — fetcher tiers, per-sport market enablement, refresh cadence. Rare, destructive-ish, correct home is Settings.
2. **View preferences** — visible books, default alt-line window, pinned markets. These should **not** live in a separate page — they belong *inline* as a "View" popover on each page, persisted per-view, with a "save as preset" path.
3. **Presets / saved views** — "my NBA spreads sweep", "MLB totals at +EV ≥ 2%". Doesn't exist yet and should.

**Split proposal:**

- *Inline view controls* on every page (visible books, market filter, live status). Filter is local by default.
- *Saved Views* — a lightweight top-bar dropdown per page, storing a named bundle of (book subset, markets, sport, mode, filters). First-class URL state.
- *Settings* shrinks to fetcher tiers, API keys, display defaults, and market-key enablement. The 60-book visibility grid moves out — it's a *view* decision, not a config decision.

The current Settings page being the only home for book visibility forces the user to round-trip `Odds → Settings → Odds` whenever they want to re-scope. That's the clearest symptom that it's in the wrong layer.

## 4. Global vs per-page filters

Live/Pre/All and Visible Books are global. This is wrong for both:

- **Live/Pre/All** genuinely *feels* global when the user is in-session ("I'm only betting live tonight"), but breaks on Settings and on the scanners when the user wants pre-game arbs while watching live odds on the Odds page. **Make it page-scoped with a "sync across pages" toggle** — default synced, but unlockable.
- **Visible Books** is much more fraught. The user has different book subsets for different jobs: all 60 for arbitrage (you need wide coverage), ~10 for odds shopping (your own accounts), 3-4 for free bets (books with promos). Forcing one global set means the user over-scopes or under-scopes constantly. **Make it per-view** with saved presets ("My accounts", "Arb universe", "Promo books").

The Fetcher toggle is correctly global — it's a system state, not a filter.

## 5. Five concrete tasks the IA makes hard today

1. **"Show me every edge on tonight's Lakers game across arbs, low-hold, and EV."** Breaks because edges live on three separate pages with no game-scoped cross-filter and no way to pivot from a game in `/odds/nba` into the scanners pre-filtered to that game.
2. **"Pin five prop markets I care about and hide the other 25 tabs."** Breaks because tab membership is driven by Settings market enablement, which is binary — there's no pin/favorite layer, and re-enabling later is a deep Settings trip.
3. **"Open arbitrage with just my three funded books + Pinnacle as the fair line."** Breaks because visible-books is one global set; switching it for an arb session pollutes the Odds page and requires another round-trip to restore.
4. **"Jump from a +EV opportunity row to the full odds grid for that game/market."** Breaks because scanner rows aren't linked back to the per-sport odds view — no "open in Odds" affordance, no shared URL schema.
5. **"Save this configuration (sport=NBA, markets=spreads+totals, books=my 4, min-EV=2%) and come back to it tomorrow."** Breaks because there's no saved-view concept; the user's filter state lives in localStorage with no name, no export, no way to switch between two configurations without re-toggling.

Common thread: the IA is organized by *tool type*, but the user works by *slate + bankroll*. The restructure should put slate (sport + game + timeframe) and bankroll (book subset) at the navigation layer, and demote tool type to a mode within a consolidated edges view.
