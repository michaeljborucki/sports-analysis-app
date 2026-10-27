# Backend performance with the larger data volume (2026-10-24)

Trigger: CFB odds page took ~18s to show (user: "not seeing any college football").
Data volume after Polymarket US: snapshot 441k rows / 458 games, API footprint 1.7 GB.

## Measurements (live API, ~20 min uptime)

| What | Number |
|---|---|
| `/api/odds/ncaaf` payload | 19.4 MB, 108k prices (17.6 MB before Polymarket US) |
| of which alternates (alt spreads / alt totals / alt team totals) | 6.6 + 6.1 + 3.0 = 15.7 MB (81%) |
| `/api/odds/{sport}` time to first byte | ncaaf 4.3s, nfl 4.9s, nba 6.4s, nhl 0.5s |
| odds:ncaaf compute (threadpool) | avg 3.0s, max 9.8s, 33 runs |
| event-loop stalls (>300ms) | 660 stalls, 304s total (~25% of uptime), max 3.2s |
| gen2 garbage collections | 1,159, 330s total, avg 285ms, max 2.9s, 0 objects collected |
| response compression | none (no GZip middleware) |

Loop-stall attribution (where the loop thread was when stalled):

| Site | Time | Count |
|---|---|---|
| `novig/fetcher.py:400` `_poll_loop` idle-list scan | 75s (+3s +2.6s :403) | 170 |
| `websockets permessage_deflate.decode` (WS decompression) | 67s (+4.4s) | 164 |
| `ssl.read` | 37s | 67 |
| pydantic `dump_python` + `json iterencode` (FastAPI response serialization on loop) | 15s | 26 |
| novig `client._get` | 18s | 35 |
| `latest_snapshot._build` (gc.freeze) | 3.4s | 6 |

## Root causes

1. **`/api/odds` and `/api/props` bypass serialize-once.** Every request validates ~100k
   prices into pydantic models in a thread, then FastAPI re-validates + re-serializes the
   18 MB model ON THE EVENT LOOP. No memo, so every SSE tick repeats it. The scanner
   endpoints (ev/arb/low-hold) already use `model_json_bytes` + memo; these two don't.
2. **Odds list ships every alternate line.** 81% of the CFB payload is alternates that only
   the expanded-game view (`alt-lines-matrix`) uses.
3. **Novig poller is O(targets) per poll on the loop.** 13,978 targets (13,801 overdue), 8
   workers, ~8 polls/s; each poll rebuilds `idle`, `due` and a `min()` over all targets.
4. **Allocation churn → gen2 GC every ~1s.** Per-request pydantic trees (100k+ objects) and
   WS row dicts push gen2 over threshold constantly; each pass scans 0.5-0.8M live objects
   and frees nothing. Default thresholds (700/10/10).
5. **WebSocket decompression on the loop.** 16 Polymarket US connections (15k markets,
   ~200 msg/s) + Kalshi + Novig, all permessage-deflate.
6. **SSE ticks every ~1s** (any WS write) while the snapshot only changes every 5s, so most
   tick-driven refetches return identical data.

## Already shipped (web, LIVE)

- Per-key SSE revalidation throttle (`web/lib/use-live-updates.ts`): one request in flight
  per key, >=3s between starts, ticks coalesce into one trailing refresh. CFB went from 12
  overlapping 18 MB refetches in 20s to 4 in 38s.

## Proposed fixes (pick by number)

1. **Serialize-once + memo for `/api/odds` and `/api/props`** — render JSON bytes in the
   threadpool once per (sport, snapshot generation) via `snapshot_memo`; return
   `json_bytes_response`. Removes the on-loop serialization and repeat work on ticks.
   Output byte-identical. Expected: repeat requests ~0ms, first request ~1/2.
2. **Split alternates out of the odds list** — list returns main markets only; new
   `/api/odds/{sport}/{event_id}` returns one game's full markets, fetched when a row is
   expanded. CFB 19.4 MB → ~3.7 MB. Web change in `app/odds/[sport]` + `alt-lines-matrix`.
   (Odds page "best price" columns unaffected; expanded view loads ~100-300 ms on click.)
3. **GZip responses** (`GZipMiddleware`, minimum_size ~1 KB). JSON compresses ~8-10x;
   cheap on localhost but cuts browser parse/transfer. Low risk.
4. **Novig poller: heap/queue instead of full scans** — one scheduler orders due targets
   once per second; workers pop. O(log n) per poll instead of 3x O(14k). Same poll order
   (soonest game first), same rate limit.
5. **GC tuning** — `gc.set_threshold(50_000, 20, 100)` (or similar) at startup + keep the
   existing gc.freeze. Cuts gen2 frequency ~10x. Memory effect watched via
   `/api/debug/memory`.
6. **Disable WS compression for Polymarket US** (`compression=None`) — removes zlib work on
   the loop; more bytes on the wire (local bandwidth is not the constraint). Optionally Kalshi.
