"""Shared live-odds feed client.

When `ODDS_FEED_BASE_URL` is configured, the agent pulls live odds from the
betting-site backend's shared cache (`GET /api/odds/{sport}/raw`) instead of
spending its own Odds API credits on games the backend is already polling.
The backend returns events in The Odds API's native JSON shape, so callers
run the response through the exact same parsers they use for a direct pull.

Any failure (feed disabled, backend down, sport not configured, bad payload)
raises `FeedUnavailable` so the caller can transparently fall back to a direct
Odds API request. The feed only covers *live* odds; historical pulls always
go straight to the Odds API.

The whole event list is memoized for a few seconds because one pipeline run
queries it many times (once for game odds, once per event for additional
markets, once per event for props) — without the memo that would be one HTTP
round-trip per call.
"""
from __future__ import annotations

import logging
import time

import requests

from config import ODDS_FEED_BASE_URL, ODDS_FEED_SPORT, ODDS_FEED_TTL_SECONDS

logger = logging.getLogger(__name__)


class FeedUnavailable(Exception):
    """The shared feed could not satisfy the request; fall back to the API."""


_cache: dict = {"ts": 0.0, "events": None}


def feed_enabled() -> bool:
    return bool(ODDS_FEED_BASE_URL) and bool(ODDS_FEED_SPORT)


def reset_cache() -> None:
    """Drop the in-process memo. Exposed for tests."""
    _cache["ts"] = 0.0
    _cache["events"] = None


def get_feed_events(force: bool = False) -> list[dict]:
    """All live events for the configured sport, in Odds API native shape.

    Memoized for `ODDS_FEED_TTL_SECONDS`. Raises `FeedUnavailable` on any
    failure so the caller can fall back to a direct Odds API pull.
    """
    if not feed_enabled():
        raise FeedUnavailable("odds feed not configured (set ODDS_FEED_BASE_URL)")

    now = time.time()
    if (
        not force
        and _cache["events"] is not None
        and now - _cache["ts"] < ODDS_FEED_TTL_SECONDS
    ):
        return _cache["events"]

    url = f"{ODDS_FEED_BASE_URL}/api/odds/{ODDS_FEED_SPORT}/raw"
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as e:
        raise FeedUnavailable(f"feed request failed: {e}") from e
    if resp.status_code != 200:
        raise FeedUnavailable(f"feed returned HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise FeedUnavailable(f"feed returned invalid JSON: {e}") from e

    events = payload.get("data", []) if isinstance(payload, dict) else []
    _cache["events"] = events
    _cache["ts"] = now
    logger.info(
        "[odds.feed] %d events from %s (stale=%ss)",
        len(events), url, payload.get("stale_seconds") if isinstance(payload, dict) else "?",
    )
    return events


def get_feed_event(event_id: str) -> dict | None:
    """One event by id from the (memoized) feed, or None if not present."""
    for event in get_feed_events():
        if event.get("id") == event_id:
            return event
    return None
