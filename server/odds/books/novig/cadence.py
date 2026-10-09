"""Novig REST book-poll cadence by hours to start. Shared by the fetcher
(when to re-poll a market the websocket isn't covering) and ev.py (how old
a Novig offer may be before it's stale — one missed cycle plus grace)."""
from __future__ import annotations


def poll_interval_s(hours_to_start: float) -> int:
    if hours_to_start < 1:
        return 60
    if hours_to_start < 3:
        return 120
    if hours_to_start < 6:
        return 240
    if hours_to_start < 12:
        return 480
    if hours_to_start < 48:
        return 900
    return 1800
