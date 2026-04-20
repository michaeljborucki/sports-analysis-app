# +EV Scanner — Implementation Status (2026-04-20)

## ✅ Shipped

Full-stack +EV tab complete. 69 tests pass, TypeScript typecheck clean, app boots cleanly, API returns well-shaped opportunities end-to-end.

### What +EV is (one sentence)
A bet where the offered price beats a sharp estimate of true probability, yielding long-term positive return: `EV = p_true × (decimal_odds − 1) − (1 − p_true)`.

### Fair-probability model
Two-tier cascade per market:
1. **Pinnacle no-vig (primary)** — devig Pinnacle's price. Used for mainlines (ML/spread/total/team-total + all period variants). High confidence.
2. **Consensus no-vig (fallback)** — per-book devig, then median across sharp books (`pinnacle`, `betonlineag`, `lowvig`); falls through to all books if <2 sharp cover the market. Used when Pinnacle absent.

Devig method: **multiplicative** (industry default). Supports 2-way and 3-way (soccer) markets.

### Files

**Backend**
- `server/odds/devig.py` — added `devig_n_way`, `american_to_decimal`, `implied_to_american` (2 new lines of utility, preserves existing signatures).
- `server/odds/ev.py` — new math module. Public entry `scan_all_ev(games, now, ...)`. Handles bucket-pairing per market type (h2h, spreads by |point|, totals by point, team_totals by (team_prefix, point), 3-way by single bucket). Period suffixes stripped via regex (basketball halves/quarters, hockey periods, baseball `_1st_N_innings`/`_fN`).
- `server/odds/market_config.py` — extended `PROP_MARKET_PREFIXES` to include `player_` (covers NBA/NHL). Affects arb too (prop markets already skipped there for the same reason).
- `server/api/ev.py` — new route `/api/ev`. Query params: `min_ev`, `max_longshot_odds`, `books`, `sharp_books`, `stale_seconds`, `max_results`, `tag_arb`. Response: `EVResponse` Pydantic model. Skips prop markets v1.
- `server/main.py` — router registered after free_bets.
- `server/tests/test_ev.py` — 16 tests covering golden math, consensus fallback, sharp-self-anchor exclusion, stale filter, longshot cutoff, low-confidence flag, also_in_arb, 3-way soccer, alt-line pairing, sort, max_results cap.

**Frontend**
- `web/lib/sections.ts` — `+EV` tab between Low Hold and Free Bets, global scope.
- `web/lib/api.ts` — `apiPaths.ev(books, {minEv, maxLongshotOdds, staleSeconds})` + `EVResponse` / `EVOpportunity` types.
- `web/types/api.ts` — regenerated from OpenAPI spec.
- `web/app/ev/page.tsx` — matches low-hold/free-bets layout. Columns: EV%, Kelly% (¼), $ (at user stake), Sport, Event, Market, Outcome, Offered (book + price), Fair (source badge PIN/CON + fair price), Starts, Flags (ARB/SUS/STALE). Filters: Min-EV chips (All/1/2/3/5%), Max-odds chips (All/+300/+500/+800), Source toggle (All/PIN/CON), Live/Pre, Offered-book dropdown, Stake $ input (localStorage `ev-stake`), global BookFilter, Refresh.

### Industry defaults applied
- Min EV: 2% (chip presets 1/2/3/5)
- Max longshot odds: +800 (devig noise cutoff)
- Stale cutoff: 60s drop, 30s grey-flag
- Kelly: quarter-Kelly displayed alongside full-Kelly in EV math
- Two-book display: offered price + Pinnacle no-vig side-by-side (the OddsJam pattern)
- Confidence cap: EV > 15% → `confidence: "low"` → SUS badge (usually stale/mispriced)
- also_in_arb cross-tag: ARB badge for bets also flagged by the arbitrage scanner

### Known V1 limitations
- **~~Player props skipped.~~ FIXED.** `_encode_outcome_name` in `server/odds/normalize.py` now embeds player identity into the `outcome_name` for all player-prop markets (`player_*`, `pitcher_*`, `batter_*`). The scanner's `_pair_bucket` extracts the player prefix from the outcome name and buckets `(market_key, player, point)` so Over/Under pair per player. 7,367 pre-fix orphan rows were purged from cache; new fetches write the correct format. Two new tests lock in the pairing behavior + the old-row safety net.
- **No per-row bet-details drawer.** Deferred per research-agent recommendation — revisit after first week of use.
- **Paper-vs-real gap.** Subtitle discloses that displayed EV is theoretical; limits and closing-line movement typically erode 1–2%. This matches Unabated/OddsJam convention.
- **Live market noise.** Devig breaks in-play (asymmetric info). UI exposes a Live toggle but applies no EV penalty — users should treat in-play EV cautiously.

### Math correctness notes
- Market-aware pairing buckets handle alternate_spreads (paired by |point|), team_totals (paired by (team_prefix, point)), and all period variants (stripped via regex before bucket lookup).
- Bucket mispairings (e.g., "Team A -1.5" with "Team B -1.5" at same raw point value) prevented by the |point| canonicalization for spreads.
- Pinnacle is always excluded from offered-side output when it's the anchor — no "Pinnacle +2% EV" rows.
- Prices consumed are already commission-adjusted via `rows_to_games` — no double-counting.

### Where to go next
1. **Player-prop keying fix** in `normalize.py` → enables `/ev` coverage of the largest EV surface.
2. **CLV tracking** — log placed bets and compare to closing Pinnacle price. Real validation signal that paper EV → real EV.
3. **Shin's method toggle** for 3-way and heavy longshot markets (per-user preference).
4. **Bankroll-aware sizing** — replace flat Stake input with multi-fraction sliders (¼ / ½ / full Kelly).

### Revert
Purely additive. To roll back: `git rm server/odds/ev.py server/api/ev.py server/tests/test_ev.py web/app/ev/page.tsx`, remove the `ev_router` import + registration in `server/main.py`, remove `ev` entry from `web/lib/sections.ts`, revert the `PROP_MARKET_PREFIXES` tuple in `market_config.py` to `("pitcher_", "batter_")`, and remove the ev types/apiPaths block from `web/lib/api.ts`. No schema changes. No external dependencies.
