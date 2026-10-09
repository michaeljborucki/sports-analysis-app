"""Novig best-bid stream over the signed websocket (`/v3/ws`, `bbo` channel).

Replaces REST book polling for every market it holds a live snapshot of:
the subscribe reply carries each outcome's best resting bid + size at a
`seq`, and every later change arrives as a sequenced delta. That is exactly
the input `take_quotes` / `maker_quotes` consume (best bid and the total
size at it), so the fetcher rebuilds a one-level book from this state and
prices it with the same code the poller uses.

READ-ONLY: the connection only ever sends `subscribe`, `unsubscribe` and
`snapshot`. `_send` refuses every other method (the protocol also carries
`place` / `cancel`), whatever scope the key has.

Subscriptions are per EVENT (`event:<id>`): one request snapshots every
market of a game, and markets that open later arrive on it as deltas. The
stream bucket charges per market subscribed directly (measured 2026-10-09:
a 50-market subscribe was rate-limited, a 270-market event was not), so
per-market subscribes would take tens of minutes after every reconnect.
The watch cap still counts an event as all its markets, so events are taken
soonest-first until MAX_MARKETS; the rest stay on REST polling.

Freshness: a market counts as covered only while the socket is up and it
has a snapshot on this connection. A sequence gap drops it back to the
poller until a re-snapshot lands; a disconnect drops everything.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Callable

import websockets

from .client import BASE_URL, _Signer

logger = logging.getLogger(__name__)

WS_URL = BASE_URL.replace("https://", "wss://", 1) + "/v3/ws"
# Live account limit (GET /v3/limits, 2026-10-09): 2048 watched markets per
# connection. Stay under it; the rest stay on REST polling.
MAX_MARKETS = int(os.environ.get("NOVIG_WS_MAX_MARKETS", "2000"))
SYNC_INTERVAL_S = 5.0
CHUNK = 5                       # events per subscribe request
RATE_LIMIT_PAUSE_S = 15.0
_ALLOWED_METHODS = frozenset({"subscribe", "unsubscribe", "snapshot"})

Bbo = dict[str, tuple[float, int]]   # outcomeId -> (best bid price, qty)


class NovigBboStream:
    def __init__(
        self,
        signer: _Signer,
        desired: Callable[[], list[tuple[str, int]]],
        on_change: Callable[[str], None],
        on_lost: Callable[[set[str]], None],
        on_new_market: Callable[[str], None] | None = None,
    ):
        """`desired()` returns (event_id, open_market_count) in priority order
        (soonest first);
        `on_change(mid)` fires when a covered market's bbo moved;
        `on_lost(mids)` fires when markets stop being covered."""
        self._signer = signer
        self._desired = desired
        self._on_change = on_change
        self._on_lost = on_lost
        self._on_new_market = on_new_market
        self.state: dict[str, Bbo] = {}
        self._seq: dict[str, int] = {}
        self._live: set[str] = set()        # markets with a snapshot on this connection
        self._event_of: dict[str, str] = {} # market -> event (subscribed events only)
        self._subscribed: set[str] = set()  # events requested on this connection
        self._pending: dict[int, list[str]] = {}  # nonce -> events awaiting reply
        self._pause_until = 0.0
        self._ws = None
        self._nonce = 0
        self.connected = False
        self.updates = 0
        self.reconnects = 0
        self.gaps = 0
        self.last_message_at: float | None = None

    # ───────────────────────── public ─────────────────────────

    def covers(self, market_id: str) -> bool:
        return self.connected and market_id in self._live

    def live_ids(self) -> set[str]:
        return set(self._live) if self.connected else set()

    def stats(self) -> dict:
        return {
            "connected": self.connected,
            "markets_live": len(self._live) if self.connected else 0,
            "events_subscribed": len(self._subscribed),
            "updates": self.updates,
            "reconnects": self.reconnects,
            "seq_gaps": self.gaps,
            "last_message_age_s": (
                round(time.monotonic() - self.last_message_at, 1)
                if self.last_message_at is not None else None
            ),
        }

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._connect_once()
                backoff = 1.0
            except asyncio.CancelledError:
                self._drop_all()
                raise
            except Exception as e:
                logger.warning("novig ws: %s: %s", type(e).__name__, e)
            self._drop_all()
            self.reconnects += 1
            await asyncio.sleep(backoff + random.uniform(0, 1))
            backoff = min(backoff * 2, 60.0)

    # ───────────────────────── connection ─────────────────────────

    async def _connect_once(self) -> None:
        headers = self._signer.headers("GET", "/v3/ws", "")
        async with websockets.connect(
            WS_URL, additional_headers=headers,
            ping_interval=20, ping_timeout=20, max_size=2**24,
        ) as ws:
            self._ws = ws
            self.connected = True
            logger.info("novig ws: connected")
            sync = asyncio.create_task(self._sync_loop())
            try:
                async for raw in ws:
                    self.last_message_at = time.monotonic()
                    self._handle(json.loads(raw))
            finally:
                sync.cancel()
                self._ws = None

    def _drop_all(self) -> None:
        lost = set(self._live)
        self.connected = False
        self._live.clear()
        self._event_of.clear()
        self._subscribed.clear()
        self._pending.clear()
        self._seq.clear()
        if lost:
            self._on_lost(lost)

    async def _send(self, method: str, payload) -> int:
        if method not in _ALLOWED_METHODS:
            raise RuntimeError(f"novig ws: refusing to send {method!r}: stream is read-only")
        self._nonce += 1
        await self._ws.send(json.dumps({"nonce": self._nonce, method: payload}))
        return self._nonce

    def _want_events(self) -> list[str]:
        """Soonest events first, until the watched-market cap."""
        out, total = [], 0
        for eid, n in self._desired():
            if total + n > MAX_MARKETS:
                continue
            out.append(eid)
            total += n
        return out

    async def _sync_loop(self) -> None:
        """Keep the event subscriptions equal to the fetcher's target events."""
        while True:
            if time.monotonic() >= self._pause_until:
                want = self._want_events()
                want_set = set(want)
                drop = [e for e in self._subscribed if e not in want_set]
                if drop:
                    await self._send("unsubscribe", [f"event:{e}" for e in drop])
                    self._forget_events(drop)
                add = [e for e in want if e not in self._subscribed]
                for i in range(0, len(add), CHUNK):
                    if time.monotonic() < self._pause_until:
                        break
                    part = add[i:i + CHUNK]
                    self._subscribed.update(part)
                    nonce = await self._send("subscribe", {"events": {e: "bbo" for e in part}})
                    self._pending[nonce] = part
            await asyncio.sleep(SYNC_INTERVAL_S)

    def _forget_events(self, events) -> None:
        events = set(events)
        self._subscribed -= events
        mids = [m for m, e in self._event_of.items() if e in events]
        lost = {m for m in mids if m in self._live}
        for m in mids:
            self._live.discard(m)
            self._event_of.pop(m, None)
            self.state.pop(m, None)
            self._seq.pop(m, None)
        if lost:
            self._on_lost(lost)

    # ───────────────────────── messages ─────────────────────────

    def _handle(self, msg: dict) -> None:
        nonce = msg.get("nonce")
        if "code" in msg and "message" in msg:
            failed = self._pending.pop(nonce, None)
            if failed:
                # Un-mark so the next sync retries them.
                self._subscribed.difference_update(failed)
            if msg.get("code") == "RATE_LIMIT_EXCEEDED":
                self._pause_until = time.monotonic() + RATE_LIMIT_PAUSE_S
            logger.warning("novig ws error %s: %s", msg.get("code"), msg.get("message"))
            return
        self._pending.pop(nonce, None)
        for mid, snap in (msg.get("snapshot") or {}).items():
            bbo = (snap or {}).get("bbo")
            eid = (snap or {}).get("eventId")
            if bbo is None or eid not in self._subscribed:
                continue
            self._event_of[mid] = eid
            self._seq[mid] = int(bbo.get("seq") or 0)
            self.state[mid] = _parse_levels(bbo.get("bbo") or {})
            if _closed((snap.get("lifecycle") or {}).get("status")):
                self.state[mid] = {}
            self._live.add(mid)
            self._on_change(mid)
        for mid, d in (msg.get("delta") or {}).items():
            self._apply_delta(mid, d or {})

    def _apply_delta(self, mid: str, d: dict) -> None:
        if (mid not in self._live and mid not in self._seq
                and d.get("eventId") in self._subscribed):
            # A market that opened after its event subscription: no
            # snapshot, its book starts empty at seq 0.
            self._event_of[mid] = d["eventId"]
            self._seq[mid] = 0
            self.state[mid] = {}
            self._live.add(mid)
            if self._on_new_market is not None:
                self._on_new_market(mid)
        if mid not in self._live:
            return
        batch = d.get("bbo")
        changed = False
        if batch:
            seq = int(batch.get("seq") or 0)
            if seq != self._seq.get(mid, -1) + 1:
                # Missed a batch: stop trusting this market until a fresh
                # snapshot arrives; the poller covers it meanwhile.
                self.gaps += 1
                self._live.discard(mid)
                self._on_lost({mid})
                asyncio.ensure_future(self._resnapshot(mid))
                return
            self._seq[mid] = seq
            levels = self.state.setdefault(mid, {})
            for delta in batch.get("deltas") or []:
                oid = delta.get("outcomeId")
                lvl = delta.get("bbo")
                if not oid:
                    continue
                if lvl:
                    parsed = _parse_level(lvl)
                    if parsed:
                        levels[oid] = parsed
                else:
                    levels.pop(oid, None)
            changed = True
        for lc in ((d.get("lifecycle") or {}).get("deltas") or []):
            if _closed(lc.get("status")):
                self.state[mid] = {}
                changed = True
        if changed:
            self.updates += 1
            self._on_change(mid)

    async def _resnapshot(self, mid: str) -> None:
        try:
            if self._ws is not None and self._event_of.get(mid) in self._subscribed:
                await self._send("snapshot", {"markets": {mid: "bbo"}})
        except Exception:
            logger.debug("novig ws: resnapshot %s failed", mid, exc_info=True)


def _closed(status) -> bool:
    return status is not None and status != "OPEN"


def _parse_level(lvl: dict) -> tuple[float, int] | None:
    try:
        return float(lvl["price"]), int(lvl["qty"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_levels(levels: dict) -> Bbo:
    out: Bbo = {}
    for oid, lvl in levels.items():
        parsed = _parse_level(lvl or {})
        if parsed:
            out[oid] = parsed
    return out


def bbo_book(levels: Bbo) -> dict:
    """One-level book in the REST `Book` shape `take_quotes` reads."""
    return {"orders": {oid: [{"price": p, "qty": q}] for oid, (p, q) in levels.items()}}
