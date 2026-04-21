# Exchange Liquidity Filter — Framework

**Date:** 2026-04-20
**Status:** Design — **NOT BUILT YET**
**Scope v1:** ProphetX (US exchange). Framework extensible to Novig, Sporttrade, Matchbook, Smarkets, Betfair.

---

## Problem

Exchange orderbooks have **tiered liquidity per price level.** The Odds API (our current sole source for exchange prices) returns only top-of-book — the best price, no size attached. In practice, top-of-book on an exchange is often posted by a single small order that can't support a real bet.

**Your example:** ProphetX shows Over at +120, but only $2 is available at that price. The next level down (+118) has $17,000 of real depth. If you try to bet $100 at +120, you fill $2 @ +120 and the remaining $98 fills at worse prices. Your effective average is much worse than +120.

For the scanner to produce **actionable** prices, it needs to filter displayed prices to levels that can actually absorb a realistic stake.

---

## What's needed

Three things, none of which we have today:

1. **Orderbook depth data per exchange** — price *and* size per level, not just the top price
2. **Minimum-liquidity filter** — per-book or global threshold, configurable
3. **Price selection logic** — walk the orderbook from best to worst, return the first level whose available size meets the threshold

Without (1), (2) and (3) are moot. **The blocker is the data pipeline, not the filter math.**

---

## Data source options (ranked)

### A. Direct ProphetX integration (recommended for v1)
ProphetX has a public-facing API used by their web app. Reverse-engineer from their site (Copy-as-cURL, same approach as we used for coral33) and pull orderbook snapshots per market. Returns full depth per outcome. Same integration pattern as `server/odds/books/coral33/`:

```
server/odds/books/prophetx/
  client.py        # auth + orderbook fetch
  normalizer.py    # depth row → cache
  fetcher.py       # polling tier
```

New cache schema change or sibling table: store multiple rows per (event, market, outcome, bookmaker) — one per price level, with a `size` column.

**Effort:** ~4–6 hours (similar to coral33), depends on whether ProphetX's API needs TLS impersonation / JWT / etc. like coral33 did.

### B. The Odds API's "premium" markets
Some Odds API plans expose an "exchange_volumes" or similar field. Haven't confirmed availability on our plan; would need to check docs + pricing. If available, this is the cheapest integration (one API call, no auth/TLS headaches).

**Effort:** Unknown pending doc check. Could be ~1h if it's just a flag, or not available at all.

### C. Third-party scrapers / aggregators
Services like Bet IQ / Betstamp sometimes expose exchange depth. Expensive, usually paid. Low priority.

---

## Data model change

Our current cache is one row per (event, bookmaker, market, outcome, point). To store depth, we'd need one of:

### Option A: Multiple rows per outcome (simpler)
Extend the PK to include a level index: `(event_id, bookmaker_key, market_key, outcome_name, outcome_point, depth_level)`.

- `depth_level=0` → best (top of book)
- `depth_level=1` → second best
- `size` column stores available amount at that level

Everything existing stays the same for non-exchange books (just one row at `depth_level=0`). Exchanges get N rows.

### Option B: JSON orderbook column
Single row per outcome with an `orderbook_json` column: `[{price: 120, size: 2}, {price: 118, size: 17000}]`.

Cleaner for reading the whole ladder; messier for querying "give me all prices ≥ threshold." SQL-hostile.

**Recommendation: Option A.** Queries stay simple, scanners already know how to iterate rows, "show me the best filtered price" becomes a WHERE clause (`size >= :min_liquidity ORDER BY price LIMIT 1`).

---

## Filter design

### Global setting
Add to the Settings page under a new "Exchange liquidity" card:

```
Minimum level size: [  $100  ] [25 | 100 | 500 | 2500]
  Only show exchange prices with this much available at the quoted level.
  Below this, the next-best level is used instead.
```

Persist to localStorage `exchange_min_liquidity_usd`.

### Selection rule per outcome
For each exchange book on an outcome, iterate depth levels from best to worst, return the first level with `size >= min_liquidity_usd`. If no level clears the threshold, suppress this book entirely for that outcome.

Non-exchange books ignore the filter (they don't have depth data, their posted price is "the price" and the book's limits are separately capped).

### UI display
Small badge on exchange prices: `(liq: $17k)` — shows which level we landed on. Red badge if the posted top-of-book was filtered out: `(liq: next level)` or similar.

---

## Scanner integration

Arbitrage / low-hold / free-bets / EV all read from the cache via `rows_to_games`. Selection logic:

- **Without liquidity filter** (non-exchange book): use `depth_level=0` — same as today
- **With liquidity filter** (exchange book, user has `min_liquidity > 0`): select the min-`depth_level` row where `size >= min_liquidity`. If none, exclude the book.

This is a **query-time decision**, applied when `rows_to_games` emits per-book prices. No scanner code changes beyond that.

---

## UX note: blended-stake pricing (not in v1, flagged)

A more sophisticated version would accept a **stake size** from the user and compute the blended effective price across levels:

```
If I bet $500 at ProphetX:
  $2 fills at +120
  $498 fills at +118 (assuming $500 depth there)
  Blended effective: weighted avg ≈ +118.01
```

This is more accurate than per-level filtering. But it requires:
- User enters stake size in the UI
- Scanner computes blended for each outcome
- Display shows "effective at $500 stake" rather than a discrete orderbook level

**Deferred.** Per-level filter is the simpler, correct-enough first version. Blended is a Phase 3.

---

## Phased rollout

### Phase 1 — Data pipeline (ProphetX only)
- Build `server/odds/books/prophetx/` following the coral33 template
- Probe ProphetX's API via Copy-as-cURL (user-provided HAR like coral33 was)
- Storage: extend `odds_snapshot` PK with `depth_level` column, default 0 for existing rows
- Fetcher pulls full depth per event, writes N rows per outcome

### Phase 2 — Filter + UI
- Add `exchange_min_liquidity_usd` to settings UI (localStorage + global state)
- Wire into `rows_to_games` / scanner read path
- Display "liq: $X" badge on exchange prices in the odds grid / arb table / EV table

### Phase 3 — Observability + blended pricing
- Track how often the top-of-book is filtered away vs. kept
- Optional: stake-sized blended effective-price mode (replaces per-level filter if user opts in)

### Phase 4 — Other exchanges
- Novig (US)
- Sporttrade (US)
- Matchbook / Smarkets / Betfair (UK/EU — lower priority, different market)

---

## Open questions

- Does the Odds API plan we're on expose exchange depth via any field? (Check before committing to a direct ProphetX integration.)
- Does ProphetX have a documented public API, or do we need to HAR-reverse-engineer like coral33? Effort estimate depends heavily on this.
- Do ProphetX prices on Odds API reflect the best level with any size, or the best level with some minimum size already filtered? (If the latter, the feature may be partially moot for some price ranges.)
- What's the right default `min_liquidity_usd`? Community intuition says $50–$250; calibrate after first week of use.

---

## Dependency summary

**Nothing to build today.** This spec exists to capture the idea and the data gap. Start with probing ProphetX's API from a fresh HAR when ready — same pattern as coral33.
