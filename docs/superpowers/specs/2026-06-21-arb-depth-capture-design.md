# Cross-Venue Arb Depth Capture (Roadmap #10 — remaining gap)

**Date:** 2026-06-21
**Status:** Design — pending reviewer pass
**Roadmap item:** Tier 2 #10 (Prediction-market ↔ sportsbook cross-arb scanner — remaining work)

## Context

The audit run while picking up Tier 2 #10 found that most of the heavy lifting is already done:

- **Cross-venue arb engine works.** `/api/arbitrage?books=kalshi,polymarket,draftkings,...` already pairs prediction-market legs with sportsbook legs. Live run shows 2 of 17 current arbs are cross-venue (WNBA Atlanta @ Kalshi/Fanatics; Liberty/Aces @ Polymarket/DK).
- **Fees are netted.** Kalshi 7% taker fee (`kalshi/normalizer.py:KALSHI_TAKER_FEE = 0.07`) and Polymarket 5% taker fee (`polymarket/normalizer.py:POLYMARKET_TAKER_FEE = 0.05`) are baked into the American odds at normalization time. Both verified empirically against real fills. The scanner's ROI numbers are post-fee.
- **Matching works.** `kalshi/event_matcher.py` and `polymarket/event_matcher.py` resolve venue tickers/slugs to the same `event_id` shape used by Odds API ingest, so prices pair correctly.

What's missing: **orderbook depth.** `odds_snapshot` has no size column. Polymarket WS `book` messages already carry full ask/bid arrays with sizes — we discard them at ingest. Kalshi `ticker` WS messages don't carry size at all; depth requires either the `orderbook_delta` WS channel or the `/markets/{ticker}/orderbook` REST endpoint. Without this, a cross-venue arb that looks great at displayed prices may only have $50 of fillable depth on the smaller leg, while the recommended stake suggests a much larger amount.

## Goals

- Capture top-of-book orderbook depth (dollar terms) for every Kalshi and Polymarket cache row.
- Expose it on the arbitrage API surface so the UI can render a "max $X" indicator per leg.
- Clamp recommended-stake math to the smaller leg's fillable size on cross-venue opportunities.
- Sportsbook rows stay at NULL — sportsbooks don't publish depth, and modeling their per-market max bet limits is out of scope.

## Non-goals

- True orderbook walk (filling beyond the top level at progressively worse prices). The scanner reports a single recommended stake at the displayed odds; the depth value tells the user whether that stake can actually fill at those odds.
- Per-user stake limit modeling (Polymarket KYC tiers, Kalshi account caps). Outside the price-discovery loop.
- Depth-aware EV / low-hold scanner. Those endpoints already filter to the best-price leg per outcome; depth is much less binding than on a multi-leg arb. Defer.
- Bid-side depth (only ask-side matters for the bettor entering a position).

## Architecture

### Schema — one new column on `odds_snapshot`

```sql
ALTER TABLE odds_snapshot ADD COLUMN max_stake_dollars REAL;
```

- `NULL` = unknown / unbounded (sportsbooks; legacy rows; transient before first orderbook poll lands).
- Non-null = approximate dollar amount fillable at the displayed `price_american`. Kalshi prices already include the 7% taker fee; Polymarket the 5% — the dollar amount represents money the bettor deploys at the fee-adjusted American odds the scanner consumes.
- Migration is idempotent (`ADD COLUMN`); tolerated by the existing `_MIGRATIONS` retry loop in `server/odds/cache.py`.

### Polymarket — capture from existing WS messages

The `book` message carries `asks: [{price, size}, ...]` per asset; `price_change` carries `price_changes: [{best_ask, best_bid, ...}, ...]`. The current `ws_ingest.py:_process_book` walks asks to find the minimum price (lines 124-141) and discards size. Extend it to also capture the size at the min-price level → `max_stake_dollars = best_ask_size_contracts × best_ask_price_dollars`.

For `_process_price_change`, the per-change object usually carries `best_ask` (price) only — Polymarket's delta messages don't include the new size at top-of-book on every update. Two options:
- Leave `max_stake_dollars` unchanged on `price_change`, refresh only on the next `book` event (which fires at most ~1 minute apart per market by their docs).
- Trigger an explicit re-`book` request on the WS when size becomes too stale.

**Chosen:** Option 1 — leave size stale between `book` events. The price keeps updating in real time via `price_change`; size only refreshes on `book` events. Documented as a known staleness window.

Zero new API calls. The data is already on the wire.

### Kalshi — new orderbook poller

Add a periodic task `_kalshi_orderbook_tick` to the existing `clv_scheduler` in `server/main.py`. Cadence: 60 seconds. For each market currently in `kalshi_fetcher.ingestor._templates` (the set of sports markets we care about), call `KalshiClient.get_orderbook(ticker)` (new method on `KalshiClient`).

The Kalshi `/markets/{ticker}/orderbook` response shape:
```json
{
  "orderbook": {
    "yes": [[price_cents, size_contracts], ...],   // sorted ascending or descending — verify at fetch time
    "no":  [[price_cents, size_contracts], ...]
  }
}
```

