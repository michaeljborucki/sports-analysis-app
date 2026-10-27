# API memory leak / hang — 2026-10-23

## Symptom
App "hanging": uvicorn :8000 stopped answering after ~44h uptime. Footprint
7.0 GB on an 8 GB laptop → swap full, process in uninterruptible paging.
Next.js :3000 was fine (waiting on the API).

## Findings (measured)
1. **Working set ∝ snapshot rows.** Fresh process plateaued at ~2.8 GB with a
   533k-row snapshot. Snapshot grew 91k → 412k rows over the 44h run.
   Baseline cost 1,288 B/row retained (90k-row NBA sample), build peak ~1.8×.
2. **Kalshi/Polymarket registrations never pruned.** On Oct 23 the Kalshi
   orderbook poller still polled Oct 21 games (309k wasted requests); distinct
   tickers 2,518 → 4,286; every 60s tick overran (~1,900 "skipped" warnings).
   Polymarket: once >5,000 stale assets accumulated, new games would stop
   being subscribed (5,000-asset cap, insertion order).
3. **Residual ~4 GB over 44h unexplained by data** — leading suspects (code
   reading, not yet measured): unbounded `OddsCache.upsert_nowait` writer
   queue; Novig `ws_feed.state` not cleared in `_drop_all` (strands ~1 MB per
   reconnect).

## Changes (uncommitted, LIVE as of the 18:5x restart)
- Kalshi/Polymarket ingestors replace registrations per cycle
  (`(sport, series)` / `sport` scopes) and prune started games; Polymarket WS
  resubscribes when new assets appear (≤ once/30s). Tests:
  `server/tests/test_direct_book_pruning.py`.
- `bettingdb_source._map_raw_rows`: streams the cursor (no `fetchall`),
  interns event/team/book/market strings, shares price/point numbers.
  `normalize._parse_iso_cached`: shared datetimes. Output byte-identical
  (hash-verified on a frozen DB copy). 1,288 → 858 B/row (−33%); row-build
  peak 142 → 58 MB per 90k rows; mapping 3.7s → 1.8s.
- `GET /api/debug/memory` (`server/api/debug_memory.py`): footprint, gc,
  snapshot size, writer-queue depth, memo sizes, Kalshi/Polymarket/Novig
  registration counts. O(1) reads, safe to poll.

## Polymarket: direct feed only (same day)
Odds API's `polymarket` copy (via betting-db) filled ~13.5k slots the direct
feed lacked and was wrong: team-swapped soccer spreads, ~1pp better than the
ask, contradictory ladders (DeAndre Hunter O3.5 reb +113 shown; Polymarket
was ~-110). Added to `normalize._EXCLUDE_BOOKMAKERS` like kalshi. Cost:
no Polymarket for NFL/NCAAF (not in direct config) or NHL (configured but 0
direct rows), and only the props the direct feed carries. `polymarket_us`
unchanged.

## Open
- Direct Polymarket coverage for NFL/NCAAF/NHL + more NBA props.
- Polymarket WS resubscribe churn: 27 reconnects in ~2.5h after the
  resubscribe-on-change change — tune debounce or subscribe incrementally.
- 24h sampling of `/api/debug/memory` → confirm/deny residual leak; watch
  `cache_writer_queue` and `novig_stream.state_markets` vs `live_markets`.
- Kalshi orderbook poller still overruns 60s (≈145s for ~600 tickers) —
  throughput, not growth.
- Known timing-flaky tests under load: `test_snapshot_pages.py` freshness
  tests (module-level `NOW`), `test_latest_snapshot.py` throttle test.

## Polymarket US direct feed (2026-10-23)

- International Polymarket (polymarket.com) feed OFF by default — `POLYMARKET_FETCHER_ENABLED=true` restores it. Odds API `polymarket` / `polymarket_us` rows stay excluded (`_EXCLUDE_BOOKMAKERS`).
- `server/odds/books/polymarket_us/`: REST discovery (gateway.polymarket.us, public) every 60 s per league + full event refresh every 5 min; real-time prices via the signed market-data WebSocket (`POLYMARKET_US_KEY_ID`/`POLYMARKET_US_SECRET_KEY` in `.env`). The key can trade; the code only signs `GET /v1/ws/markets`.
- WS limit (undocumented, observed): ~10 subscribe requests × 100 slugs per connection → `PolymarketUSWSPool` shards ≤1000 markets per connection (cap `POLYMARKET_US_WS_MAX_CONNECTIONS`, default 25). ~15k markets = 16 connections.
- Prices = buy side (ask; short side = 1 − bid) + taker fee Θ·p·(1−p), Θ = market `feeCoefficient` (0.0695). Verified vs live BBO: Heat −161 / Hornets +134.
- Team matching: exact matcher, then a fuzzy fallback (same mascot + one shared token, both teams, ±90 min, unambiguous) for CFB names like "K-State" / "Miami (FL)" / "Louisiana-Monroe".
- Unmatched events left are games the Odds API (betting-db) doesn't list yet (NBA/NHL 2–3 days out) plus 2 small FCS games; they match automatically once listed.
- Status: `GET /api/polymarket-us/status`, `GET /api/debug/memory` → `polymarket_us`.
