"""Typed publish helpers for the four sidecar SSE event types.

Thin layer over server.odds.events.publish() — every helper sets the type
field. Keeping these inline-typed dicts ensures the consumer schema is
discoverable from one file."""
from __future__ import annotations

from server.odds import events


def emit_placement(payload: dict) -> None:
    events.publish({"type": "sidecar_placement", **payload})


def emit_topup_required(payload: dict) -> None:
    events.publish({"type": "sidecar_topup_required", **payload})


def emit_signal_skipped(payload: dict) -> None:
    events.publish({"type": "sidecar_signal_skipped", **payload})


def emit_partial_fill(payload: dict) -> None:
    events.publish({"type": "sidecar_partial_fill", **payload})