7. **Server-side SSE tick cadence = snapshot cadence** — publish at most one odds tick per
   snapshot generation (5s) instead of per cache write (1s).
8. **Skip the duplicate initial fetch** — the SSE `connected` event fires a full revalidate
   right after the page's own first fetch; only revalidate-all on REconnect.

Not changing: what any scanner computes, which books/markets are fetched, Odds API spend,
fair-value math. Items 1, 3, 4, 5, 6, 7, 8 are behavior-neutral; item 2 changes how the
expanded view gets its data.

## Lower priority / noted

- Kalshi orderbook poller: 1,191 tickers polled per 576s cycle, `rows_updated: 0`
  (~2 req/s of REST that changes nothing — likely duplicated by the WS). Worth a look.
- Novig WS: `ws_markets_live: 0`, last message 261s old while REST polls 14k targets.
- Snapshot itself: 441k rows, 1.7 GB footprint. Fine for now; items 1+2 reduce peak.

## Results — items 1, 3, 4, 5, 6 shipped (2026-10-24, LIVE)

Also shipped: Polymarket US skips event discovery (`distinct_events`) on cycles where no
game needs a full fetch.

| Metric | Before (20 min) | After (10.5 min) |
|---|---|---|
| Event-loop stall time | 304s = 25% of uptime (660 stalls) | 111s = 17.5% (259) |
| Automatic gen2 GC passes | 1,159 (330s) | 0 — only the snapshot's own once-a-minute pass (8, 12s) |
| `/api/odds` repeat request | 4-6s every time | 10-60ms (memo hit) |
| `/api/odds` first request per data version | 4-6s | 1-10s (unchanged compute; contended) |
| CFB odds on the wire | 19.4 MB | 0.66-0.98 MB (gzip) |
| CFB odds page in browser | 10-15s per request, ~12 overlapping | 0.65-0.93s |
| Novig poller in stall list | #1 (75s) | gone |
| Snapshot full rebuild | avg 48s, max 195s | avg 33s, max 74s |

## Remaining top issue: snapshot full rebuild

A full rebuild (~440k rows -> games) runs every 60s and takes 33-48s of CPU in a worker
thread, so the GIL is contended most of the time and the loop stalls behind it; its
once-a-minute `gc.unfreeze(); gc.collect(); gc.freeze()` adds 0.3-6s on the main thread.

Options (not started):
- A. Rebuild less often (e.g. every 3-5 min); the 5s overlay already carries direct-book
  changes in between. Smallest change; need to confirm betting-db changes reach the
  overlay or accept up to N min for Odds API books (currently ~1 min).
- B. Incremental rebuild: re-map only events whose betting-db rows changed.
- C. Build the snapshot in a separate process (no GIL contention); ship results back
  (pickle cost) or have the API read a shared pre-built artifact.

## Results — option C shipped: snapshot built in a subprocess (2026-10-24, LIVE)

`server/odds/snapshot_worker.py`: in betting_db mode the full rebuild runs in a fresh spawned
process (`ProcessPoolExecutor(1, spawn, max_tasks_per_child=1)`). The child returns many small
pickles: 2,000-row slices, one per game, signature chunks. The parent unpickles them one by one
in a worker thread, so the event loop runs between chunks, and order lists keep rows and games in
exactly the in-process order (tested for equivalence, including chunk boundaries). If the child
fails or exceeds 240s (`SNAPSHOT_SUBPROCESS_TIMEOUT_S`), the build falls back to the in-process
path. Kill switch: `SNAPSHOT_BUILD_SUBPROCESS=false`. `/api/debug/memory` → `snapshot.last_build`
shows mode and timings.

