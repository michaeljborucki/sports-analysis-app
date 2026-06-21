# Roadmap

Open work from the 2026-06-21 audit pass (backend perf + odds-matching + competitive research + storage/realtime + data sources). Items grouped by impact tier and effort. Tick off as completed.

> **Already shipped in this audit pass:**
> - `c19e810` — 3 SQL indexes, refresh_event indexed lookup, dashboard single-scan, soccer team aliases (WC + EU clubs), WC sport_key
> - `ed61f0d` — cache-version memo key on EV / arb / low-hold scanners (~5× speedup on memo hits)
> - `f2e6d83` — player-prop name canonicalization across all 4 books
> - `1e51a30` — **#9** request coalescing on all 5 scanner endpoints (5 concurrent requests = 1 underlying scan)
> - `6bb2f9c` — **#8** SSE push to the frontend (UI re-renders sub-second on Kalshi/Polymarket WS price changes; replaces 5–15s SWR polling)

---

## Tier 1 — medium-effort, high-leverage (a few days each)

- [x] ~~**#8 SSE push to the frontend instead of SWR polling.**~~ **Shipped in `6bb2f9c`.** Dumb-tick payload + 100ms debounce + 15s heartbeat. One `useLiveUpdates` hook in `SwrProvider` calls `mutate(() => true)` on every backend tick — every SWR-backed page gets push-driven freshness with zero per-page wiring. Verified live: 2 subscribers active on Edges page, ticks fire on every cache upsert.
- [x] ~~**#9 Request coalescing on EV / arb endpoints.**~~ **Shipped in `1e51a30`.** Custom 30-LOC helper (`server/odds/coalesce.py`) wraps memo + in-flight registry. Wired into all 5 scanner endpoints (arb, EV, low-hold, free-bets, profit-boost). 12 new tests including a concurrent integration test that proves 3 simultaneous HTTP requests trigger exactly 1 scan.

## Tier 2 — strategic, biggest differentiation

- [x] ~~**#10 Prediction-market ↔ sportsbook cross-arb scanner.**~~ **Shipped 2026-06-21.** Audit found the engine, fee netout (Kalshi 7%, Polymarket 5%, both baked into `price_american` at normalization), and venue→event matching were already done by earlier infra — cross-venue arbs were already surfacing on `/api/arbitrage` (verified with 2 of 17 live arbs cross-venue). Remaining gap was orderbook depth: shipped `max_stake_dollars` column on `odds_snapshot` (COALESCE in DO UPDATE SET so a NULL write preserves prior non-null values); Polymarket size flows from existing WS `book` messages (previously discarded); Kalshi gets a new 60s `/markets/{ticker}/orderbook` poller wired into `clv_scheduler` with a fixture-pinned bid-inversion helper that tolerates both integer-cents and decimal-dollar-string formats. Arb scanner emits per-leg `max_stake_dollars` + opportunity-level `max_total_stake_dollars` (the largest total stake respecting every leg's depth; NULL when any leg is unknown). UI shows a small `max $X` chip next to each cross-venue leg's price on `/edges`. Spec: `docs/superpowers/specs/2026-06-21-arb-depth-capture-design.md`. Plan: `docs/superpowers/plans/2026-06-21-arb-depth-capture.md`. Deferred follow-ups: bid-side depth (only ask-side matters for taker), Polymarket size-staleness mitigation between `book` events, depth-aware EV / low-hold scanners, "cross-venue only" UI filter chip.
- [ ] ~~**#12 Push alert engine.**~~ **Skipped per user request.**
- [ ] ~~**#13a Add Manifold Markets.**~~ **Skipped per user request 2026-06-21.** Manifold's two products (play-money Mana, real-money Sweeps) don't slot cleanly into the existing real-money arb scanner.
- [ ] ~~**#13b Add PrizePicks + Underdog Fantasy.**~~ **Skipped per user request 2026-06-21.**
- [x] ~~**#11 Bet tracker + auto-CLV vs Pinnacle reference.**~~ **Shipped 2026-06-21.** Unified `bets` table in `cache.db` (PK: source_book + external_id). Four sync paths: Coral33 mirror (folded into existing 30-min wager-log tick), Kalshi portfolio fills (5-min APScheduler), Polymarket wallet trades (5-min, wallet from user_settings.json), CSV import (POST /api/bets/import + downloadable template at GET /api/bets/import/template). New `/bets` page with rollup tiles (30d/90d/lifetime/net), recharts CLV trend chart, breakdowns by book/sport/market, filter bar, unified bet table. /accounts Bets sub-tab now shows a redirect banner. CLV via new `lookup_clv_for_bet` (sport-agnostic; reads existing `closing_lines`). 60 new tests pass. Spec: `docs/superpowers/specs/2026-06-21-bet-tracker-multi-source-design.md`. Plan: `docs/superpowers/plans/2026-06-21-bet-tracker-multi-source.md`. Deferred follow-ups: Kalshi/Polymarket event-id resolution via event_matcher.py (rows surface without CLV until landed); Polymarket SELL-side trades (early exits).
## Tier 3 — odds-matching audit findings (not in original synthesis)

