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

WS messages carry yes_ask / yes_bid and their sizes, which price both
sides: YES at yes_ask, NO at 1 - yes_bid (see quote_depth). Both sides'
rows update in real time and carry `max_stake_dollars`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterable

from ...cache import OddsCache
from .normalizer import yes_to_american
from .quote_depth import ask_dollars, max_stake_from_quote


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
        # `ws_side` is "yes" (priced from yes_ask) or "no" (from 1 - yes_bid)
        self._templates: dict[str, list[tuple[dict, str]]] = {}
        # Per-ticker last-WS-update wall clock (observability).
        self.last_ws_update: dict[str, float] = {}
        # Stats for /api/kalshi/status
        self.updates_total: int = 0
        self.unknown_market_msgs: int = 0
        self.last_update_at: float | None = None
        self.registered_markets: int = 0
        # Registration scopes. Each REST cycle registers the full current
        # market set for one (sport_key, series_ticker); `replace_scope`
        # uses these maps to drop tickers that disappeared from that
        # scope without touching other scopes' registrations. Without
        # this, tickers only ever accumulated (finished games kept being
        # WS-tracked for days).
        self._scope_tickers: dict[tuple, set[str]] = {}
        self._ticker_scopes: dict[str, set[tuple]] = {}
        self.pruned_total: int = 0
        self.last_prune_at: float | None = None

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

    def replace_scope(self, scope: tuple, rows: Iterable[dict]) -> int:
        """Register `rows` as the COMPLETE current set of markets for
        `scope` (the fetcher uses ``(sport_key, series_ticker)``).

        Tickers that this scope registered on a previous cycle but that
        are absent now are released; a ticker is dropped from the
        template map (and `last_ws_update`) only once no scope owns it.
        Tickers registered via plain `register_rows` (no scope) are
        never pruned here. Returns count of rows registered.
        """
        rows = list(rows)
        new_tickers = {r.get("_market_ticker") for r in rows if r.get("_market_ticker")}
        old_tickers = self._scope_tickers.get(scope, set())
        for mt in old_tickers - new_tickers:
            owners = self._ticker_scopes.get(mt)
            if owners is not None:
                owners.discard(scope)
                if not owners:
                    self._ticker_scopes.pop(mt, None)
                    self._drop_ticker(mt)
        # Fresh templates for surviving tickers: drop their old template
        # list first so outcomes the book no longer offers on that ticker
        # don't linger either.
        for mt in new_tickers:
            owners = self._ticker_scopes.setdefault(mt, set())
            if owners <= {scope}:
                self._templates.pop(mt, None)
            owners.add(scope)
        if new_tickers:
            self._scope_tickers[scope] = new_tickers
        else:
            self._scope_tickers.pop(scope, None)
        return self.register_rows(rows)

    def prune_started(self, now: datetime | None = None) -> int:
        """Drop every ticker whose templates are all for games that have
        already started (commence_time <= now). Mirrors the fetcher's
        `purge_live_rows_for_book("kalshi", now)` (grace 0) so WS ticks
        stop re-upserting rows that purge deletes
        anyway. Templates with an unparseable commence_time are kept.
        Returns count of tickers dropped."""
        now = now or datetime.now(timezone.utc)
        dropped = 0
        for mt, templates in list(self._templates.items()):
            if templates and all(
                _has_started(t.get("commence_time"), now) for t, _ in templates
            ):
                self._drop_ticker(mt)
                for scope in self._ticker_scopes.pop(mt, set()):
                    owned = self._scope_tickers.get(scope)
                    if owned is not None:
                        owned.discard(mt)
                        if not owned:
                            self._scope_tickers.pop(scope, None)
                dropped += 1
        return dropped

    def _drop_ticker(self, mt: str) -> None:
        if self._templates.pop(mt, None) is not None:
            self.pruned_total += 1
            self.last_prune_at = time.time()
        self.last_ws_update.pop(mt, None)
        self.registered_markets = len(self._templates)

    # ────────────────────── WS message processing ─────────────────────

    def process_ticker(self, msg: dict) -> int:
        """Handle one `type=ticker` message. Returns the number of rows
        upserted (0 if market_ticker is unknown to us — a ticker pruned since
        the subscription last synced)."""
        body = msg.get("msg") or {}
        market_ticker = body.get("market_ticker")
        if not market_ticker:
            return 0
        templates = self._templates.get(market_ticker)
        if not templates:
            # Pruned since the last subscription sync
            self.unknown_market_msgs += 1
            return 0

        # Both sides price off one ticker message: YES at yes_ask, NO at
        # 1 - yes_bid (hitting the best YES bid), each with its top-of-book
        # size -> max_stake_dollars. A side with no ask keeps its last row.
        prices: dict[str, int | None] = {}
        for side in ("yes", "no"):
            ask = ask_dollars(body, side=side)
            prices[side] = yes_to_american(ask) if ask is not None else None
        if prices["yes"] is None and prices["no"] is None:
            return 0

        # Use the WS server's timestamp when available — it's authoritative
        # for ordering line moves. Fall back to wall clock.
        fetched_at = _parse_ws_timestamp(body) or datetime.now(timezone.utc)

        rows_to_upsert: list[dict] = []
        for template, side in templates:
            price = prices.get(side)
            if price is None:
                continue
            new_row = {
                **template,
                "price_american": int(price),
                "fetched_at": fetched_at,
            }
            stake = max_stake_from_quote(body, side=side)
            if stake is not None:
                new_row["max_stake_dollars"] = stake
            rows_to_upsert.append(new_row)

        if not rows_to_upsert:
            return 0

        try:
            self.cache.upsert_nowait(rows_to_upsert, label=f"kalshi WS {market_ticker}")
        except Exception:
            logger.exception("kalshi WS: upsert failed for %s", market_ticker)
            return 0

        self.updates_total += len(rows_to_upsert)
        now = time.time()
        self.last_update_at = now
        self.last_ws_update[market_ticker] = now
        return len(rows_to_upsert)

    def registered_tickers(self) -> list[str]:
        """Public accessor — list of market_tickers currently in the
        template map. The WS client subscribes to exactly this set."""
        return list(self._templates.keys())

    # ────────────────────── Status / observability ────────────────────

    def stats(self) -> dict:
        """Read-only size counters for debug endpoints."""
        return {
            "templates_tickers": len(self._templates),
            "template_rows": sum(len(v) for v in self._templates.values()),
            "last_ws_update_entries": len(self.last_ws_update),
            "scopes": len(self._scope_tickers),
            "pruned_total": self.pruned_total,
            "last_prune_at": self.last_prune_at,
        }

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


def _has_started(commence, now: datetime) -> bool:
    """True when `commence` (datetime or ISO string) is <= now. Unknown /
    unparseable values count as NOT started so we never over-prune."""
    if commence is None:
        return False
    if isinstance(commence, str):
        try:
            commence = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(commence, datetime):
        return False
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    return commence <= now


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