| Metric | After 1/3/4/5/6 (10.5 min) | After C (10.5 min) |
|---|---|---|
| Event-loop stall time | 111s = 17.5% (259 stalls) | 34s = 5.3% (79 stalls, max 2.9s) |
| Snapshot build CPU in the API process | avg 33s every 60s | parent assemble 0.5-2.1s; build itself in child |
| Snapshot build wall time | avg 33s, max 74s | avg 18.5s, max 39s |
| gen2 GC (snapshot's once-a-minute pass) | 8 passes, 12s | 9 passes, 4.4s |
| `/api/odds` first request per version | 1-10s | ncaaf 1.0s, nfl 0.6s, nba 0.4s |
| API footprint | ~1.75 GB | 1.75 GB (+ child peak RSS 425 MB, during builds only) |
| Fallbacks / tracebacks | — | 0 / 0 |

Remaining stall sites: mostly the Novig REST poller (`_poll_loop` / `_poll_one` / `get_book`) and
the Kalshi orderbook poller (`rows_updated: 0`, see "Lower priority").

## Investigation — Kalshi orderbook poller + Novig poller (2026-10-24)

Stall attribution by the innermost frame (29 min uptime, 372 stalls, 144s = 8.3%). The
earlier "pollers are the top site" reading came from grepping only `server/` frames:

| Leaf | Time | Comes from |
|---|---|---|
| `permessage_deflate.decode` | 33s | Kalshi WS (the only compressed stream left) |
| `ssl.read` | 19s | socket reads, mostly the same Kalshi stream |
| `importlib _path_stat` | 16s | httpcore's per-request `import sniffio` — not installed, so every request re-scans sys.path (13s under Novig `get_book`, 2s Kalshi orderbook, 1.4s PMUS) |
| snapshot gc / overlay | ~15s | snapshot's own once-a-minute pass |

### Kalshi
- **Orderbook poller is fully broken.** Kalshi changed the response to
  `{"orderbook_fp": {"yes_dollars": [...], "no_dollars": [...]}}`; the parser reads
  `orderbook.yes/no`, gets nothing, writes nothing. 1,241 signed REST calls per ~150s cycle,
  `rows_updated: 0`, and **0 of 3,283 Kalshi rows have `max_stake_dollars`**, so the
  minimum-liquidity filter never applies to Kalshi (rows with no depth always pass).
- **WS subscribes to the entire platform.** `{"channels": ["ticker"]}` with no
  `market_tickers` → measured 38,110 msgs in 20s (~1,900/s, ~1 MB/s decompressed, 1,147
  series), each deflated + `json.loads`ed on the event loop, then dropped unless it's one
  of our 1,665 tickers.
- **The ticker message already carries depth for both sides:** `yes_ask_dollars` +
  `yes_ask_size_fp` (buy YES) and `yes_bid_dollars` + `yes_bid_size_fp` (buy NO at
  1 − yes_bid). Today the ingestor updates only YES prices from WS; NO prices wait for the
  60s REST cycle.

### Novig
- Poller code is no longer a stall site (queue fix held). Its HTTP cost is the sniffio scan.
- Coverage: 10,986 targets, 10,301 overdue (94%) at the signed 8 req/s limit — a full pass
  takes ~23 min vs the 60-480s schedule, so far-out rows show the betting-db copy. WS holds
  36 events but only 104 live markets (cap 2,000). Not yet understood why so few.

### Proposed (pick by letter)
- **K1** Kalshi WS: subscribe to our tickers only (`market_tickers`, then
  `update_subscription` add/delete as tickers register/prune) + `compression=None`.
- **K2** Kalshi depth + NO price from the WS ticker message (YES and NO rows get
  `max_stake_dollars`; NO prices become real-time).
- **K3** Retire the REST orderbook poller (or fix its parser and keep it only for tickers
  with no WS update in the window).
- **N1** Install `sniffio` (tiny pure-Python dep of the httpx stack; add to pyproject).
- **N2** Investigate Novig coverage (why 104 live of 36 events; second WS connection if the
  2,048 limit is per connection; or trim far-out alternate targets). Investigation only.

## Fixes shipped — K1, K2, K3, N1, N2 + Coral33 time zone (2026-10-24, LIVE)

- **N1** `sniffio` installed and added to `pyproject.toml`.
- **K1** Kalshi WS subscribes to our tickers only (`market_tickers`, then `update_subscription`
  add/delete every 5s, ≤500 per command) with `compression=None`. ~1,900 msg/s → ~76 msg/s.
- **K2** Kalshi depth + NO price from quotes (`kalshi/quote_depth.py`): YES = yes_ask ×
  yes_ask_size, NO = (1 − yes_bid) × yes_bid_size, from both REST `/markets` (normalizer) and
  WS ticks (ingestor). Kalshi rows with depth: 0 of 3,283 → 2,945 of 2,945. NO prices now
  update live (verified `no_ask == 1 − yes_bid` on live markets).
- **K3** REST orderbook poller removed (module, scheduler job, `get_orderbook`, tests).
- **N2** Novig stream: `/v3/limits` now says maxWatchedMarkets 8192, stream 512 / 32 per s
  (was 2048 / 4). Rate-limit errors arrive with `nonce=None`, so failed events were never
  retried. Now: cap 8,000; subscribes batched ~256 markets and paced by market count / 32 per s;
  unanswered requests retried after 30s; `compression=None`. Live markets 104 → 4,791 within
  5 min; overdue REST targets 94% → 67% and falling. REST rate left at 8/s (16/s allowed, but
  unverified whether that budget is per key or per account).
- **Coral33** line times switched from Denver to Eastern around 2026-10-24 02:00Z, putting
  every game 2h off: NBA/NFL/NHL/MLB/NCAAF all orphaned (soccer/UFC/tennis survived on wide
  windows). The fetcher now votes the zone each cycle from strict-window sports' line times vs
  cache start times (`observe_coral_timezone`). After: NBA 508, NFL 152, NHL 76, MLB 52,
  NCAAF 48 rows; 14 low-holds with a Coral33 leg. Not changed: `wager_log.py` (bet-history
  timestamps) still assumes Denver.