Source: parallel odds-matching audit run on 2026-06-21.

- [x] ~~**M3** Date-only time-window matching.~~ **Shipped 2026-06-21.** New `match_multi_anchor` on both Polymarket and Kalshi matchers; per-sport anchor table at `server/odds/books/_anchor_table.py` ({noon, 7pm, 10pm ET} default; NBA/NHL/WNBA evening-only). Both fetchers wrap `matcher.match` in a smart wrapper that prefers the multi-anchor ±3h scan for date-only inputs and falls back to the original ±12h wide-window match when no anchor hits.
- [ ] ~~**M4** Alt-market orientation mismatch.~~ **Helper shipped, wiring deferred.** `canonicalize_spread_outcome` + `is_spread_market` in `server/odds/books/spread_orientation.py` with unit tests. Wiring it at row-ingest collapses both sides of a sportsbook spread market to the same cache key (price-loss). The actual M4 bug is already handled by `pairing.collect_spread_pairs` at the scanner layer (joins by complementary signed points across books), so wiring isn't needed for current consumers. Helper kept for future read-side canonicalization.
- [x] ~~**M5** Kalshi event-ticker `_split_team_pair` ambiguity.~~ **Shipped 2026-06-21.** `validate_code_map_unique_prefixes` raises if any code is a prefix of another; called at module load per-sport on `TEAM_CODE_TO_CANONICAL`. Future team rebrands now fail loud at boot.
- [x] ~~**M6** Polymarket soccer 3-way drops the entire event if any leg is missing.~~ **Shipped 2026-06-21.** `_normalize_soccer_3way_event` now emits whichever outcomes ARE present (typically 2-of-3 when draw isn't listed). The 3-way overround sanity check only fires on 3-of-3; partials are gated downstream by cross-book devig. Captures ~2-5% of early-tournament events previously dropped silently.
- [x] ~~**M7** Outcome-name collision logging.~~ **Shipped 2026-06-21.** `normalize.py:_check_outcome_name_collisions` walks `rows_to_games` input, groups by (event_id, market_key, outcome_point), and emits a WARN once per address per process when two books label the same address differently. Pure observability.
- [x] ~~**M8** Coral33 in-play purge bluntness.~~ **Shipped 2026-06-21.** `OddsCache.purge_live_rows_for_book` takes an optional `grace_seconds`; Coral33 fetcher passes 1800 (30 min). Catches the common rain-delay / soft-start case without polling Coral33 for live game status (audit's preferred fix, deferred).

## Tier 4 — backend audit findings (not in original synthesis)

- [x] ~~**A5** `_resolved_keys` / `_event_sport_map` never TTL.~~ **Shipped 2026-06-21.** 24h TTL on `_resolved_keys` with refresh-failure preservation (transient errors don't blank out previously-good cached keys; timestamp stays put so next caller retries). First-time failure still falls back to static keys to avoid retry-storms. Logs key-set changes on refresh. `_event_sport_map` was lumped in by the audit but it's a memory-growth concern (never goes stale), deferred separately.
- [x] ~~**A6** `rows_to_games` does O(prices²) per outcome for best-price search.~~ **Shipped 2026-06-21.** New `best_price_dict` helper in `best_odds.py`; `rows_to_games` does one `max()` over the dicts directly, eliminating the redundant linear scan to recover the original dict from a tuple match.
- [x] ~~**A8** `distinct_events` could push the `commence_time` time filter into SQL instead of Python.~~ **Shipped 2026-06-21.** SQL pushdown via `HAVING MAX(commence_time) BETWEEN ? AND ?` — preserves per-event MAX semantics (rows for one event can disagree on commence_time; HAVING filters on the aggregate, matching the previous Python-filter behavior bit-for-bit). Adds a `now` kwarg for testability.

## Tier 5 — storage / realtime architecture

- [ ] **DuckDB for CLV / line-history queries.** Embedded, columnar, single-process. Right call when building **#11** (bet tracker + CLV). Don't introduce until then. **~1 day to wire up.**
- [ ] **In-process tick-dedup + 250–500ms write batching on WS ingest.** Kills the bulk of duplicate Kalshi/Polymarket WS messages before they hit SQLite. Reduces write churn and improves perceived freshness. **~1 day.**

## Tier 6 — data sources to add

Pricing sources (ranked by unique-value / integration-cost):

- [ ] **Betfair Exchange API.** £499 one-off Live App Key (free Delayed for dev). World-class sharp lines for soccer / tennis / horse racing. **High priority once cross-arb scanner (#10) ships.**
- [ ] **Smarkets API.** Free with application; UK exchange #2, complementary to Betfair on UK markets.
- [ ] **Limitless Exchange.** Second crypto-native prediction venue, similar shape to Polymarket integration. Public REST + WS.
- [ ] **Sporttrade / Novig / ProphetX.** No public APIs today (June 2026) but all recently CFTC-licensed. Watch list — revisit in 6–12 months.

Enrichment-only sources (sharpen the `agents/` models, not new books):

- [ ] **pybaseball / Statcast.** Free; per-pitch exit velo, spin, launch angle, expected stats. Best free MLB feature source. **Day-1 add for MLB.**
- [ ] **`swar/nba_api` (stats.nba.com).** Free; play-by-play, shot charts, lineup splits, hustle stats. NBA-only.
- [ ] **ESPN undocumented APIs (`pseudo-r/Public-ESPN-API`).** Free; injuries, depth charts, schedules across NFL/NBA/MLB/NHL.
- [ ] **Open-Meteo weather.** Free, no key. Critical for NFL totals / passing-yards props and MLB HR props.
- [ ] **BALLDONTLIE.** Free tier across NBA/NFL/MLB/NHL — fallback when stats.nba.com is IP-blocked.

## Tier 7 — competitive landscape features

From competitor research; ranked by how loud users complain about the gap.

- [ ] **Bonus-bet / promo converter with auto-find best hedge.** DarkHorse and OddsJam own this. Pure calculator on data you already have. **Medium.**
- [ ] **Sharp-book line-history charts** (steam moves, RLM, when DK lags Pinnacle by Xms). You already store ticks — just chart them. **Medium.**
- [ ] **Limit-risk score per market.** Loudest unmet complaint on Reddit: "I get limited in 3 days." Score markets by limit risk (round numbers, mainline games, avoid obscure props). Unique product. Ties into **#11** (bet tracker). **Medium.**
- [ ] **Same-game-parlay correlation-aware builder.** Large effort — correlation matrices per prop pair. **Large.**
- [ ] **Screenshot / OCR bet import.** For the bet tracker (#11). GPT-4o / Claude vision API. **Medium.**

## Skip list — bad effort-vs-value for this stage

- ~~DragonflyDB / Redis / ClickHouse / KeyDB~~ — overkill for single-user single-machine
- ~~WebSockets to the browser~~ — SSE is the right fit
- ~~Pinnacle direct API~~ — closed to public July 2025; rely on the-odds-api's Pinnacle relay
- ~~Bet365 / BetMGM direct scraping~~ — Cloudflare arms race; the-odds-api already covers them
- ~~Augur / Drift Predict / Stake.com~~ — negligible sports liquidity or US legality issues
- ~~Kafka / NATS / horizontal scaling primitives~~ — explicitly out of scope
