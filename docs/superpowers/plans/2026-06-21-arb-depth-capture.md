# Cross-Venue Arb Depth Capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture top-of-book orderbook depth for Kalshi + Polymarket cache rows so the arb scanner can clamp stake recommendations to fillable size on cross-venue opportunities.

**Architecture:** New `max_stake_dollars` column on `odds_snapshot`. Polymarket size comes from existing WS `book` messages (currently discarded). Kalshi requires a new `/markets/{ticker}/orderbook` REST poller (the ticker WS channel doesn't carry size) wired into the existing `clv_scheduler`. Arb scanner reads the column and emits per-leg + per-opportunity caps; UI surfaces them as "max $X" chips.

**Tech Stack:** Python 3.11, FastAPI, sqlite3, APScheduler. Next.js 16, React 19, SWR.

**Spec:** `docs/superpowers/specs/2026-06-21-arb-depth-capture-design.md`

---

## Pre-flight

```bash
git status
# Should be clean (or only have unstaged user_settings.json)
git log --oneline -3
# Should show: 58a8b71 (spec fixes), 1774070 (spec), 87ba984 (#11 done in roadmap)
```

---

## Phase 1 — Schema + cache layer

### Task 1: Add `max_stake_dollars` column

**Files:**
- Modify: `server/odds/cache.py` (SCHEMA constant, _MIGRATIONS list, upsert method)
- Test: `server/tests/test_cache.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_cache.py`:

```python
def test_max_stake_dollars_column_exists(tmp_path):
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(odds_snapshot)")}
    assert "max_stake_dollars" in cols


def test_upsert_persists_max_stake_dollars(tmp_path):
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -145, "fetched_at": now,
        "max_stake_dollars": 234.50,
    }])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["max_stake_dollars"] == 234.50


def test_upsert_without_max_stake_dollars_is_null(tmp_path):
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "draftkings",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -145, "fetched_at": now,
    }])
    rows = cache.all_current()
    assert rows[0]["max_stake_dollars"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py::test_max_stake_dollars_column_exists -v
```

Expected: FAIL — column doesn't exist.

- [ ] **Step 3: Add to schema + migration + upsert**

In `server/odds/cache.py`:

(a) Inside the `CREATE TABLE IF NOT EXISTS odds_snapshot` block, add a new column line just before the closing PRIMARY KEY:

```sql
  max_stake_dollars REAL,
```

(b) Append to `_MIGRATIONS` list:

```python
    # 0.5: per-row top-of-book depth in dollars. NULL for sportsbook
    # rows (no depth data) and pre-migration rows; populated by the
    # Polymarket WS ingest path and the Kalshi orderbook poller.
    "ALTER TABLE odds_snapshot ADD COLUMN max_stake_dollars REAL",
```

(c) Extend the `upsert` method:

In the `prepared.append({...})` block, add:
```python
                "max_stake_dollars": r.get("max_stake_dollars"),
```

In the `INSERT INTO odds_snapshot` columns list, append `, max_stake_dollars`.
In the `VALUES` list, append `, :max_stake_dollars`.
In the `DO UPDATE SET` clause, append:
```sql
                   max_stake_dollars = excluded.max_stake_dollars,
```

- [ ] **Step 4: Run all cache tests**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -v
```

Expected: all pass (including 3 new).

- [ ] **Step 5: Commit**

```bash
git add server/odds/cache.py server/tests/test_cache.py
git commit -m "$(cat <<'EOF'
feat(db): add max_stake_dollars column to odds_snapshot (#10)

NULL for sportsbook rows and legacy data; populated by Polymarket WS
ingest and the new Kalshi orderbook poller in later tasks. Reads
flow through unchanged; writes pass the value via cache.upsert's
named-param SQL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Polymarket WS depth capture

### Task 2: Extract size from `book` messages

**Files:**
- Modify: `server/odds/books/polymarket/ws_ingest.py` (`_process_book` and `_upsert_with_price`)
- Test: `server/tests/test_polymarket_ws_ingest.py` (existing — extend)

- [ ] **Step 1: Check existing test file**

```bash
ls server/tests/test_polymarket_ws_ingest.py 2>/dev/null && head -20 server/tests/test_polymarket_ws_ingest.py
```

If it doesn't exist, create it from scratch. Otherwise, extend.

- [ ] **Step 2: Write a failing test**

Append (or write fresh):

```python
import pytest
from datetime import datetime, timezone
from server.odds.cache import OddsCache
from server.odds.books.polymarket.ws_ingest import PolymarketBookIngestor


@pytest.fixture
def cache(tmp_path):
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _template_row(asset_id: str, cache) -> dict:
    # Simulate what the REST normalizer would emit + register
    return {
        "_asset_id": asset_id,
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": datetime(2026, 6, 21, tzinfo=timezone.utc),
        "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -150,
        "fetched_at": datetime.now(timezone.utc),
    }


def test_book_message_captures_max_stake_dollars(cache):
    ing = PolymarketBookIngestor(cache=cache)
    ing.register_rows([_template_row("0xabc", cache)])
    msg = {
        "event_type": "book",
        "asset_id": "0xabc",
        # Polymarket sorts asks DESCENDING by price; best (lowest) is last.
        "asks": [
            {"price": "0.70", "size": "500"},
            {"price": "0.65", "size": "1000"},
            {"price": "0.62", "size": "234.5"},  # min price = best ask
        ],
        "timestamp": "1782070000000",
    }
    n = ing.process_message(msg)
    assert n == 1
    rows = cache.all_current()
    # best ask = 0.62, size = 234.5 → 0.62 * 234.5 = 145.39
    assert rows[0]["max_stake_dollars"] == pytest.approx(145.39, abs=0.01)


def test_book_message_with_no_asks_keeps_max_stake_null(cache):
    ing = PolymarketBookIngestor(cache=cache)
    ing.register_rows([_template_row("0xabc", cache)])
    msg = {"event_type": "book", "asset_id": "0xabc", "asks": []}
    n = ing.process_message(msg)
    assert n == 0  # no asks → no update


def test_price_change_leaves_max_stake_dollars_unchanged(cache):
    """Polymarket delta messages don't carry size; we leave the existing
    max_stake_dollars in place rather than nulling it."""
    ing = PolymarketBookIngestor(cache=cache)
    ing.register_rows([_template_row("0xabc", cache)])
    # First, a book message sets size
    ing.process_message({
        "event_type": "book", "asset_id": "0xabc",
        "asks": [{"price": "0.62", "size": "100"}],
        "timestamp": "1782070000000",
    })
    # Then a price_change updates only price
    ing.process_message({
        "event_type": "price_change",
        "asset_id": "0xabc",
        "price_changes": [{"asset_id": "0xabc", "best_ask": "0.60", "best_bid": "0.55"}],
        "timestamp": "1782070001000",
    })
    rows = cache.all_current()
    # size from the first book event should persist; only price changed
    assert rows[0]["max_stake_dollars"] == pytest.approx(62.0, abs=0.01)
```

- [ ] **Step 3: Run test to verify failure**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_ws_ingest.py -v -k max_stake
```

Expected: FAIL on the first test — max_stake_dollars is None.

- [ ] **Step 4: Implement**

In `server/odds/books/polymarket/ws_ingest.py`, modify `_process_book`:

Replace the body's price-extraction block with:

```python
        asks = msg.get("asks") or []
        if not asks:
            return 0
        # Find the (price, size) at the min-price level. Defensive against
        # array-ordering changes upstream.
        best_price: float | None = None
        best_size: float | None = None
        for ask in asks:
            if not isinstance(ask, dict):
                continue
            try:
                p = float(ask.get("price"))
                s = float(ask.get("size"))
            except (TypeError, ValueError):
                continue
            if best_price is None or p < best_price:
                best_price = p
                best_size = s
        if best_price is None:
            return 0
        max_stake_dollars = round(best_price * (best_size or 0), 4) or None

        return self._upsert_with_price(
            template, best_price, msg.get("timestamp"),
            max_stake_dollars=max_stake_dollars,
        )
```

Update `_upsert_with_price` signature + body to accept and propagate `max_stake_dollars`:

```python
    def _upsert_with_price(
        self, template: dict, price: float, ts_str: str | None,
        max_stake_dollars: float | None = None,
    ) -> int:
        american = yes_to_american(price)
        if american is None:
            return 0
        fetched_at = _parse_ws_timestamp(ts_str) or datetime.now(timezone.utc)
        new_row = {
            **template,
            "price_american": int(american),
            "fetched_at": fetched_at,
        }
        if max_stake_dollars is not None:
            new_row["max_stake_dollars"] = max_stake_dollars
        try:
            self.cache.upsert([new_row])
        except Exception:
            logger.exception("polymarket WS: upsert failed for %s",
                             template.get("_asset_id"))
            return 0
        # ... existing bookkeeping (updates_total++, last_update_at) ...
        return 1
```

(Verify the existing `_process_price_change` already calls `_upsert_with_price` WITHOUT `max_stake_dollars` — if so, that path naturally leaves the existing column value unchanged via the `if max_stake_dollars is not None` guard. If `_upsert_with_price` instead always writes a fresh row, you'll need to read the existing row's `max_stake_dollars` and preserve it. Check before implementing.)

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_ws_ingest.py -v
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: new tests pass; no regressions elsewhere.

- [ ] **Step 6: Commit**

```bash
git add server/odds/books/polymarket/ws_ingest.py server/tests/test_polymarket_ws_ingest.py
git commit -m "$(cat <<'EOF'
feat(polymarket): capture top-of-book size from WS book messages (#10)

Polymarket's `book` events already carry asks: [{price, size}]; this
extracts the size at the min-price level and persists it as
max_stake_dollars. price_change deltas don't carry size, so we leave
the existing value in place — known staleness window of ~1 minute
between book events.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Kalshi orderbook poller

### Task 3: `KalshiClient.get_orderbook`

**Files:**
- Modify: `server/odds/books/kalshi/client.py`
- Test: `server/tests/test_kalshi_normalizer.py` (or new test file; choose the smallest existing kalshi-client test surface)

- [ ] **Step 1: Capture a real Kalshi orderbook response as a fixture**

This is the safest way to pin the response shape. Get the fixture by either:
- (preferred) Hitting the live endpoint once with the existing client and saving the JSON:
  ```bash
  .venv/bin/python -c "
  import asyncio, json
  from server.odds.books.kalshi.client import KalshiClient
  from server.config import Config
  config = Config.from_env()
  client = KalshiClient(api_key=config.kalshi_api_key, private_key_path=config.kalshi_private_key_path)
  # Pick any ticker from the registered set — main.py lifespan logs them on startup
  ticker = 'KXNBAFINALS-26-OKC'  # replace with a known live ticker
  ob = asyncio.run(client._signed_get(f'/markets/{ticker}/orderbook'))
  print(json.dumps(ob, indent=2))
  " > server/tests/fixtures/kalshi_orderbook.json
  ```
- Or, if no live key is available, hand-craft a representative fixture matching Kalshi's documented shape and noted in the file's docstring.

Save the captured JSON at `server/tests/fixtures/kalshi_orderbook.json`. Add a short header comment in the test file describing which ticker / market it came from.

- [ ] **Step 2: Write the failing test for the client method**

Add to `server/tests/test_kalshi_normalizer.py` (or a new file `test_kalshi_client.py`):

```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_get_orderbook_calls_signed_get_with_path():
    from server.odds.books.kalshi.client import KalshiClient
    client = KalshiClient(
        api_key="test", private_key_path=None,
    )
    client._signed_get = AsyncMock(return_value={"orderbook": {"yes": [], "no": []}})
    result = await client.get_orderbook("KXMARKET-TICKER")
    client._signed_get.assert_called_once_with("/markets/KXMARKET-TICKER/orderbook")
    assert "orderbook" in result
```

- [ ] **Step 3: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -v -k get_orderbook
```

Expected: AttributeError — get_orderbook doesn't exist.

- [ ] **Step 4: Implement**

In `server/odds/books/kalshi/client.py`, add after `get_portfolio_fills`:

```python
    async def get_orderbook(self, ticker: str) -> dict:
        """GET /markets/{ticker}/orderbook — full L2 book for one market.

        Returns the parsed JSON response, shape:
          {"orderbook": {"yes": [[price_cents, size], ...],
                          "no":  [[price_cents, size], ...]}}

        Signed via _signed_get; auth required for higher rate limits.
        Pinned via fixture at server/tests/fixtures/kalshi_orderbook.json.
        """
        return await self._signed_get(f"/markets/{ticker}/orderbook")
```

- [ ] **Step 5: Run + commit**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -v -k get_orderbook
git add server/odds/books/kalshi/client.py server/tests/test_kalshi_normalizer.py server/tests/fixtures/kalshi_orderbook.json
git commit -m "$(cat <<'EOF'
feat(kalshi): get_orderbook client method + response fixture (#10)

New thin wrapper around /markets/{ticker}/orderbook signed via the
existing _signed_get helper. Fixture captures the response shape for
tests in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Public `registered_tickers()` accessor

**Files:**
- Modify: `server/odds/books/kalshi/ws_ingest.py` (add public method)
- Modify: `server/odds/books/kalshi/fetcher.py` (add passthrough)
- Test: `server/tests/test_kalshi_normalizer.py` (or new)

- [ ] **Step 1: Failing test**

```python
def test_ingestor_registered_tickers_returns_known_tickers(tmp_path):
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    from server.odds.books.kalshi.ws_ingest import KalshiTickerIngestor
    cache = OddsCache(tmp_path / "test.db"); cache.init()
    ing = KalshiTickerIngestor(cache=cache)
    now = datetime.now(timezone.utc)
    ing.register_rows([{
        "_market_ticker": "KX-A", "_ws_side": "yes",
        "event_id": "e1", "sport_key": "nba", "home_team": "BOS",
        "away_team": "MIA", "commence_time": now,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -145, "fetched_at": now,
    }, {
        "_market_ticker": "KX-B", "_ws_side": "yes",
        "event_id": "e2", "sport_key": "nba", "home_team": "OKC",
        "away_team": "MIN", "commence_time": now,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": "OKC",
        "outcome_point": None, "price_american": +110, "fetched_at": now,
    }])
    assert set(ing.registered_tickers()) == {"KX-A", "KX-B"}
```

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -v -k registered_tickers
```

- [ ] **Step 3: Implement**

In `server/odds/books/kalshi/ws_ingest.py`, in `KalshiTickerIngestor`, add:

```python
    def registered_tickers(self) -> list[str]:
        """Public accessor — list of market_tickers currently in the
        template map. Used by the orderbook poller to enumerate which
        markets to fetch depth for."""
        return list(self._templates.keys())
```

In `server/odds/books/kalshi/fetcher.py`, in `KalshiFetcher`, add passthrough:

```python
    def registered_tickers(self) -> list[str]:
        """Markets currently in the ingestor's template map."""
        return self._ingestor.registered_tickers()
```

- [ ] **Step 4: Run tests + commit**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -v -k registered_tickers
git add server/odds/books/kalshi/ws_ingest.py server/odds/books/kalshi/fetcher.py server/tests/test_kalshi_normalizer.py
git commit -m "$(cat <<'EOF'
feat(kalshi): public registered_tickers() on ingestor + fetcher (#10)

Avoids the orderbook scheduler reaching into _templates from main.py.
Thin passthrough; no behavior change to existing callers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Orderbook → max_stake_dollars translator

**Files:**
- Create: `server/odds/books/kalshi/orderbook_depth.py`
- Test: `server/tests/test_kalshi_orderbook_depth.py`

- [ ] **Step 1: Inspect the fixture captured in Task 3**

```bash
cat server/tests/fixtures/kalshi_orderbook.json | head -40
```

Confirm the array shape (entries are `[price, size]` pairs, or dicts with `price`/`size` keys). This pins the parsing logic.

- [ ] **Step 2: Write the failing test**

Create `server/tests/test_kalshi_orderbook_depth.py`:

```python
import json
from pathlib import Path
import pytest


# This fixture is hand-crafted to match Kalshi's documented orderbook
# shape — each side is sorted ascending by price (so the LAST entry
# is the highest-price bid on that side).
SAMPLE = {
    "orderbook": {
        "yes": [
            [40, 200],   # 200 contracts bid at 40c
            [42, 100],
            [45, 50],    # highest-price YES bid = 45c, 50 contracts
        ],
        "no": [
            [55, 150],
            [58, 80],    # highest-price NO bid = 58c, 80 contracts
        ],
    }
}


def test_yes_side_size_from_no_bids():
    """A row with ws_side='yes' needs the YES ASK, which is derived from
    the best NO BID: yes_ask_cents = 100 - best_no_bid_cents.
    Best NO bid = 58c, size 80 → yes_ask = 42c, size = 80 contracts.
    max_stake_dollars = 0.42 * 80 = 33.60.
    """
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    result = max_stake_for_side(SAMPLE, ws_side="yes")
    assert result == pytest.approx(33.60, abs=0.01)


def test_no_side_size_from_yes_bids():
    """ws_side='no' needs the NO ASK from the best YES BID:
    Best YES bid = 45c, size 50 → no_ask = 55c, size = 50.
    max_stake_dollars = 0.55 * 50 = 27.50.
    """
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    result = max_stake_for_side(SAMPLE, ws_side="no")
    assert result == pytest.approx(27.50, abs=0.01)


def test_empty_opposite_side_returns_none():
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    empty = {"orderbook": {"yes": [], "no": []}}
    assert max_stake_for_side(empty, ws_side="yes") is None


def test_malformed_orderbook_returns_none():
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    assert max_stake_for_side({}, ws_side="yes") is None
    assert max_stake_for_side({"orderbook": {}}, ws_side="yes") is None


def test_fixture_loads_and_parses():
    """Smoke-test against the live-captured fixture in Task 3.
    Both sides should return either a positive number or None."""
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    path = Path(__file__).parent / "fixtures" / "kalshi_orderbook.json"
    if not path.exists():
        pytest.skip("kalshi_orderbook.json fixture not captured yet")
    data = json.loads(path.read_text())
    for side in ("yes", "no"):
        result = max_stake_for_side(data, ws_side=side)
        assert result is None or result > 0
```

- [ ] **Step 3: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_orderbook_depth.py -v
```

- [ ] **Step 4: Implement**

Create `server/odds/books/kalshi/orderbook_depth.py`:

```python
"""Kalshi orderbook response → max_stake_dollars translator.

Kalshi's /markets/{ticker}/orderbook returns each side's BIDS — `yes`
is people bidding to buy YES; `no` is people bidding to buy NO. A
taker filling YES at the best ask is equivalent to taking the best
NO bid (since YES_ask_cents = 100 - NO_bid_cents). This module owns
that inversion + size lookup, isolated so it can be unit-tested
without the rest of the WS stack.
"""
from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)


def _highest_price_entry(entries: Iterable) -> tuple[int, float] | None:
    """Walk a side's bid list and return (price_cents, size_contracts)
    of the highest-price entry. Tolerates both [[price,size]] tuple
    format and [{price,size}] dict format. Returns None if empty or
    unparseable."""
    best_p: int | None = None
    best_s: float | None = None
    for raw in entries or []:
        try:
            if isinstance(raw, dict):
                p = int(raw.get("price"))
                s = float(raw.get("size"))
            else:
                p = int(raw[0])
                s = float(raw[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (0 < p < 100):
            continue
        if s <= 0:
            continue
        if best_p is None or p > best_p:
            best_p = p
            best_s = s
    if best_p is None or best_s is None:
        return None
    return best_p, best_s


def max_stake_for_side(
    orderbook_response: dict, *, ws_side: str,
) -> float | None:
    """Compute max_stake_dollars at the best ask for a given side.

    For ws_side='yes', use the opposite side's best bid (NO bids) and
    invert: yes_ask = 100 - no_bid_cents; size = that no_bid's size.
    For ws_side='no', symmetric using YES bids.

    Returns the dollar amount fillable at the displayed price, or
    None when the orderbook is empty / malformed / one-sided.
    """
    if not isinstance(orderbook_response, dict):
        return None
    ob = orderbook_response.get("orderbook")
    if not isinstance(ob, dict):
        return None
    opposite_side = "no" if ws_side == "yes" else "yes"
    best = _highest_price_entry(ob.get(opposite_side))
    if best is None:
        return None
    opposite_bid_cents, size = best
    inferred_ask_cents = 100 - opposite_bid_cents
    if inferred_ask_cents <= 0:
        return None
    return round(inferred_ask_cents / 100.0 * size, 2)
```

- [ ] **Step 5: Run tests + commit**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_orderbook_depth.py -v
git add server/odds/books/kalshi/orderbook_depth.py server/tests/test_kalshi_orderbook_depth.py
git commit -m "$(cat <<'EOF'
feat(kalshi): orderbook → max_stake_dollars translator (#10)

Kalshi's orderbook endpoint returns BIDS by side; YES asks are derived
by inverting against NO bids. This module owns the inversion + size
extraction, isolated for unit testing. Pinned by fixture captured
against a live market in Task 3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Orderbook poll tick + scheduler wiring

**Files:**
- Create: `server/odds/books/kalshi/orderbook_poller.py` (the per-tick worker)
- Modify: `server/main.py` (lifespan adds the job to clv_scheduler)
- Test: `server/tests/test_kalshi_orderbook_poller.py`

- [ ] **Step 1: Failing test**

```python
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path):
    c = OddsCache(tmp_path / "test.db"); c.init()
    return c


def _register_template(cache, ticker: str, side: str = "yes"):
    """Insert one initial row + return a (template, side) tuple shaped
    like what KalshiTickerIngestor stores."""
    now = datetime.now(timezone.utc)
    return {
        "event_id": "e1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -145,
        "fetched_at": now,
    }, side


def test_poll_writes_max_stake_dollars(cache):
    from server.odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
    ingestor = MagicMock()
    ingestor.registered_tickers.return_value = ["KX-A"]
    # Make the ingestor's _templates accessible
    ingestor._templates = {"KX-A": [_register_template(cache, "KX-A", "yes")]}
    client = MagicMock()
    client.get_orderbook = AsyncMock(return_value={
        "orderbook": {
            "yes": [[40, 200], [45, 50]],
            "no":  [[55, 150], [58, 80]],
        }
    })

    asyncio.run(poll_kalshi_orderbooks(client=client, ingestor=ingestor, cache=cache))
    rows = cache.all_current()
    assert len(rows) == 1
    # YES side: best NO bid = 58c × 80 → 42c × 80 contracts = $33.60
    assert rows[0]["max_stake_dollars"] == pytest.approx(33.60, abs=0.01)


def test_poll_skips_unknown_tickers(cache):
    from server.odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
    ingestor = MagicMock()
    ingestor.registered_tickers.return_value = ["KX-A"]
    ingestor._templates = {}  # not registered
    client = MagicMock()
    client.get_orderbook = AsyncMock(return_value={"orderbook": {"yes": [], "no": []}})
    # Should not raise even when the ticker has no template
    asyncio.run(poll_kalshi_orderbooks(client=client, ingestor=ingestor, cache=cache))


def test_poll_tolerates_client_failure(cache):
    from server.odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
    ingestor = MagicMock()
    ingestor.registered_tickers.return_value = ["KX-A", "KX-B"]
    ingestor._templates = {
        "KX-A": [_register_template(cache, "KX-A", "yes")],
        "KX-B": [_register_template(cache, "KX-B", "yes")],
    }
    client = MagicMock()
    # First call raises; second succeeds
    client.get_orderbook = AsyncMock(side_effect=[
        Exception("kaboom"),
        {"orderbook": {"yes": [[40, 100]], "no": [[55, 100]]}},
    ])
    asyncio.run(poll_kalshi_orderbooks(client=client, ingestor=ingestor, cache=cache))
    # KX-B should have been updated despite KX-A failing
    rows = cache.all_current()
    # We initialized two rows, both via _register_template's bookmaker_key=kalshi
    # Only one row will have non-null max_stake_dollars (KX-B's event_id="e1" matches both,
    # so the keys collide — verify a non-null value is present somewhere)
    assert any(r.get("max_stake_dollars") is not None for r in rows)
```

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_orderbook_poller.py -v
```

- [ ] **Step 3: Implement `orderbook_poller.py`**

```python
"""Kalshi orderbook poller — periodic top-of-book depth refresh.

Runs every 60s from the lifespan scheduler. For each registered
Kalshi market (per KalshiTickerIngestor.registered_tickers), hits
GET /markets/{ticker}/orderbook, translates the response to
max_stake_dollars via orderbook_depth.max_stake_for_side, and upserts
the per-(template, side) cache row. WS ticker channel still owns
price; this owns size.

Tolerates per-market failures — one ticker's 5xx doesn't block the
rest of the cycle. Sleep between calls is a single `await asyncio.
sleep(0.05)` to stay under the 100/sec auth'd rate limit even for
~200-market batches.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ...cache import OddsCache
from .orderbook_depth import max_stake_for_side


logger = logging.getLogger(__name__)

_INTER_CALL_DELAY_S = 0.05


async def poll_kalshi_orderbooks(*, client, ingestor, cache: OddsCache) -> int:
    """One sync cycle. Returns count of rows updated with non-null
    max_stake_dollars. Exceptions during a single market's poll are
    logged + skipped; rest of the batch continues."""
    tickers = ingestor.registered_tickers()
    if not tickers:
        return 0

    updated = 0
    for ticker in tickers:
        try:
            ob = await client.get_orderbook(ticker)
        except Exception:
            logger.exception("kalshi orderbook poll: get failed for %s", ticker)
            continue

        templates = getattr(ingestor, "_templates", {}).get(ticker, [])
        if not templates:
            continue

        now = datetime.now(timezone.utc)
        rows_to_upsert: list[dict] = []
        for template, side in templates:
            max_stake = max_stake_for_side(ob, ws_side=side)
            if max_stake is None:
                continue
            new_row = {
                **template,
                "fetched_at": template.get("fetched_at") or now,
                "max_stake_dollars": max_stake,
            }
            # Preserve the existing price_american from the template if
            # it's already populated by the WS path; orderbook poll
            # never decides price.
            rows_to_upsert.append(new_row)

        if rows_to_upsert:
            try:
                cache.upsert(rows_to_upsert)
                updated += len(rows_to_upsert)
            except Exception:
                logger.exception("kalshi orderbook poll: upsert failed for %s", ticker)
                continue

        await asyncio.sleep(_INTER_CALL_DELAY_S)

    if updated:
        logger.info("kalshi orderbook poll: %d rows refreshed", updated)
    return updated
```

- [ ] **Step 4: Wire into lifespan**

In `server/main.py`, inside the `if initial_mode == CacheMode.LIVE:` block (near where the existing Kalshi portfolio sync job lives), add:

```python
            # Kalshi orderbook depth poll — pulls top-of-book size for
            # registered sports markets so the arb scanner can clamp
            # stake recommendations to fillable depth. 60s cadence.
            async def _kalshi_orderbook_tick():
                try:
                    if not kalshi_fetcher.client.is_authenticated:
                        return
                    from .odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
                    await poll_kalshi_orderbooks(
                        client=kalshi_fetcher.client,
                        ingestor=kalshi_fetcher._ingestor,
                        cache=cache,
                    )
                except Exception:
                    logging.exception("kalshi orderbook poll tick failed")

            clv_scheduler.add_job(
                _kalshi_orderbook_tick,
                trigger="interval", seconds=60,
                id="kalshi_orderbook_poll",
                replace_existing=True, max_instances=1,
            )
```

- [ ] **Step 5: Verify server boots**

```bash
lsof -ti :8000 | xargs -r kill 2>/dev/null
sleep 1
nohup .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
disown
sleep 5
grep -E "kalshi_orderbook|kalshi orderbook" /tmp/uvicorn.log | head -3
curl -s http://127.0.0.1:8000/api/health | head -c 200
```

Expected: server boots; log shows the new job is scheduled (only if cache_mode=live).

- [ ] **Step 6: Run tests + commit**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_orderbook_poller.py -v
git add server/odds/books/kalshi/orderbook_poller.py server/main.py server/tests/test_kalshi_orderbook_poller.py
git commit -m "$(cat <<'EOF'
feat(kalshi): periodic orderbook poller for top-of-book depth (#10)

60s cadence APScheduler job in the existing clv_scheduler. Iterates
ingestor.registered_tickers(), calls client.get_orderbook, translates
via orderbook_depth.max_stake_for_side, upserts. Tolerates per-market
failures. Inter-call 50ms sleep stays under Kalshi's 100/sec limit.
No-op when Kalshi auth isn't configured.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Arb scanner integration

### Task 7: `max_stake_dollars` on ArbSide + ArbOpportunity

**Files:**
- Modify: `server/odds/arbitrage.py` (`_emit` + `_try_three_way` emission)
- Modify: `server/api/arbitrage.py` (`ArbSide` + `ArbOpportunity` Pydantic models)
- Test: `server/tests/test_pairing.py` or new `test_arbitrage_depth.py`

- [ ] **Step 1: Failing test**

Create `server/tests/test_arbitrage_depth.py`:

```python
from server.odds.arbitrage import scan_all_arbs


def _game_with_two_books(market_kind: str, side_a_price: int, side_b_price: int,
                         side_a_book: str, side_b_book: str,
                         side_a_size: float | None, side_b_size: float | None,
                         point: float | None = None):
    """Construct a one-event game dict that yields exactly one h2h or
    spreads/totals arb opportunity between two distinct books."""
    return {
        "sport_key": "nba", "event_id": "e1",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": "2026-06-21T19:00:00+00:00",
        "is_live": False, "stale_seconds": 0,
        "markets": [{
            "market_key": market_kind,
            "outcomes": [
                {
                    "outcome_name": "BOS",
                    "prices": [{
                        "bookmaker_key": side_a_book,
                        "price_american": side_a_price,
                        "point": point,
                        "fetched_at": "2026-06-21T19:00:00+00:00",
                        "max_stake_dollars": side_a_size,
                    }],
                },
                {
                    "outcome_name": "MIA",
                    "prices": [{
                        "bookmaker_key": side_b_book,
                        "price_american": side_b_price,
                        "point": -point if point is not None else None,
                        "fetched_at": "2026-06-21T19:00:00+00:00",
                        "max_stake_dollars": side_b_size,
                    }],
                },
            ],
        }],
    }


def test_each_side_carries_its_max_stake():
    """An h2h arb between Polymarket ($50) and DK (None) yields:
    sides[0].max_stake_dollars == 50, sides[1].max_stake_dollars is None."""
    game = _game_with_two_books(
        "h2h", side_a_price=+200, side_b_price=-150,
        side_a_book="polymarket", side_b_book="draftkings",
        side_a_size=50.0, side_b_size=None,
    )
    opps = scan_all_arbs([game], books_filter=None)
    assert len(opps) == 1
    assert opps[0]["sides"][0]["max_stake_dollars"] == 50.0
    assert opps[0]["sides"][1]["max_stake_dollars"] is None


def test_max_total_stake_is_none_when_any_leg_is_none():
    """A sportsbook leg has unknown depth → no overall clamp."""
    game = _game_with_two_books(
        "h2h", +200, -150, "polymarket", "draftkings", 50.0, None,
    )
    opps = scan_all_arbs([game], books_filter=None)
    assert opps[0]["max_total_stake_dollars"] is None


def test_max_total_stake_clamps_to_binding_leg():
    """Both legs have depth → max total = min over legs of size/stake_pct."""
    game = _game_with_two_books(
        "h2h", +100, +100, "polymarket", "kalshi", 50.0, 500.0,
    )
    opps = scan_all_arbs([game], books_filter=None)
    # +100 / +100: stake_pct = 50/50; binding leg = polymarket at $50,
    # so total = $50 / 0.5 = $100.
    assert opps[0]["max_total_stake_dollars"] == 100.0
```

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_arbitrage_depth.py -v
```

- [ ] **Step 3: Implement — extend `_emit` in `server/odds/arbitrage.py`**

Modify the `sides` block to include the size field, and add the top-level clamp computation. Replace the existing `_emit` body's return with:

```python
    a_size = best_a.get("max_stake_dollars")
    b_size = best_b.get("max_stake_dollars")
    stake_a_pct = imp_a / total * 100.0
    stake_b_pct = imp_b / total * 100.0
    if a_size is not None and b_size is not None and stake_a_pct > 0 and stake_b_pct > 0:
        cap_a = a_size / (stake_a_pct / 100.0)
        cap_b = b_size / (stake_b_pct / 100.0)
        max_total = round(min(cap_a, cap_b), 2)
    else:
        max_total = None
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,
        "point": point,
        "roi_pct": roi * 100.0,
        "max_total_stake_dollars": max_total,
        "sides": [
            {
                "outcome_name": side_a["outcome_name"],
                "book": best_a["bookmaker_key"],
                "price_american": best_a["price_american"],
                "point": best_a.get("point"),
                "stake_pct": stake_a_pct,
                "max_stake_dollars": a_size,
            },
            {
                "outcome_name": side_b["outcome_name"],
                "book": best_b["bookmaker_key"],
                "price_american": best_b["price_american"],
                "point": best_b.get("point"),
                "stake_pct": stake_b_pct,
                "max_stake_dollars": b_size,
            },
        ],
    }
```

Apply the same pattern to `_try_three_way` / its emit path (3 legs, same min-over-legs clamp).

- [ ] **Step 4: Extend Pydantic models**

In `server/api/arbitrage.py`:

```python
class ArbSide(BaseModel):
    outcome_name: str
    book: str
    price_american: int
    point: float | None = None
    stake_pct: float
    max_stake_dollars: float | None = None


class ArbOpportunity(BaseModel):
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    market_kind: Literal["h2h", "spreads", "totals"]
    point: float | None = None
    roi_pct: float
    sides: list[ArbSide]
    max_total_stake_dollars: float | None = None
```

- [ ] **Step 5: Verify rows_to_games carries max_stake_dollars through**

Check `server/odds/best_odds.py` — find `rows_to_games` and confirm the price dicts it emits include `max_stake_dollars` from each `odds_snapshot` row. If not, add the field to the price dict construction (same pattern as `point`, `bookmaker_key`).

```bash
grep -n "rows_to_games\|bookmaker_key.*price_american\|point.*price_american" server/odds/best_odds.py | head -10
```

If the price dict construction doesn't already pass through extra columns, add `"max_stake_dollars": r.get("max_stake_dollars")` to the price dict literal.

- [ ] **Step 6: Run tests + commit**

```bash
.venv/bin/python -m pytest server/tests/test_arbitrage_depth.py -v
.venv/bin/python -m pytest server/tests/test_api.py -v -k arb
git add server/odds/arbitrage.py server/api/arbitrage.py server/tests/test_arbitrage_depth.py server/odds/best_odds.py
git commit -m "$(cat <<'EOF'
feat(arb): emit max_stake_dollars per leg + max_total_stake_dollars (#10)

Each ArbSide carries its leg's depth (null for sportsbooks). The
opportunity-level max_total_stake_dollars is computed by inverting
each leg's stake_pct against its size and taking the min — i.e., the
largest total stake that respects every leg's fillable depth. NULL on
any leg → null total (don't clamp on incomplete info).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Frontend surfacing

### Task 8: Regenerate API types

**Files:**
- Modify: `web/types/api.d.ts` (regenerated from OpenAPI schema)
- Modify: `web/openapi.json` (regenerated)

- [ ] **Step 1: Regenerate**

Find the existing schema-regen command (likely a script or doc in the repo):

```bash
grep -rn "openapi-typescript\|openapi.json" web/package.json
```

Run it (usually `npm run` something in `web/`, or a Python script that dumps the FastAPI schema). If unclear, you can extract the schema directly:

```bash
curl -s http://127.0.0.1:8000/openapi.json > web/openapi.json
cd web && npx openapi-typescript openapi.json -o types/api.d.ts && cd ..
```

- [ ] **Step 2: Confirm the new fields are in the generated types**

```bash
grep -A 1 "max_stake_dollars\|max_total_stake_dollars" web/types/api.d.ts | head -8
```

Expected: both fields appear in `ArbSide` and `ArbOpportunity` definitions.

- [ ] **Step 3: Commit**

```bash
git add web/openapi.json web/types/api.d.ts
git commit -m "$(cat <<'EOF'
chore(web): regenerate API types — adds max_stake_dollars fields (#10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Per-leg "max $X" badge on arb cards

**Files:**
- Modify: the arb-row rendering component (likely `web/components/edges/edges-table.tsx` or similar — locate via grep)

- [ ] **Step 1: Locate the arb-row leg rendering**

```bash
grep -rn "ArbSide\|stake_pct\|price_american" web/components/edges web/app/edges 2>/dev/null | head -10
```

Identify the file + the JSX block that renders each side's price chip.

- [ ] **Step 2: Add the badge**

Next to each side's price chip, conditionally render:

```tsx
{side.max_stake_dollars != null && (
  <span
    className="ml-1 text-[10px] text-text-3 tabular"
    title={`Top-of-book depth at the displayed price`}
  >
    max ${side.max_stake_dollars.toFixed(0)}
  </span>
)}
```

- [ ] **Step 3: Add row-level "fillable up to $X" caption**

Below the row, if the user's stake input exceeds `opp.max_total_stake_dollars`:

```tsx
{opp.max_total_stake_dollars != null && userStake > opp.max_total_stake_dollars && (
  <div className="text-[11px] text-text-3 mt-1">
    Fillable up to ${opp.max_total_stake_dollars.toFixed(0)} at displayed price.
  </div>
)}
```

(The exact integration depends on how `userStake` is threaded into the row component — inspect the existing stake-input logic and follow that pattern.)

- [ ] **Step 4: Browser smoke-test**

```bash
# Restart server if it's not already up
lsof -ti :8000 | xargs -r kill 2>/dev/null
sleep 1
nohup .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
disown
sleep 5
```

Open `http://localhost:3000/edges?type=arb` in Playwright. Inspect a cross-venue arb (one with a kalshi or polymarket leg). Confirm:
- The leg with non-null `max_stake_dollars` shows the "max $X" chip
- Sportsbook legs do not show the chip
- When the stake input exceeds the cap, the caption appears

- [ ] **Step 5: Commit**

```bash
git add web/components/edges/ web/app/edges/
git commit -m "$(cat <<'EOF'
feat(web): max-depth badge + clamp caption on cross-venue arbs (#10)

Each ArbSide with non-null max_stake_dollars shows a 'max $X' chip
next to its price. When the user's stake input exceeds the opportunity-
level max_total_stake_dollars, a 'Fillable up to $X at displayed price'
caption appears below the row. Sportsbook legs (null depth) stay clean.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification — manual end-to-end

After all tasks complete:

- [ ] `.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py` — should report all-pass (only the same pre-existing failures excluded).
- [ ] Restart server. Confirm `/tmp/uvicorn.log` shows the new `kalshi_orderbook_poll` job scheduled (when in LIVE mode + auth configured).
- [ ] Hit `curl -s "http://127.0.0.1:8000/api/arbitrage?books=kalshi,polymarket,draftkings,fanduel,pinnacle" | python3 -m json.tool | head -50` — confirm the response includes `max_stake_dollars` per side (non-null on kalshi/polymarket legs after WS messages have flowed for a few minutes) and `max_total_stake_dollars` on opportunities.
- [ ] Browser smoke-test `/edges?type=arb`. Cross-venue arbs show the chip + caption when applicable.

---

## Deferred follow-ups (intentionally out of scope)

- "Cross-venue only" filter chip on `/edges` (a separate UI task).
- Bid-side depth.
- EV / low-hold scanner depth awareness.
- Polymarket size staleness mitigation (explicit re-`book` trigger).
- Kalshi `liquidity` field as a secondary coarse depth signal.
- True orderbook walk (filling beyond top-of-book at degraded prices).
