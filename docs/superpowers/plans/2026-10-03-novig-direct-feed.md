# Novig direct feed — take + make prices (plan)

Status: **Stages 1 + 2 SHIPPED + LIVE 2026-10-03** (uncommitted). Stage 3 (websocket) and 4 (placement) not started.
Written 2026-10-03 from the Novig v3 OpenAPI spec
(`https://docs.novig.com/llms.txt`) and live probes of `api.novig.com`.

## Why

Today `novig` reaches us only through The Odds API → betting-db: one `price_american`
per outcome, which is the **take** price (verified: Burrow Over 268.5 shows −135 in
betting-db = 1 − 0.425 resting Under bid on Novig's own book). We get no maker side,
no size, and a side with no opposing bid is simply missing.

## What the Novig API gives us (verified against the spec)

| Need | Endpoint | Auth |
|---|---|---|
| Events | `GET /v3/public/catalog/events` (league/status/startsAfter filters, limit ≤ 5000) | none (per-IP edge throttle) |
| Markets + outcomes + fee | `GET /v3/public/catalog/markets` (league/marketType/event filters) | none |
| Order book | `GET /v3/public/catalog/markets/{id}/book` (ETag → 304) | none |
| Live book deltas | `wss://api.novig.com/v3/ws`, subject `market:<id>`/`event:<id>`, channel `book` | `trading::read` key |
| Throttle schedule | `GET /v3/limits` | any key |

Book semantics (same shape as Kalshi — reuse `kalshi/orderbook_depth.py` logic):
- `orders[outcomeId]` = resting **buy** orders on that outcome, best first. `price` is a
  probability string on a grid (0.001 steps at the tails, 0.005 in 0.055–0.945); `qty`
  contracts pay 1¢ each (80,000 qty = $800 payout).
- **Take** outcome A = `1 − best bid on B` (two-outcome markets), size = that bid's qty.
- **Make** outcome A = best bid on A (join it) or one tick better (improve it).

Fees: taker `c·P·(1−P)` per contract; game markets `c=0.03`, charged **only in-game**
(`WHEN_LIVE`); futures `c=0.06` always. Makers never pay and earn `makerCredit` (0.5 game,
0.7 futures) of the taker fee. Fee is per market in the `fee` field — read it, don't hardcode.

Gotchas from the spec:
- Event moving to `OPEN_INGAME` **voids every resting order** on its markets.
- `voids: FMV` markets settle at fair value on a void, not a refund.
- Public REST 429'd after ~20 rapid book calls from one IP → per-market REST polling
  can't cover the slate; the websocket is the real feed.
- Keys require KYC; a `trading::read` key comes from opening a subaccount with a
  management key. Placement additionally needs device geolocation within 3 days (451).

## Stages

**Stage 1 — read-only REST fetcher (no key needed).** LIVE when shipped, read-only.
- `server/odds/books/novig/` mirroring `books/kalshi/`: `client.py` (public REST,
  ETag + Retry-After aware), `mapping.py` (marketType → our market keys:
  MONEY→h2h, SPREAD→spreads, TOTAL→totals, TEAM_TOTAL→team_totals, player types →
  player_* props), `event_matcher.py` (reuse `_anchor_table` / Kalshi matcher pattern),
  `normalizer.py`, `fetcher.py`.
- Scope to scheduled pregame events in enabled sports; poll books for mainline
  markets first, paced under the edge throttle.
- Emit take price as `bookmaker_key="novig"` rows; add `novig` to
  `normalize._EXCLUDE_BOOKMAKERS` and `bettingdb_source.DIRECT_BOOK_KEYS` so the direct
  rows replace the Odds API copy (same pattern as kalshi).
- Commission: leave `commissions.py` novig at 0.0 for pregame; in-game taker fee
  handled per row from the market's `fee` block.

**Stage 2 — maker price + size in the model.**
- New optional fields on price rows: `max_stake_dollars` (take size, already used for
  Kalshi arb depth) and `maker_price_american` + `maker_size_dollars`.
- Surface in no-vig / EV / low-hold as a secondary "make @ X" column; take price stays
  the headline number. Regenerate `web/openapi.json` + `types/api.ts`.

**Stage 3 — websocket book stream (needs a `trading::read` key — user action).**
- `ws_client.py` / `ws_ingest.py` like Kalshi: snapshot via REST `book` (seq), then
  apply `book` deltas in seq order; resubscribe on gap. Budget: `maxWatchedMarkets`
  2048, stream bucket 512 cap / 4 per sec.
- Key material in gitignored `.env` (`NOVIG_KEY_ID`, `NOVIG_PRIVATE_KEY_PATH`); never
  commit the `.pem`.

**Stage 4 — placement (not proposed now).** `POST /v3/orders` with `tif: "PO"`
(post-only = guaranteed maker) or `IOC`/`FOK` for taking. Would ship inert behind a
`NOVIG_PLACEMENT_LIVE` flag that only the user flips, same as Coral33.

## User decisions needed

1. Build Stage 1 now? (free, no account needed)
2. Create a Novig API key (KYC on novig.com → management key → `trading::read`
   subaccount key) to unlock Stage 3?
3. Stage 2 UI: secondary "make" column vs. tooltip only?

## Blast radius (Stage 1)

Changes: Novig rows switch source from Odds API to the direct feed. Unchanged: every
other book, cache_mode, Odds API spend (Novig rows come with the same betting-db poll
either way — removing them does not reduce credits), Coral33/Kalshi/Polymarket paths.

## Stage 1 — as built (2026-10-03)

Files: `server/odds/books/novig/{__init__,mapping,normalizer,client,fetcher}.py`,
`server/api/novig_ctl.py` (`GET /api/novig/status`, `POST /api/novig/refresh`),
wiring in `server/main.py` + `server/api/cache_mode.py`, `novig` added to
`bettingdb_source.DIRECT_BOOK_KEYS` (+ `bettingdb_source.book_rows`), tests in
`server/tests/test_novig_normalizer.py` (12).

Design changes vs. the proposal above (learned while building):
- **Override-only, never invent slots.** A Novig market is polled only if betting-db
  already holds a Novig row for the same event/line/player ("sibling"); the direct
  row copies that row's `market_key`, so main-vs-alt is never guessed and nothing
  duplicates. Consequence: Novig tennis is not covered (the Odds API carries no
  Novig tennis rows to override).
- `novig` was NOT added to `normalize._EXCLUDE_BOOKMAKERS`: the direct poller only
  reaches a rate-limited subset, so betting-db's copy fills every slot it misses.
- Budget: public REST ≈ 1.5 req/s per IP (uncached book GET ≈ 2.7s → 8 concurrent
  workers). Catalog refresh every 300s, 12h horizon, enabled sports only. Due
  markets are served soonest-game-first; cadence 60s (<1h) / 120s (<3h) / 240s
  (<6h) / 480s. On a full Saturday slate there are ~4.3k targets, so far-out games
  stay on the betting-db copy.
- Live games: Novig voids resting orders at kickoff; we stop polling at start and
  `purge_live_rows_for_book("novig")` each catalog cycle (betting_db mode only).
- Team/fighter aliases are shared with coral33.toml.

Verified live: 206/206 direct rows served in place of the betting-db copy; on a
75-side sample 65 matched betting-db's price exactly and the rest were newer
moves; event-loop lag with the fetcher on vs off was equivalent (90-ping p50
7ms vs 16ms, >2s stalls 2 vs 3 — pre-existing). Kill switch:
`NOVIG_FETCHER_ENABLED=false`. Tunables: `NOVIG_PUBLIC_RPS`, `NOVIG_POLL_WORKERS`,
`NOVIG_HORIZON_HOURS`, `NOVIG_CATALOG_SECONDS`.

## Stage 2 — as built (2026-10-03): maker prices on the Edges page

User flow: post the next incremented maker price. Decisions (user-approved):
the toggle also SURFACES maker-only edges; on a one-tick spread the maker
price JOINS the best bid.

- Maker quote = best bid on the outcome + one grid tick (0.001 / 0.005 / 0.001
  bands); joins the bid if that would reach the take price; none when nobody
  bids the outcome. Written as virtual book `novig_maker` (no fee, no depth cap);
  deleted the moment the bid disappears.
- `server/odds/venues.py`: `novig_maker` is OPT-IN — scanners consider it only
  when the request's `books` names it, so odds/props grids, CLV, consensus/fair
  prices, dashboards and free-bet/profit-boost hedges are unchanged. Two-leg
  scanners require distinct VENUES (novig_maker ≡ novig), looking up to 4 deep
  past a same-venue best price.
- Each Novig take leg carries its maker price and each maker leg its take price
  (`counterpart_price_american` on ArbSide / LowHoldSide / EVOpportunity).
- Edges page: "with Novig at take prices | take + maker prices" clause (URL
  `novig=maker`), arb / low-hold / EV modes only. Rows needing a fill get a
  **Maker** chip; legs show "make X" / "take X".
- Limit: only markets the Stage 1 poller reaches (sibling-matched, soonest-first)
  have maker quotes.
