"""WebSocket ticker → cache-row ingestor.

Bridges Kalshi's streaming `ticker` messages to our existing
`odds_snapshot` table. The REST normalizer remains the source of truth
for market metadata (event_id, market_key, outcome_name, etc.); the
ingestor caches one cache-row template per (market_ticker, side) and
updates the price field when WS messages arrive.

Lifecycle per market:
  1. REST snapshot fetches & normalizes the market → emits N cache rows
  2. KalshiTickerIngestor.register_rows(rows) caches each row by
     (market_ticker, ws_side) so the WS task can find it on each tick
  3. WebSocket message arrives → look up templates → mutate price +
     fetched_at → upsert to cache

WS messages carry YES-side prices only (no_ask_dollars is NOT in the
ticker payload — orderbook_delta carries that). So templates tagged
ws_side="no" don't get real-time updates and stay refreshed by the REST
safety-net cycle (every 60s).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterable

from ...cache import OddsCache
from .normalizer import yes_to_american


logger = logging.getLogger(__name__)


class KalshiTickerIngestor:
    """Maintains a market_ticker→cache_row_template map populated by
    REST snapshots; updates the cache when WS ticker messages arrive.

    Thread-safety: registration and processing are called from the same
    asyncio loop (no concurrent access), so no locking needed.
    """

    def __init__(self, cache: OddsCache):
        self.cache = cache
        # market_ticker → list[(template, ws_side)]
        # `template` is a cache-row dict missing only price_american + fetched_at
        # `ws_side` is "yes" (update from yes_ask) or "no" (no real-time path —
        # REST safety net keeps it fresh, but we still hold the row for
        # bookkeeping / debugging)
        self._templates: dict[str, list[tuple[dict, str]]] = {}
        # Stats for /api/kalshi/status
        self.updates_total: int = 0
        self.unknown_market_msgs: int = 0
        self.last_update_at: float | None = None
        self.registered_markets: int = 0

    # ────────────────────── Registration ──────────────────────────────

    def register_rows(self, rows: Iterable[dict]) -> int:
        """Cache each row by its source market_ticker so the WS task
        can update it on incoming ticker messages.

        Expects rows produced by `normalize_markets` with the additional
        `_market_ticker` and `_ws_side` metadata fields (stripped on cache
        upsert by `_clean_row`).

        Returns count of rows registered. Idempotent — re-registering
        the same (market_ticker, outcome_name, outcome_point, ws_side)
        replaces the previous template (which is correct because the
        market metadata is the latest known shape).
        """
        registered = 0
        for row in rows:
            mt = row.get("_market_ticker")
            side = row.get("_ws_side", "yes")
            if not mt:
                continue
            template = _clean_row(row)
            existing = self._templates.setdefault(mt, [])
            replaced = False
            key = (template.get("outcome_name"), template.get("outcome_point"), side)
            for i, (t, s) in enumerate(existing):
                if (t.get("outcome_name"), t.get("outcome_point"), s) == key:
                    existing[i] = (template, side)
                    replaced = True
                    break
            if not replaced:
                existing.append((template, side))
            registered += 1
        self.registered_markets = len(self._templates)
        return registered

    # ────────────────────── WS message processing ─────────────────────

    def process_ticker(self, msg: dict) -> int:
        """Handle one `type=ticker` message. Returns the number of rows
        upserted (0 if market_ticker is unknown to us — typical, since
        Kalshi streams every market on the platform but we only track
        sports markets we've registered)."""
        body = msg.get("msg") or {}
        market_ticker = body.get("market_ticker")
        if not market_ticker:
            return 0
        templates = self._templates.get(market_ticker)
        if not templates:
            # Unknown market — non-sports or sport we don't process yet
            self.unknown_market_msgs += 1
            return 0

        # Parse the YES-side price. WS ticker doesn't include no_ask, so
        # we can only update side='yes' templates. side='no' rows stay
        # at whatever REST last set; the 60s safety net catches drift.
        try:
            yes_ask = float(body["yes_ask_dollars"])
        except (KeyError, TypeError, ValueError):
            return 0
        new_price = yes_to_american(yes_ask)
        if new_price is None:
            return 0

        # Use the WS server's timestamp when available — it's authoritative
        # for ordering line moves. Fall back to wall clock.
        fetched_at = _parse_ws_timestamp(body) or datetime.now(timezone.utc)

        rows_to_upsert: list[dict] = []
        for template, side in templates:
            if side != "yes":
                continue
            new_row = {
                **template,
                "price_american": int(new_price),
                "fetched_at": fetched_at,
            }
            rows_to_upsert.append(new_row)

        if not rows_to_upsert:
            return 0

        try:
            self.cache.upsert(rows_to_upsert)
        except Exception:
            logger.exception("kalshi WS: upsert failed for %s", market_ticker)
            return 0

        self.updates_total += len(rows_to_upsert)
        self.last_update_at = time.time()
        return len(rows_to_upsert)

    # ────────────────────── Status / observability ────────────────────

    def status(self) -> dict:
        now = time.time()
        return {
            "ws_registered_markets": self.registered_markets,
            "ws_updates_total": self.updates_total,
            "ws_unknown_msgs": self.unknown_market_msgs,
            "ws_last_update_age_s": (
                round(now - self.last_update_at, 1)
                if self.last_update_at is not None
                else None
            ),
        }


# ────────────────────────── Helpers ───────────────────────────────────


# Fields the WS path adds to row dicts but the cache doesn't store. The
# extras pass through `cache.upsert` harmlessly (named-param SQL ignores
# extras) but we strip them on registration to keep templates tidy.
_INTERNAL_ROW_FIELDS = ("_market_ticker", "_ws_side", "price_american", "fetched_at")


def _clean_row(row: dict) -> dict:
    """Return a copy of `row` without the WS-internal metadata fields
    and without the per-tick price/fetched_at (those get re-injected
    per WS message)."""
    return {k: v for k, v in row.items() if k not in _INTERNAL_ROW_FIELDS}


def _parse_ws_timestamp(body: dict) -> datetime | None:
    """Pull the Kalshi-server timestamp from a ticker `msg` payload.
    Prefers `ts_ms` (ms epoch) → falls back to `ts` (s epoch) → ISO
    `time` string. Returns tz-aware UTC datetime or None."""
    ts_ms = body.get("ts_ms")
    if ts_ms is not None:
        try:
            return datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    ts_s = body.get("ts")
    if ts_s is not None:
        try:
            return datetime.fromtimestamp(int(ts_s), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    iso = body.get("time")
    if iso:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    return None
