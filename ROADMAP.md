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

- [ ] **#10 Prediction-market ↔ sportsbook cross-arb scanner.** Your single unique competitive moat — only project ingesting Kalshi + Polymarket + 12 traditional books. Competitor research identified this as "the differentiator nobody else has" (only GapSeek and ArbBets attempt it, both narrow). Ship a unified cross-venue arb mode. **~3–5 days.**
- [x] ~~**#11 Bet tracker + auto-CLV vs Pinnacle reference.**~~ **Shipped 2026-06-21.** Unified `bets` table in `cache.db` (PK: source_book + external_id). Four sync paths: Coral33 mirror (folded into existing 30-min wager-log tick), Kalshi portfolio fills (5-min APScheduler), Polymarket wallet trades (5-min, wallet from user_settings.json), CSV import (POST /api/bets/import + downloadable template at GET /api/bets/import/template). New `/bets` page with rollup tiles (30d/90d/lifetime/net), recharts CLV trend chart, breakdowns by book/sport/market, filter bar, unified bet table. /accounts Bets sub-tab now shows a redirect banner. CLV via new `lookup_clv_for_bet` (sport-agnostic; reads existing `closing_lines`). 60 new tests pass. Spec: `docs/superpowers/specs/2026-06-21-bet-tracker-multi-source-design.md`. Plan: `docs/superpowers/plans/2026-06-21-bet-tracker-multi-source.md`. Deferred follow-ups: Kalshi/Polymarket event-id resolution via event_matcher.py (rows surface without CLV until landed); Polymarket SELL-side trades (early exits).
- [ ] **#12 Push alert engine.** Reddit's #1 reason people pay for OddsJam at $199/mo. Custom threshold rules (arb > X%, EV > Y%) → web-push or Pushover. Builds on existing Kalshi/Polymarket WS streams. **~3 days.**
- [ ] **#13a Add Manifold Markets.** Half-day integration — REST + WS, no auth, free. Fills long-tail / futures / political coverage no other source has. **~half day.**
- [ ] **#13b Add PrizePicks + Underdog Fantasy.** Opens a large player-prop EV pocket vs traditional sportsbook props. Scrape-based (curl_cffi); medium maintenance. **~1–2 days each.**

## Tier 3 — odds-matching audit findings (not in original synthesis)

Source: parallel odds-matching audit run on 2026-06-21.

- [ ] **M3** Date-only time-window matching. Kalshi + Polymarket anchor to "noon ET" + 12h window. Playoff back-to-backs between same teams can theoretically cross-pair. ~0.5–2% rare miss. Fix: tighten anchors during high-cadence periods. **Low.**
- [ ] **M4** Alt-market orientation mismatch. Same game, different `outcome_name` when book A emits "Home -2.5" and book B emits "Away +2.5". ~5–10% of alt-spread rows split. Fix: canonicalize spread orientation in normalizer (always store the favored team's view). **Medium.**
- [ ] **M5** Kalshi event-ticker `_split_team_pair` ambiguity. No defensive check that all team codes are non-overlapping prefixes. Adding a future MLB team or rebrand could silently break event resolution. Fix: validate the code map at load time. **Low.**
- [ ] **M6** Polymarket soccer 3-way drops the entire event if any leg is missing. ~2–5% of early-tournament Polymarket soccer events. Fix: emit partial markets and let the cache merge 2-of-3. **Medium.**
- [ ] **M7** Outcome-name collision logging. Add a WARNING when two books emit different `outcome_name` strings for the same (event, market_key, outcome_point). Catches silent splits before they become unrecoverable. **Low.**
- [ ] **M8** Coral33 in-play purge bluntness. `purge_live_rows_for_book("coral33", now)` deletes any commence_time ≤ now — but a delayed/rescheduled game might still be "future." Fix: gate on actual game-status, not just clock. **Low.**

## Tier 4 — backend audit findings (not in original synthesis)

- [ ] **A5** `_resolved_keys` / `_event_sport_map` never TTL. Cached for process lifetime; stale during tournament rotations. Fix: re-resolve every 24h. **Medium.**
- [ ] **A6** `rows_to_games` does O(prices²) per outcome for best-price search. Small win on 100+ event slates. Fix: pre-build a price lookup dict. **Low.**
- [ ] **A8** `distinct_events` could push the `commence_time` time filter into SQL instead of Python. **Low.**

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
