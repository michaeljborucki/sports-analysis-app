"""Shared live-odds feed client.

When `ODDS_FEED_BASE_URL` and `ODDS_FEED_SPORT` are configured, the agent pulls
live odds from the betting-site backend's shared cache
(`GET /api/odds/{sport}/raw`) instead of spending its own Odds API credits on
games the backend is already polling. The backend returns events in The Odds
API's native JSON shape, so callers run the response through the exact same
parsers they use for a direct pull.

Any failure (feed disabled, backend down, sport not configured, bad payload)
raises `FeedUnavailable` so the caller can transparently fall back to a direct
Odds API request. The feed only covers *live* odds; historical pulls always go
straight to the Odds API.

The whole event list is memoized for a few seconds because one pipeline run
queries it many times — without the memo that would be one HTTP round-trip per
call.
"""
from __future__ import annotations

import logging
import time

import requests

from config import (
    ODDS_FEED_BASE_URL,
    ODDS_FEED_MAX_STALE_SECONDS,
    ODDS_FEED_SPORT,
    ODDS_FEED_TTL_SECONDS,
)

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
        raise FeedUnavailable(
            "odds feed not configured (set ODDS_FEED_BASE_URL and ODDS_FEED_SPORT)"
        )

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

    if not isinstance(payload, dict):
        raise FeedUnavailable("feed payload was not an object")

    # Staleness guard: a backend that's up but serving frozen/stale odds (cache
    # in snapshot/latest mode, or the fetcher stalled) still answers 200, so a
    # hard-failure fallback alone wouldn't catch it. `stale_seconds` is how long
    # ago the fetcher last completed a cycle; None means it never ran. Reject
    # anything past the threshold and let the caller fall back to the live API.
    # Set ODDS_FEED_MAX_STALE_SECONDS=0 to disable; keep it above the backend's
    # poll interval so normal poll jitter doesn't trip it.
    stale = payload.get("stale_seconds")
    if ODDS_FEED_MAX_STALE_SECONDS > 0:
        if stale is None:
            raise FeedUnavailable("feed has never been fetched (stale_seconds=None)")
        if stale > ODDS_FEED_MAX_STALE_SECONDS:
            raise FeedUnavailable(
                f"feed is stale ({stale}s > {ODDS_FEED_MAX_STALE_SECONDS}s)"
            )

    events = payload.get("data", [])
    _cache["events"] = events
    _cache["ts"] = now
    logger.info("[odds.feed] %d events from %s (stale=%ss)", len(events), url, stale)
    return events


def get_feed_event(event_id: str) -> dict | None:
    """One event by id from the (memoized) feed, or None if not present."""
    for event in get_feed_events():
        if event.get("id") == event_id:
            return event
    return None


def warn_missing_markets(events: list[dict], expected, context: str) -> list[str]:
    """Loudly log any expected market entirely absent from the feed.

    The shared feed only carries the markets the backend has enabled (in
    markets.<sport>.toml + the /settings UI). If the backend has a market the
    agent models switched off, the agent silently sees zero of it — this warning
    surfaces that coupling. A market is "present" if it appears in any event;
    genuinely-not-yet-posted markets will also show up here, so treat it as a
    heads-up, not an error. Returns the sorted list of missing market keys.
    """
    present = {
        m["key"]
        for event in events
        for bk in event.get("bookmakers", [])
        for m in bk.get("markets", [])
    }
    missing = sorted(set(expected) - present)
    if missing:
        logger.warning(
            "[odds.feed:%s] %d expected market(s) absent from shared feed — "
            "disabled in backend settings or not yet posted: %s",
            context, len(missing), ", ".join(missing),
        )
    return missing
