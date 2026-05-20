"""Polymarket WebSocket client — public, no auth.

Subscribes to per-asset_id streams on the CLOB. One persistent connection
yields book snapshots + price_change deltas; the ingestor routes each
update to the matching cache-row template via asset_id.

URL: wss://ws-subscriptions-clob.polymarket.com/ws/market

Subscribe message:
  {
    "assets_ids": ["<id_1>", "<id_2>", ...],
    "type": "market",
    "initial_dump": true,
    "level": 2
  }

On `initial_dump: true` the server sends one `book` event per asset
(one-time orderbook snapshot), then streams `price_change` events on
every level change.

Heartbeat: send literal string "PING" (NOT JSON) every 10s. Server
replies with "PONG". If we don't ping, the server closes the connection
after ~30s of silence.

Message envelope: the server may return either a single object OR a
top-level LIST of objects. We always normalize to an iterable of dicts
before yielding.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import AsyncIterator, Iterable

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException


logger = logging.getLogger(__name__)


WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Reconnect backoff — same shape as Kalshi's. 30s ceiling avoids hammering
# during an extended outage; full jitter spreads reconnects across the
# fleet so we don't herd-thunder the server on recovery.
_BACKOFF_STEPS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

# Subscription resubscribe cap. We don't expect to need this — assets_ids
# is unbounded in practice — but keep the subscribe message under a
# safe-ish payload size (a few thousand IDs is fine).
_MAX_ASSETS_PER_SUB = 5000

# Polymarket heartbeat. Server expects "PING" as a literal text frame
# (NOT JSON-wrapped). Send every 10s.
_PING_INTERVAL_S = 10.0


class PolymarketWSError(Exception):
    pass


class PolymarketWSClient:
    """Persistent WebSocket consumer for Polymarket CLOB market events.

    Async-iterator pattern (mirrors `KalshiWSClient`):

        client = PolymarketWSClient(get_asset_ids=lambda: ingestor.asset_ids())
        async for msg in client.market_messages():
            ingestor.process_message(msg)

    `get_asset_ids` is a callable returning the CURRENT list of asset_ids
    to subscribe to. We invoke it on each connect — so a REST cycle that
    discovers new games and registers them with the ingestor will pick
    them up at the next reconnect (or after the resubscribe-on-stale
    mechanism kicks in, see below).

    `market_messages` yields parsed dicts (one per delta), normalized
    out of whatever envelope the server used (single object OR list).
    Connection lifecycle is fully handled internally — callers don't
    need to wrap in try/except for transient failures. Only `stop()`
    terminates the iteration.
    """

    def __init__(
        self,
        get_asset_ids: callable,
        url: str = WS_URL,
        ping_interval_s: float = _PING_INTERVAL_S,
    ):
        self._get_asset_ids = get_asset_ids
        self.url = url
        self._ping_interval_s = ping_interval_s
        self._stop = False
        # Telemetry — mirrors KalshiWSClient.status()
        self.connected_at: float | None = None
        self.last_message_at: float | None = None
        self.total_messages: int = 0
        self.total_reconnects: int = 0
        self.subscribed_assets: int = 0

    @property
    def is_connected(self) -> bool:
        return self.connected_at is not None

    def stop(self) -> None:
        """Request graceful shutdown. The async iterator exits at the
        next reconnect boundary; an in-flight `recv` will be cancelled
        when the task is cancelled."""
        self._stop = True

    async def market_messages(self) -> AsyncIterator[dict]:
        """Async iterator yielding parsed message dicts. Handles connect /
        subscribe / heartbeat / reconnect transparently.

        Yields each individual event-typed message; if the server batches
        them in a list, we flatten before yielding. Non-event messages
        (lifecycle, errors) are logged and dropped.
        """
        backoff_idx = 0
        while not self._stop:
            try:
                async for msg in self._connect_and_stream():
                    self.last_message_at = time.time()
                    self.total_messages += 1
                    yield msg
                    backoff_idx = 0  # success → reset backoff
                if self._stop:
                    break
                logger.info("polymarket WS: closed normally; reconnecting")
            except PolymarketWSError:
                # Non-recoverable (e.g. no assets to subscribe to + we want
                # to surface that to the caller for debugging). Pause and
                # retry — discovery may populate assets shortly.
                if self._stop:
                    break
                logger.warning(
                    "polymarket WS: no assets to subscribe — sleeping before retry",
                )
            except (ConnectionClosed, WebSocketException, asyncio.TimeoutError) as e:
                if self._stop:
                    break
                logger.warning("polymarket WS: connection error: %s", e)
            except Exception:
                if self._stop:
                    break
                logger.exception("polymarket WS: unexpected error")

            self.total_reconnects += 1
            self.connected_at = None
            delay = _BACKOFF_STEPS[min(backoff_idx, len(_BACKOFF_STEPS) - 1)]
            delay = delay * (0.5 + random.random())
            logger.info("polymarket WS: reconnecting in %.1fs", delay)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                self._stop = True
                break
            backoff_idx += 1

    async def _connect_and_stream(self) -> AsyncIterator[dict]:
        """Single-attempt connect + subscribe + yield. Caller wraps in
        the reconnect loop. Raises PolymarketWSError when the asset list
        is empty (rare — happens between fetcher startup and the first
        REST cycle); the caller backs off and retries.
        """
        assets = list(self._get_asset_ids() or ())
        if not assets:
            raise PolymarketWSError("polymarket WS: no assets registered yet")
        # Cap subscription size — but in practice the full Phase 1 set is
        # ~50 games × 2 outcomes = 100 asset_ids, far below the cap.
        if len(assets) > _MAX_ASSETS_PER_SUB:
            logger.warning(
                "polymarket WS: capping subscription at %d assets (had %d)",
                _MAX_ASSETS_PER_SUB, len(assets),
            )
            assets = assets[:_MAX_ASSETS_PER_SUB]

        async with websockets.connect(
            self.url,
            # We handle keepalive at the protocol level via PING strings;
            # disable the library's automatic ping/pong so it doesn't
            # send conflicting frames.
            ping_interval=None,
            ping_timeout=None,
            max_size=2**21,  # 2 MiB — generous for big book snapshots
            close_timeout=2.0,
        ) as ws:
            self.connected_at = time.time()
            self.subscribed_assets = len(assets)
            logger.info("polymarket WS: connected (%d assets)", len(assets))

            sub_msg = {
                "assets_ids":   assets,
                "type":         "market",
                "initial_dump": True,
                "level":        2,
            }
            await ws.send(json.dumps(sub_msg))

            # Heartbeat task — sends "PING" (literal text frame) on the
            # configured interval. Polymarket's server requires this every
            # ≤30s; we send every 10s for a healthy margin.
            ping_task = asyncio.create_task(self._heartbeat(ws))

            try:
                async for raw in ws:
                    if self._stop:
                        break
                    # The server sometimes sends literal "PONG" frames in
                    # response to our heartbeats — drop them.
                    if isinstance(raw, str) and raw.strip().upper() == "PONG":
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        # Unparseable text frame — log and skip.
                        logger.debug("polymarket WS: non-JSON frame: %r", raw[:120])
                        continue
                    for msg in _flatten_payload(payload):
                        if not isinstance(msg, dict):
                            continue
                        et = msg.get("event_type")
                        if et in ("book", "price_change"):
                            yield msg
                        elif et:
                            logger.debug(
                                "polymarket WS: dropping non-book event_type=%s", et,
                            )
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _heartbeat(self, ws) -> None:
        """Send "PING" every `_ping_interval_s`. Cancelled when the outer
        async-for loop exits."""
        try:
            while not self._stop:
                await asyncio.sleep(self._ping_interval_s)
                try:
                    await ws.send("PING")
                except (ConnectionClosed, WebSocketException):
                    return
        except asyncio.CancelledError:
            return

    def status(self) -> dict:
        """Snapshot for /api/polymarket/status. Same field names as
        KalshiWSClient.status() so a single UI component can display both."""
        now = time.time()
        return {
            "ws_connected": self.is_connected,
            "ws_total_messages": self.total_messages,
            "ws_total_reconnects": self.total_reconnects,
            "ws_subscribed_assets": self.subscribed_assets,
            "ws_last_message_age_s": (
                round(now - self.last_message_at, 1)
                if self.last_message_at is not None
                else None
            ),
            "ws_connected_age_s": (
                round(now - self.connected_at, 1)
                if self.connected_at is not None
                else None
            ),
        }


def _flatten_payload(payload) -> Iterable[dict]:
    """Polymarket's server returns either a single dict OR a top-level
    list of dicts (batched messages). Always emit a flat iterable."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return (payload,)
    return ()
