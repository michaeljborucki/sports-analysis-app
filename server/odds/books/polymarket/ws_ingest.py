"""WebSocket message → cache-row ingestor.

Bridges Polymarket's streaming `book` / `price_change` messages to our
`odds_snapshot` table. The REST normalizer remains the source of truth
for market metadata (event_id, market_key, outcome_name, etc.); the
ingestor caches one cache-row template per asset_id and updates the
price field when WS messages arrive.

Lifecycle per market:
  1. REST cycle fetches Gamma events → emits 2 cache rows per market
  2. PolymarketIngestor.register_rows(rows) caches each row by asset_id
  3. WebSocket connects, subscribes to all known asset_ids
  4. `book` event arrives (one-time snapshot) → update row from best ask
  5. `price_change` events arrive → update row from each delta's best_ask

Differences from KalshiTickerIngestor:
  - Lookup key is `asset_id`, not `market_ticker`
  - Each template = ONE row (not a list) because each asset_id IS a
    side. There's no "yes/no" distinction at the asset level on
    Polymarket (each YES contract on each outcome is its own asset).
  - Price source is `best_ask` from the orderbook (book.asks[0].price
    for snapshots; price_change[i].best_ask for deltas). We use ASK
    because that's the price you'd pay to BUY — same convention as
    Kalshi's yes_ask_dollars.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterable

from ...cache import OddsCache
from .normalizer import yes_to_american


logger = logging.getLogger(__name__)


# Fields the WS path adds to row dicts but the cache doesn't store. The
# extras pass through `cache.upsert` harmlessly (named-param SQL ignores
# extras), but we strip them on registration to keep templates tidy.
_INTERNAL_ROW_FIELDS = ("_asset_id", "_ws_side", "price_american", "fetched_at")


class PolymarketIngestor:
    """Maintains an asset_id → cache_row_template map populated by REST
    cycles; updates the cache when WS messages arrive.

    Thread-safety: registration and processing are called from the same
    asyncio loop (no concurrent access), so no locking needed.
    """

    def __init__(self, cache: OddsCache):
        self.cache = cache
        # asset_id → template dict (without price / fetched_at)
        self._templates: dict[str, dict] = {}
        # Stats for /api/polymarket/status
        self.updates_total: int = 0
        self.unknown_asset_msgs: int = 0
        self.last_update_at: float | None = None
        self.registered_assets: int = 0

    # ────────────────────── Registration ──────────────────────────────

    def asset_ids(self) -> list[str]:
        """All currently-registered asset_ids — handed to the WS client
        on each (re)connect so subscriptions include every active game."""
        return list(self._templates.keys())

    def register_rows(self, rows: Iterable[dict]) -> int:
        """Cache each row by its source asset_id. Idempotent — re-registering
        the same asset_id replaces the previous template (which is correct:
        market metadata may have refreshed on the latest REST cycle, e.g.
        an updated commence_time after a rescheduling).

        Expects rows produced by `normalize_h2h_market` with the additional
        `_asset_id` and `_ws_side` metadata fields.

        Returns count of rows registered.
        """
        registered = 0
        for row in rows:
            asset_id = row.get("_asset_id")
            if not asset_id:
                continue
            self._templates[str(asset_id)] = _clean_row(row)
            registered += 1
        self.registered_assets = len(self._templates)
        return registered

    # ────────────────────── WS message processing ─────────────────────

    def process_message(self, msg: dict) -> int:
        """Handle one `book` or `price_change` message. Returns the number
        of rows upserted (0 if asset_id is unknown — typical, since
        Polymarket streams every subscribed asset and we filter to only
        those we registered)."""
        et = msg.get("event_type")
        if et == "book":
            return self._process_book(msg)
        if et == "price_change":
            return self._process_price_change(msg)
        return 0

    def _process_book(self, msg: dict) -> int:
        """Initial orderbook snapshot. Polymarket sorts `asks` DESCENDING
        by price (worst offer first; verified live 2026-05-12). So the
        BEST ask (cheapest YES contract — the price we'd pay to buy) is
        at `asks[-1]`, NOT `asks[0]`.

        Implementation: compute min(asks.price) instead of trusting array
        order. That's defensive — if Polymarket ever changes ordering,
        we still pick the right number. One row updated per book event.
        """
        asset_id = msg.get("asset_id")
        if not asset_id:
            return 0
        template = self._templates.get(asset_id)
        if template is None:
            self.unknown_asset_msgs += 1
            return 0

        asks = msg.get("asks") or []
        if not asks:
            return 0
        # min(price) across all levels = best (cheapest) ask. Defensive
        # against array-ordering changes upstream.
        prices: list[float] = []
        for ask in asks:
            if not isinstance(ask, dict):
                continue
            try:
                prices.append(float(ask.get("price")))
            except (TypeError, ValueError):
                continue
        if not prices:
            return 0
        best_ask = min(prices)

        return self._upsert_with_price(template, best_ask, msg.get("timestamp"))

    def _process_price_change(self, msg: dict) -> int:
        """Delta. The message has an `asset_id` at the top level AND a
        `price_changes` array; each entry has its own `asset_id` (which
        in practice matches the top-level one) plus `best_bid` and
        `best_ask` fields. We use `best_ask` directly — same convention
        as the book snapshot.

        If the top-level asset_id isn't registered AND no entry in
        price_changes matches a registered asset, count as unknown and
        skip. Otherwise, update each registered asset's row from its
        matching entry's best_ask.
        """
        updated = 0
        changes = msg.get("price_changes") or []
        if not isinstance(changes, list):
            return 0

        # Some servers nest the asset_id only inside each change; others
        # repeat it at the top. Try both paths.
        top_asset = msg.get("asset_id")
        timestamp = msg.get("timestamp")

        for change in changes:
            if not isinstance(change, dict):
                continue
            asset_id = change.get("asset_id") or top_asset
            if not asset_id:
                continue
            template = self._templates.get(asset_id)
            if template is None:
                self.unknown_asset_msgs += 1
                continue
            ba = change.get("best_ask")
            if ba is None:
                # Fallback: use price (the level that moved) — less ideal
                # because it could be a non-top-of-book level, but on a
                # tight market the difference is single-cent.
                ba = change.get("price")
            try:
                best_ask = float(ba)
            except (TypeError, ValueError):
                continue
            n = self._upsert_with_price(template, best_ask, timestamp)
            updated += n
        return updated

    def _upsert_with_price(
        self, template: dict, best_ask: float, timestamp,
    ) -> int:
        """Convert best_ask (decimal probability 0..1) to American odds,
        stamp fetched_at (prefer WS-server timestamp, fallback wall clock),
        and upsert. Returns 1 on success, 0 on filter rejection / DB error.
        """
        american = yes_to_american(best_ask)
        if american is None:
            return 0
        fetched_at = _parse_ws_timestamp(timestamp) or datetime.now(timezone.utc)
        new_row = {
            **template,
            "price_american": int(american),
            "fetched_at": fetched_at,
        }
        try:
            self.cache.upsert([new_row])
        except Exception:
            logger.exception(
                "polymarket WS: upsert failed for event %s outcome %s",
                template.get("event_id"), template.get("outcome_name"),
            )
            return 0
        self.updates_total += 1
        self.last_update_at = time.time()
        return 1

    # ────────────────────── Status / observability ────────────────────

    def status(self) -> dict:
        now = time.time()
        return {
            "ws_registered_assets": self.registered_assets,
            "ws_updates_total": self.updates_total,
            "ws_unknown_msgs": self.unknown_asset_msgs,
            "ws_last_update_age_s": (
                round(now - self.last_update_at, 1)
                if self.last_update_at is not None
                else None
            ),
        }


# ────────────────────────── Helpers ───────────────────────────────────


def _clean_row(row: dict) -> dict:
    """Return a copy of `row` without WS-internal metadata and without the
    per-tick price/fetched_at (those get re-injected per WS message)."""
    return {k: v for k, v in row.items() if k not in _INTERNAL_ROW_FIELDS}


def _parse_ws_timestamp(ts) -> datetime | None:
    """Polymarket's `timestamp` is a string of millisecond-epoch (e.g.
    "1779303544001"). Some shapes send it as an int. Both → UTC datetime.
    Returns None on missing / malformed."""
    if ts is None:
        return None
    try:
        ms = int(ts)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OSError, ValueError):
        return None
