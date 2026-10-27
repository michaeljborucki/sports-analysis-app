"""Polymarket US market-data WebSocket (wss://api.polymarket.us/v1/ws/markets).

Auth is an Ed25519-signed handshake: headers X-PM-Access-Key, X-PM-Timestamp
(ms) and X-PM-Signature = base64(sign(timestamp + "GET" + path)). This module
signs exactly that one message for exactly this one path — it has no way to
reach order/portfolio/account endpoints, even though the key could.

Subscriptions are capped at 100 market slugs each, so the current slug set is
sent in chunks — and a connection accepts only ~10 subscribe requests
("max subscriptions per connection reached"; undocumented, observed
2026-10-23), so PolymarketUSWSPool shards slugs across connections of
<=1000 markets each. New slugs (a REST cycle discovered games / props) are added
with extra subscribe messages on the live connection — no reconnect. Slugs
that disappear are left subscribed (their messages no longer match a
template and are ignored); once more than half the subscribed set is dead the
connection is recycled so it doesn't keep streaming finished games.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import json
import logging
import os
import random
import time
from typing import Awaitable, Callable

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


logger = logging.getLogger(__name__)

WS_BASE = "wss://api.polymarket.us"
WS_PATH = "/v1/ws/markets"
MAX_SLUGS_PER_SUB = 100
MAX_SUBS_PER_CONN = 10
SLUGS_PER_CONN = MAX_SUBS_PER_CONN * MAX_SLUGS_PER_SUB
MAX_CONNECTIONS = int(os.environ.get("POLYMARKET_US_WS_MAX_CONNECTIONS", "25"))
_REBALANCE_INTERVAL_S = 5.0
_SYNC_INTERVAL_S = 10.0
_BACKOFF_STEPS = (1, 2, 5, 10, 30, 60)


def load_signing_key(secret_b64: str) -> Ed25519PrivateKey:
    """Polymarket US secrets are base64 Ed25519 keys: a 32-byte seed or a
    64-byte seed+public key (use the seed). Padding may be stripped."""
    raw = base64.b64decode(secret_b64 + "=" * (-len(secret_b64) % 4))
    if len(raw) not in (32, 64):
        raise ValueError(f"unexpected Polymarket US secret length {len(raw)}")
    return Ed25519PrivateKey.from_private_bytes(raw[:32])


def handshake_headers(key_id: str, signing_key: Ed25519PrivateKey,
                      now_ms: int | None = None) -> dict[str, str]:
    ts = str(int(time.time() * 1000) if now_ms is None else now_ms)
    sig = signing_key.sign(f"{ts}GET{WS_PATH}".encode())
    return {
        "X-PM-Access-Key": key_id,
        "X-PM-Timestamp": ts,
        "X-PM-Signature": base64.b64encode(sig).decode(),
    }


class PolymarketUSWSClient:
    def __init__(
        self,
        key_id: str,
        secret_key: str,
        get_slugs: Callable[[], set[str]],
        on_market_data: Callable[[dict], Awaitable[None] | None],
        name: str = "polymarket_us WS",
    ):
        self._key_id = key_id
        self._signing_key = load_signing_key(secret_key)
        self._get_slugs = get_slugs
        self._on_market_data = on_market_data
        self._name = name
        self._stop = False
        self._ws = None
        self._subscribed: set[str] = set()
        self._subs_used = 0
        self._next_req = 0
        self.connected_at: float | None = None
        self.last_message_at: float | None = None
        self.total_messages = 0
        self.total_reconnects = 0
        self.total_errors = 0
        self.last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self.connected_at is not None

    def stop(self) -> None:
        self._stop = True
        ws = self._ws
        if ws is not None:
            asyncio.ensure_future(ws.close())

    def stats(self) -> dict:
        return {
            "connected": self.is_connected,
            "subscribed_markets": len(self._subscribed),
            "total_messages": self.total_messages,
            "total_reconnects": self.total_reconnects,
            "total_errors": self.total_errors,
            "last_error": self.last_error,
            "last_message_at": self.last_message_at,
        }

    async def _subscribe(self, ws, slugs: list[str]) -> None:
        for i in range(0, len(slugs), MAX_SLUGS_PER_SUB):
            chunk = slugs[i:i + MAX_SLUGS_PER_SUB]
            self._next_req += 1
            self._subs_used += 1
            await ws.send(json.dumps({"subscribe": {
                "requestId": f"md-{self._next_req}",
                "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
                "marketSlugs": chunk,
                "responsesDebounced": True,
            }}))
            self._subscribed.update(chunk)

    async def _sync_loop(self, ws) -> None:
        """Subscribe newly registered slugs; recycle when mostly dead."""
        while True:
            await asyncio.sleep(_SYNC_INTERVAL_S)
            current = self._get_slugs()
            new = sorted(current - self._subscribed)
            needed = -(-len(new) // MAX_SLUGS_PER_SUB)
            if new and self._subs_used + needed > MAX_SUBS_PER_CONN:
                # Out of subscribe requests: reconnect and resubscribe compactly.
                logger.info("%s: +%d markets needs a fresh connection; recycling",
                            self._name, len(new))
                await ws.close()
                return
            if new:
                await self._subscribe(ws, new)
                logger.info("%s: +%d markets (now %d)",
                            self._name, len(new), len(self._subscribed))
            dead = len(self._subscribed - current)
            if len(self._subscribed) > 200 and dead * 2 > len(self._subscribed):
                logger.info("%s: %d/%d subscribed markets gone; recycling",
                            self._name, dead, len(self._subscribed))
                await ws.close()
                return

    async def run(self) -> None:
        backoff = 0
        while not self._stop:
            sync_task = None
            try:
                slugs = sorted(self._get_slugs())
                if not slugs:
                    await asyncio.sleep(5)
                    continue
                headers = handshake_headers(self._key_id, self._signing_key)
                async with websockets.connect(
                    WS_BASE + WS_PATH, additional_headers=headers,
                    max_size=None, ping_interval=20, ping_timeout=20,
                    # No permessage-deflate: inflating ~200 msg/s across 16
                    # sockets on the event loop was the #2 loop-stall site
                    # (2026-10-24). Bandwidth is not the constraint here.
                    compression=None,
                ) as ws:
                    self._ws = ws
                    self.connected_at = time.time()
                    self._subscribed = set()
                    self._subs_used = 0
                    await self._subscribe(ws, slugs)
                    logger.info("%s: connected, %d markets", self._name, len(slugs))
                    sync_task = asyncio.create_task(self._sync_loop(ws))
                    async for raw in ws:
                        self.last_message_at = time.time()
                        self.total_messages += 1
                        backoff = 0
                        try:
                            msg = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        if "marketData" in msg:
                            res = self._on_market_data(msg["marketData"])
                            if asyncio.iscoroutine(res):
                                await res
                        elif "error" in msg:
                            self.total_errors += 1
                            self.last_error = str(msg.get("error"))[:200]
                            logger.warning("%s error: %s", self._name, self.last_error)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # handshake rejection, network, protocol
                self.total_errors += 1
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                logger.warning("%s: %s", self._name, self.last_error)
            finally:
                if sync_task is not None:
                    sync_task.cancel()
                self._ws = None
                self.connected_at = None
            if self._stop:
                break
            self.total_reconnects += 1
            delay = _BACKOFF_STEPS[min(backoff, len(_BACKOFF_STEPS) - 1)]
            backoff += 1
            await asyncio.sleep(delay * (0.5 + random.random()))


class PolymarketUSWSPool:
    """Shards the registered slugs across PolymarketUSWSClient connections of
    at most SLUGS_PER_CONN markets each (sticky assignment, so a slug stays
    on its connection). Beyond MAX_CONNECTIONS the remainder is left
    unstreamed (REST-refreshed) and counted in `unstreamed`."""

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        get_slugs: Callable[[], set[str]],
        on_market_data: Callable[[dict], Awaitable[None] | None],
        max_connections: int = MAX_CONNECTIONS,
    ):
        load_signing_key(secret_key)   # fail fast on a malformed secret
        self._key_id, self._secret_key = key_id, secret_key
        self._get_slugs = get_slugs
        self._on_market_data = on_market_data
        self._max = max(1, max_connections)
        self._assign: dict[str, int] = {}
        self._shard_slugs: list[set[str]] = []
        self._clients: list[PolymarketUSWSClient] = []
        self._tasks: list[asyncio.Task] = []
        self._stop = False
        self.unstreamed = 0

    def _rebalance(self) -> None:
        current = self._get_slugs()
        self._assign = {s: k for s, k in self._assign.items() if s in current}
        counts = collections.Counter(self._assign.values())
        shard = overflow = 0
        for slug in sorted(current - self._assign.keys()):
            while shard < self._max and counts[shard] >= SLUGS_PER_CONN:
                shard += 1
            if shard >= self._max:
                overflow += 1
                continue
            self._assign[slug] = shard
            counts[shard] += 1
        self.unstreamed = overflow
        n = max(counts, default=-1) + 1
        shards: list[set[str]] = [set() for _ in range(max(n, len(self._clients)))]
        for slug, k in self._assign.items():
            shards[k].add(slug)
        self._shard_slugs = shards
        if overflow:
            logger.warning("polymarket_us WS: %d markets over the %d-connection cap stay REST-only",
                           overflow, self._max)

    def _spawn(self) -> None:
        while len(self._clients) < len(self._shard_slugs):
            i = len(self._clients)
            client = PolymarketUSWSClient(
                self._key_id, self._secret_key,
                get_slugs=lambda i=i: self._shard_slugs[i] if i < len(self._shard_slugs) else set(),
                on_market_data=self._on_market_data,
                name=f"polymarket_us WS[{i}]",
            )
            self._clients.append(client)
            self._tasks.append(asyncio.create_task(client.run()))

    async def run(self) -> None:
        try:
            while not self._stop:
                self._rebalance()
                self._spawn()
                await asyncio.sleep(_REBALANCE_INTERVAL_S)
        finally:
            for c in self._clients:
                c.stop()
            for t in self._tasks:
                t.cancel()
            self._clients, self._tasks = [], []

    def stop(self) -> None:
        self._stop = True
        for c in self._clients:
            c.stop()

    @property
    def is_connected(self) -> bool:
        active = [c for i, c in enumerate(self._clients)
                  if i < len(self._shard_slugs) and self._shard_slugs[i]]
        return bool(active) and all(c.is_connected for c in active)

    @property
    def last_message_at(self) -> float | None:
        """Oldest per-connection last message, so one stalled shard counts."""
        active = [c for i, c in enumerate(self._clients)
                  if i < len(self._shard_slugs) and self._shard_slugs[i]]
        if not active or any(c.last_message_at is None for c in active):
            return None
        return min(c.last_message_at for c in active)

    def stats(self) -> dict:
        per = [c.stats() for c in self._clients]
        return {
            "connections": len(per),
            "connected": sum(1 for p in per if p["connected"]),
            "subscribed_markets": sum(p["subscribed_markets"] for p in per),
            "unstreamed_markets": self.unstreamed,
            "total_messages": sum(p["total_messages"] for p in per),
            "total_reconnects": sum(p["total_reconnects"] for p in per),
            "total_errors": sum(p["total_errors"] for p in per),
            "last_errors": sorted({p["last_error"] for p in per if p["last_error"]}),
            "last_message_at": self.last_message_at,
        }
