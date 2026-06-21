"""SSE event broadcaster for live odds updates.

The cache writes (upsert + 3 purge methods) call `mark_dirty()`. A
background `flush_loop` checks the dirty flag every FLUSH_INTERVAL_S;
if set, it broadcasts a single "tick" event to every subscriber and
resets the flag. Net effect: a burst of N upserts inside the window
coalesces to one tick — bounded UI re-render rate regardless of WS
push volume.

A separate `heartbeat_loop` broadcasts a no-op every 15s so that
proxies / intermediaries don't drop the SSE connection during idle
stretches.

Design rationale (see ROADMAP.md #8 + the design doc in commit thread):

  - One channel, dumb-tick payload. The UI doesn't need to know WHICH
    event changed; it uses SWR `mutate(key => true)` on tick to
    revalidate every key currently in its cache. With the request-
    coalescing memo from `coalesce.py`, concurrent mutations collapse
    to one server-side scan per endpoint.

  - Hooked at `OddsCache._bump_version()` rather than at each fetcher.
    Captures REST + WS + purges through a single emit point.

  - Bounded per-subscriber queue (256 events). A slow / disconnected
    subscriber gets backpressure-dropped rather than blocking the
    producer or the other subscribers.

  - Module-level state. Single-process server; no need for an
    instance-keyed broker.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any


logger = logging.getLogger(__name__)


# Coalescing window — multiple mark_dirty() calls within this many
# seconds emit one tick. 1.0s is the floor at which client work
# (SWR mutate(()=>true) → revalidate every key globally) stops
# saturating the main thread. Kalshi/Polymarket WS streams push so
# continuously that the dirty flag is essentially always set, so this
# interval IS the effective tick rate. Still 15× faster than the old
# 15s SWR polling. Don't drop below ~0.5s without re-checking client
# CPU and server scanner load.
FLUSH_INTERVAL_S = 1.0

# Idle keepalive so proxies / NAT translators don't drop the SSE
# connection. 15s is well inside every common idle-timeout default.
HEARTBEAT_INTERVAL_S = 15.0

# Per-subscriber bounded queue. 256 is generous — at 1 tick/s the
# buffer holds ~4 minutes of events for a stuck client before drops
# start.
QUEUE_MAX = 256


# Module-level subscriber registry. asyncio.Queue is single-threaded
# under the event loop; no lock needed for set add/discard since the
# event loop serializes all access.
_subscribers: "set[asyncio.Queue[dict[str, Any]]]" = set()

# Debounce flag. Reads/writes are atomic under CPython's GIL; the
# flush_loop's read-and-clear is safe with concurrent writes — a write
# between the read and clear is captured on the next flush iteration.
_pending_dirty: bool = False


def mark_dirty() -> None:
    """Signal that the odds cache has changed.

    Cheap (sets a boolean). Safe to call from any context — sync code,
    async code, no event loop running yet. Multiple calls within a
    FLUSH_INTERVAL_S window coalesce to a single broadcast tick.

    Hooked at `OddsCache._bump_version()` so every state-changing op
    (upsert, purges) flows through here uniformly. Calls from outside
    a running event loop are still safe — the flag gets set; the
    flush_loop picks it up once the app starts.
    """
    global _pending_dirty
    _pending_dirty = True


def subscribe() -> "asyncio.Queue[dict[str, Any]]":
    """Register a new SSE subscriber.

    Returns a bounded queue receiving every event. Caller MUST call
    `unsubscribe(q)` on disconnect — the SSE endpoint wraps this in
    a try/finally.
    """
    q: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue(maxsize=QUEUE_MAX)
    _subscribers.add(q)
    logger.debug("SSE subscribe: %d active", len(_subscribers))
    return q


def unsubscribe(q: "asyncio.Queue[dict[str, Any]]") -> None:
    """Remove a subscriber. Idempotent — safe to call from disconnect
    cleanup even if subscribe wasn't called for any reason."""
    _subscribers.discard(q)
    logger.debug("SSE unsubscribe: %d active", len(_subscribers))


def subscriber_count() -> int:
    """Number of active subscribers. Useful for health/debug endpoints."""
    return len(_subscribers)


def _broadcast(event: dict[str, Any]) -> None:
    """Fan out an event to every subscriber's queue.

    Uses `put_nowait` so a slow consumer (queue full) gets the event
    DROPPED rather than blocking the producer. The next event still
    reaches them. Dropping individual events is fine because (a)
    ticks are idempotent (one tick = "re-fetch everything", no
    cumulative loss), and (b) heartbeats are belt-and-suspenders.
    """
    if not _subscribers:
        return
    dropped = 0
    # Snapshot to avoid set-mutation-during-iteration if a subscriber
    # disconnects while we're broadcasting.
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dropped += 1
    if dropped:
        logger.debug("SSE: dropped event for %d slow subscriber(s)", dropped)


async def flush_loop() -> None:
    """Background task: every FLUSH_INTERVAL_S, broadcast ONE tick if
    any mark_dirty() calls have occurred since the previous flush.
    Multiple bumps in the window coalesce to a single tick — that's
    the whole point.

    Started from FastAPI's lifespan context; cancelled on shutdown.
    Catches and logs exceptions so a transient broadcast failure
    doesn't kill the loop permanently.
    """
    global _pending_dirty
    logger.info("SSE flush_loop starting (interval=%.2fs)", FLUSH_INTERVAL_S)
    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            if _pending_dirty:
                # Clear before broadcast so any mark_dirty during the
                # broadcast is captured for the next flush iteration.
                _pending_dirty = False
                _broadcast({"type": "tick", "ts": time.time()})
        except asyncio.CancelledError:
            logger.info("SSE flush_loop cancelled")
            raise
        except Exception:
            logger.exception("SSE flush_loop iteration failed; continuing")


async def heartbeat_loop() -> None:
    """Background task: every HEARTBEAT_INTERVAL_S, broadcast a
    no-op heartbeat so idle SSE connections don't get dropped by
    proxies / browsers / OS NAT translators.
    """
    logger.info(
        "SSE heartbeat_loop starting (interval=%.1fs)", HEARTBEAT_INTERVAL_S
    )
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            _broadcast({"type": "heartbeat", "ts": time.time()})
        except asyncio.CancelledError:
            logger.info("SSE heartbeat_loop cancelled")
            raise
        except Exception:
            logger.exception("SSE heartbeat_loop iteration failed; continuing")


def _reset_for_tests() -> None:
    """Drop all subscribers and clear the dirty flag. Tests only."""
    global _pending_dirty
    _subscribers.clear()
    _pending_dirty = False
