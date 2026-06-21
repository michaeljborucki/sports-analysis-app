"""Server-Sent Events endpoint for live odds updates.

One endpoint: GET /api/stream/odds.

Event types emitted:
  - `connected`  : once per subscription, immediately after connect
  - `tick`       : whenever the odds cache changes (debounced ≤10/s)
  - `heartbeat`  : every 15s — proxy/NAT keepalive, ignored by client

The browser uses `new EventSource('/api/stream/odds')` and listens for
the `tick` event to revalidate its SWR cache. On `connected`, the
client re-fetches all visible keys (covers the reconnect-after-drop
case without server-side event replay logs).

Roll-our-own SSE (no sse-starlette dependency). The wire protocol
is just `event: <name>\\ndata: <json>\\n\\n` per RFC EventSource.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..odds import events


logger = logging.getLogger(__name__)


# Belt-and-suspenders timeout for `queue.get()`. The heartbeat_loop
# normally pushes every 15s; if for any reason it stops (shouldn't),
# this fallback ensures the endpoint still emits a keepalive comment
# rather than holding the connection silent forever.
_QUEUE_GET_TIMEOUT_S = 30.0


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/stream/odds")
    async def stream_odds(request: Request) -> StreamingResponse:
        """Subscribe to the live odds event stream.

        Returns an SSE stream. The browser's EventSource handles
        reconnect automatically; this endpoint just produces events
        for as long as the client stays connected.
        """
        async def event_iterator():
            q = events.subscribe()
            try:
                # Initial handshake — tells the client they're live so
                # any reconnect-after-drop can trigger a full re-fetch.
                yield _format_event(
                    "connected", {"ts": time.time()}
                )

                while True:
                    # Cheap disconnect check — Starlette tracks this on
                    # the request scope. If the client navigated away,
                    # bail before doing more work.
                    if await request.is_disconnected():
                        break

                    try:
                        event = await asyncio.wait_for(
                            q.get(), timeout=_QUEUE_GET_TIMEOUT_S
                        )
                    except asyncio.TimeoutError:
                        # Belt-and-suspenders — heartbeat_loop should
                        # normally fire first. Emit an SSE comment as
                        # a last-resort keepalive (comments don't
                        # trigger any client event handler).
                        yield ": keepalive\n\n"
                        continue

                    kind = event.get("type", "tick")
                    yield _format_event(kind, event)
            except asyncio.CancelledError:
                # Client disconnect or server shutdown — clean exit.
                raise
            finally:
                events.unsubscribe(q)

        return StreamingResponse(
            event_iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # Disable any proxy buffering (nginx X-Accel-Buffering;
                # browsers/dev-servers ignore it but it's harmless).
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/stream/status")
    async def stream_status() -> dict:
        """Lightweight diagnostic — how many SSE subscribers are
        currently connected. Useful for debugging connection leaks."""
        return {"subscribers": events.subscriber_count()}

    return router


def _format_event(kind: str, payload: dict) -> str:
    """Render a single SSE message.

    SSE wire format is plain text:
      event: <name>\\n
      data: <json>\\n
      \\n
    """
    return f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