For each registered (ticker, ws_side) template, look up the matching side's best ask price + size, compute `max_stake_dollars = price_cents / 100 × size_contracts`, and upsert. Reuses the same template-based path the WS ticker ingestor already uses — only the price source differs.

**Cost:** ~100 sports markets at 60s cadence = ~1.7 calls/sec sustained. Kalshi's authenticated rate limit is 100 calls/sec — comfortable headroom.

**Staleness window:** Between orderbook polls, the WS `ticker` channel keeps `price_american` fresh. `max_stake_dollars` lags by up to 60s. Acceptable — depth changes meaningfully slower than price.

The Kalshi WS ticker ingestor is **not** modified — it continues to update price and only price. Size updates flow exclusively through the new orderbook poller.

### Cache writes — `upsert` already handles the new field

`OddsCache.upsert(rows)` uses named-parameter SQL — adding `max_stake_dollars` to the SET clause and the prepared dict is the entire change. No new upsert method needed. Callers that don't provide the field implicitly send `None` → column stays NULL.

### Arb scanner — clamp recommendation

The `ArbSide` model in `server/api/arbitrage.py` gains an optional `max_stake_dollars: float | None`. The `ArbOpportunity` gains `max_total_stake_dollars: float | None`.

In `scan_all_arbs` (`server/odds/arbitrage.py`), when emitting an opportunity:
- For each leg, look up the source row's `max_stake_dollars`.
- Compute `max_total_stake_dollars`: if any leg has `None`, the field is `None` (no clamp — sportsbook depth is unknown, treated as unlimited). Otherwise, `min(leg.max_stake / leg.stake_pct)` over all legs, giving the largest total stake that respects every leg's cap.

The recommended-stake math at the API layer is unchanged in shape — it returns `stake_pct` per leg as before. The new field is informational; the UI consumes it to clamp display.

### UI — per-leg badge + row-level cap caption

On `/edges` arb cards, each leg's price chip gets a small `max $X` badge when `max_stake_dollars` is non-null. Sportsbook legs (always null) stay clean. Cross-venue arbs (at least one Kalshi or Polymarket leg) always show the badge on those legs.

Below the row, if the user's stake-input value exceeds `max_total_stake_dollars`, display a short caption: `Fillable up to $Y at displayed price.` The stake input itself is not gated — the user may proceed at their entered stake, accepting the slippage.

### Error handling

| Failure | Behavior |
|---------|----------|
| Kalshi orderbook poll fails (network / 5xx / rate limit) | Skip that market this cycle. Existing `max_stake_dollars` stays. Log at warning level; resume next cycle. |
| Kalshi orderbook response missing expected side | Same — skip the row, log once per cycle. |
| Polymarket `book` message malformed / missing `asks` | Existing pattern — skip the row, log. Size update fails; price already updated. |
| `max_stake_dollars` arithmetic overflow / negative | Clamp to `None` on write. Defensive. |
| Migration on existing DB with old schema | `ADD COLUMN` is idempotent; the existing `_MIGRATIONS` tolerance handles "duplicate column" errors. |
| Arb scanner finds opportunity with inconsistent cap data (mixed null + non-null) | `max_total_stake_dollars = None` (don't clamp on incomplete info). |

### Testing

- Unit: `OddsCache.upsert` with a row containing `max_stake_dollars` → row is queryable with the field populated.
- Unit: Polymarket `_process_book` with a fixture that has multiple ask levels → extracts the size at the min-price level, not array order.
- Unit: Polymarket `_process_price_change` without size → leaves `max_stake_dollars` unchanged.
- Unit: Kalshi orderbook response fixture → expected `max_stake_dollars` per row, both YES-side and NO-side.
- Unit: Arb scanner — two-leg arb with sizes [$50, $500] at equal stake_pct → `max_total_stake_dollars` reflects the binding leg.
- Unit: Arb scanner — two-leg arb with one NULL leg → `max_total_stake_dollars` is None.
- Integration: existing arb endpoint tests still pass; new field is `Optional` and absent from older fixtures.

## Open / deferred

- **Bid-side depth.** Not needed for taker-side arb scanning. If we ever surface laying / two-sided market making, revisit.
- **Polymarket size staleness mitigation.** If empirical observation shows `book` events lag price too much, add an explicit re-`book` trigger when size data ages past N seconds.
- **EV / low-hold scanner depth awareness.** Single-leg endpoints; depth binding rarely matters. Defer until/unless real losses surface from this gap.
- **Kalshi `liquidity` field as secondary signal.** Already in `/markets` responses we fetch every 15s. Could persist alongside `max_stake_dollars` as a coarser long-term liquidity gauge. Not needed for the arb-clamp goal; defer.

## Out of scope

- Polling Kalshi for sportsbook-style "max bet" limits (sportsbook depth is unknown by design and likely unmodelable from public data).
- Reworking the arb scanner's pairing logic (already works for cross-venue).
- Touching the existing EV / low-hold endpoints (single-leg, depth less binding).
- Adding a "cross-venue only" filter chip on `/edges`. Deferred to a separate UI follow-up; this spec is data-layer + clamp behavior only.
