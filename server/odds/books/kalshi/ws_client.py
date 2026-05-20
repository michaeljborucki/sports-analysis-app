"""Kalshi WebSocket client — authenticated ticker stream.

Replaces REST polling for live price updates. One persistent connection
receives every market's price changes in real-time. Drops staleness from
15-50s (REST cycle) to <1s (push latency).

Connection lifecycle:
  1. RSA-PSS sign the handshake (same scheme as REST authenticated reads)
  2. Send subscribe message to "ticker" channel — single subscription
     covers ALL markets (no per-ticker enumeration needed)
  3. Yield parsed messages from the stream
  4. On disconnect, reconnect with exponential backoff (1s, 2s, 4s, 8s,
     capped at 30s, with full jitter)

Message types observed:
  - "subscribed" / "error"     — handshake lifecycle
  - "ticker"                   — price update per market (~30 msg/s observed)

Ticker message shape:
  {
    "type": "ticker",
    "sid": <subscription id>,
    "msg": {
      "market_ticker": "KXMLBGAME-...-CHC",
      "yes_bid_dollars": "0.6100",
      "yes_ask_dollars": "0.6200",
      "price_dollars": "0.6150",        # last traded
      "ts_ms": 1779294595165,
      ...
    }
  }

Critical: ticker messages do NOT include no_ask_dollars. NO-side pricing
for spread/total/team_total markets still requires REST polling. WS
covers the YES side only — which is fully sufficient for h2h moneylines
(the main staleness pain point).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import time
from pathlib import Path
from typing import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException


logger = logging.getLogger(__name__)


# Production WebSocket URL. The newer external-api-ws.kalshi.com host
# also works but the legacy api.elections.kalshi.com URL is more battle-
# tested and matches our REST base.
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

# The path embedded in the WS auth signature. Kalshi expects the full
# canonical path including the /trade-api/v2 prefix (per REST convention).
_WS_SIG_PATH = "/trade-api/ws/v2"

# Reconnect backoff schedule (seconds). Caps at 30s — long enough to avoid
# hammering during a Kalshi outage, short enough to recover quickly when
# the issue is transient.
_BACKOFF_STEPS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

# How long to wait for the subscribe ack before assuming the channel is
# unavailable. The ack arrives within ~200ms in practice; 10s is generous.
_SUBSCRIBE_ACK_TIMEOUT_S = 10.0

# Ping interval — keeps the connection alive across NAT timeouts. The
# `websockets` library handles pong responses automatically.
_PING_INTERVAL_S = 30.0
_PING_TIMEOUT_S = 10.0


class KalshiWSError(Exception):
    pass


class KalshiWSClient:
    """Persistent WebSocket consumer for Kalshi ticker updates.

    Usage (async iterator pattern):
        client = KalshiWSClient(api_key, private_key_path)
        async for msg in client.ticker_messages():
            # msg is a parsed dict with type="ticker"
            ...

    The async iterator auto-reconnects on disconnect — callers don't
    need to wrap in try/except for transient failures. Only `stop()`
    or a non-recoverable auth error terminates the iteration.
    """

    def __init__(
        self,
        api_key: str,
        private_key_path: Path,
        url: str = WS_URL,
    ):
        if not api_key:
            raise KalshiWSError("kalshi WS: api_key required")
        if not private_key_path:
            raise KalshiWSError("kalshi WS: private_key_path required")
        self.api_key = api_key
        self.private_key_path = private_key_path
        self.url = url
        self._private_key = None
        self._stop = False
        # Telemetry — useful for /api/kalshi/status reporting and debugging
        self.connected_at: float | None = None
        self.last_message_at: float | None = None
        self.total_messages: int = 0
        self.total_reconnects: int = 0

    @property
    def is_connected(self) -> bool:
        # Approximate — we can't see the underlying socket from here, but
        # if connected_at is set and the iterator hasn't bailed, we're live.
        return self.connected_at is not None

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key
        from cryptography.hazmat.primitives import serialization
        data = self.private_key_path.read_bytes()
        self._private_key = serialization.load_pem_private_key(data, password=None)
        return self._private_key

    def _build_handshake_headers(self) -> dict[str, str]:
        """Same RSA-PSS signing scheme as REST. The signed payload is
        `timestamp + method + path` where method is GET (WS upgrade is a
        GET-with-Upgrade-header) and path is the canonical /trade-api/ws/v2."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        pk = self._load_private_key()
        ts = str(int(time.time() * 1000))
        payload = (ts + "GET" + _WS_SIG_PATH).encode()
        sig = pk.sign(
            payload,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def stop(self) -> None:
        """Request graceful shutdown. The async iterator exits at the next
        message boundary or reconnect attempt."""
        self._stop = True

    async def ticker_messages(self) -> AsyncIterator[dict]:
        """Async iterator yielding parsed ticker messages. Handles
        connect / subscribe / reconnect transparently. Non-recoverable
        errors (bad credentials, persistent rejection) raise KalshiWSError.

        Yields only `type == "ticker"` messages — drops lifecycle messages
        (subscribed, error, etc.) after logging. This keeps the caller's
        loop simple.
        """
        backoff_idx = 0
        while not self._stop:
            try:
                async for msg in self._connect_and_stream():
                    self.last_message_at = time.time()
                    self.total_messages += 1
                    yield msg
                    # Reset backoff on successful message — connection is healthy
                    backoff_idx = 0
                # _connect_and_stream returns normally only on graceful close;
                # that's typically a server-side disconnect → reconnect.
                if self._stop:
                    break
                logger.info("kalshi WS: connection closed normally; reconnecting")
            except KalshiWSError:
                # Auth-level errors aren't recoverable; surface to caller.
                raise
            except (ConnectionClosed, WebSocketException, asyncio.TimeoutError) as e:
                if self._stop:
                    break
                logger.warning("kalshi WS: connection error: %s", e)
            except Exception:
                if self._stop:
                    break
                logger.exception("kalshi WS: unexpected error")

            # Backoff before reconnecting
            self.total_reconnects += 1
            self.connected_at = None
            delay = _BACKOFF_STEPS[min(backoff_idx, len(_BACKOFF_STEPS) - 1)]
            delay = delay * (0.5 + random.random())  # full jitter
            logger.info("kalshi WS: reconnecting in %.1fs", delay)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                self._stop = True
                break
            backoff_idx += 1

    async def _connect_and_stream(self) -> AsyncIterator[dict]:
        """Single-attempt connect + subscribe + yield. Caller wraps in
        a reconnect loop. Raises on auth or subscribe failure; returns
        normally on connection close."""
        headers = self._build_handshake_headers()
        async with websockets.connect(
            self.url,
            additional_headers=headers,
            ping_interval=_PING_INTERVAL_S,
            ping_timeout=_PING_TIMEOUT_S,
            max_size=2**20,  # 1 MiB — generous for batched ticker messages
        ) as ws:
            self.connected_at = time.time()
            logger.info("kalshi WS: connected")

            # Subscribe to the ticker channel. One subscription covers
            # every market on the platform; we filter in the ingestor.
            sub_msg = {
                "id": 1,
                "cmd": "subscribe",
                "params": {"channels": ["ticker"]},
            }
            await ws.send(json.dumps(sub_msg))

            # Wait for the subscribe ack to confirm we're live
            try:
                async with asyncio.timeout(_SUBSCRIBE_ACK_TIMEOUT_S):
                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        if msg.get("type") == "subscribed":
                            logger.info(
                                "kalshi WS: subscribed sid=%s",
                                msg.get("msg", {}).get("sid"),
                            )
                            break
                        if msg.get("type") == "error":
                            raise KalshiWSError(
                                f"kalshi WS subscribe failed: {msg.get('msg')}"
                            )
                        # Tickers might arrive before the ack lands; pass them
                        # through to the caller too.
                        if msg.get("type") == "ticker":
                            yield msg
            except asyncio.TimeoutError as e:
                raise KalshiWSError(
                    "kalshi WS: subscribe ack timeout"
                ) from e

            # Main stream loop — yield ticker messages, drop everything else
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("kalshi WS: non-JSON message dropped")
                    continue
                t = msg.get("type")
                if t == "ticker":
                    yield msg
                elif t == "error":
                    logger.warning("kalshi WS error msg: %s", msg.get("msg"))
                # Drop "subscribed" duplicates and any other lifecycle msgs

    def status(self) -> dict:
        """Snapshot for /api/kalshi/status. Mirrors the existing fetcher
        status shape — adds WS-specific health fields."""
        now = time.time()
        return {
            "ws_connected": self.is_connected,
            "ws_total_messages": self.total_messages,
            "ws_total_reconnects": self.total_reconnects,
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
