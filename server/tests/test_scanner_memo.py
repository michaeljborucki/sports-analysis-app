"""Behavioral tests for the scanner-endpoint version-keyed memo.

The three scanner endpoints (/api/ev, /api/arbitrage, /api/low-hold) wrap
their handlers in a 20s TTLCache. The cache_version optimization folds
`OddsCache.version` into the memo key so two consecutive scans with no
intervening upsert hit the memo even after the 20s TTL would have expired
— and any upsert/purge breaks the cache key, forcing a re-scan.

These tests confirm:
  1. Two scans with no upsert between them hit the memo (the underlying
     scan function runs exactly once).
  2. An upsert between two scans bumps the version, breaking the memo
     and forcing a second scan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.arbitrage import build_router as build_arb_router
from server.api.low_hold import build_router as build_lh_router
from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


def _seed_two_book_h2h(cache: OddsCache) -> None:
    """Drop a minimal h2h universe into the cache so scanner endpoints
    have something concrete to scan."""
    now = datetime.now(timezone.utc)
    cache.upsert([
        {
            "event_id": "evt_1", "sport_key": "mlb",
            "home_team": "Yankees", "away_team": "Red Sox",
            "commence_time": now,
            "bookmaker_key": "draftkings",
            "market_key": "h2h",
            "outcome_name": "Yankees", "outcome_point": None,
            "price_american": -110, "fetched_at": now,
        },
        {
            "event_id": "evt_1", "sport_key": "mlb",
            "home_team": "Yankees", "away_team": "Red Sox",
            "commence_time": now,
            "bookmaker_key": "draftkings",
            "market_key": "h2h",
            "outcome_name": "Red Sox", "outcome_point": None,
            "price_american": -110, "fetched_at": now,
        },
    ])


def test_arbitrage_memo_hits_when_version_unchanged(cache, monkeypatch):
    """Two /api/arbitrage requests with no upsert between them should hit
    the memo — the underlying scan_all_arbs runs exactly once."""
    _seed_two_book_h2h(cache)

    # Count underlying scan invocations by wrapping the scan func.
    import server.api.arbitrage as arb_mod
    call_count = {"n": 0}
    real_scan = arb_mod.scan_all_arbs

    def counting_scan(*args, **kwargs):
        call_count["n"] += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(arb_mod, "scan_all_arbs", counting_scan)

    app = FastAPI()
    app.include_router(build_arb_router(cache))
    with TestClient(app) as client:
        r1 = client.get("/api/arbitrage")
        r2 = client.get("/api/arbitrage")
        assert r1.status_code == 200
        assert r2.status_code == 200

    # Exactly one underlying scan despite two requests = memo hit.
    assert call_count["n"] == 1, (
        f"expected 1 scan (memo hit), got {call_count['n']}"
    )


def test_arbitrage_memo_busts_on_upsert(cache, monkeypatch):
    """An upsert between two /api/arbitrage requests bumps the version,
    breaks the cache key, and forces a fresh scan."""
    _seed_two_book_h2h(cache)

    import server.api.arbitrage as arb_mod
    call_count = {"n": 0}
    real_scan = arb_mod.scan_all_arbs

    def counting_scan(*args, **kwargs):
        call_count["n"] += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(arb_mod, "scan_all_arbs", counting_scan)

    app = FastAPI()
    app.include_router(build_arb_router(cache))
    with TestClient(app) as client:
        r1 = client.get("/api/arbitrage")
        v_before = cache.version

        # An upsert mid-flight must bump the version and invalidate the memo.
        now = datetime.now(timezone.utc)
        cache.upsert([
            {
                "event_id": "evt_1", "sport_key": "mlb",
                "home_team": "Yankees", "away_team": "Red Sox",
                "commence_time": now,
                "bookmaker_key": "fanduel",
                "market_key": "h2h",
                "outcome_name": "Yankees", "outcome_point": None,
                "price_american": -105, "fetched_at": now,
            },
        ])
        assert cache.version == v_before + 1

        r2 = client.get("/api/arbitrage")
        assert r1.status_code == 200
        assert r2.status_code == 200

    # Two scans — once before, once after the upsert.
    assert call_count["n"] == 2, (
        f"expected 2 scans (memo bust on version bump), got {call_count['n']}"
    )


def test_low_hold_memo_hits_when_version_unchanged(cache, monkeypatch):
    """Same memo-hit behavior for /api/low-hold."""
    _seed_two_book_h2h(cache)

    import server.api.low_hold as lh_mod
    call_count = {"n": 0}
    real_scan = lh_mod.scan_all_low_hold

    def counting_scan(*args, **kwargs):
        call_count["n"] += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(lh_mod, "scan_all_low_hold", counting_scan)

    app = FastAPI()
    app.include_router(build_lh_router(cache))
    with TestClient(app) as client:
        r1 = client.get("/api/low-hold")
        r2 = client.get("/api/low-hold")
        assert r1.status_code == 200
        assert r2.status_code == 200

    assert call_count["n"] == 1, (
        f"expected 1 scan (memo hit), got {call_count['n']}"
    )


# ──────────────────────────────────────────────────────────────────────
# Coalescing — simultaneous-request behavior
# ──────────────────────────────────────────────────────────────────────
#
# The memo above catches the *serial* case (B arrives after A returns,
# B hits memo). Coalescing catches the *concurrent* case (A and B both
# arrive before A's scan completes → both should share A's work).
# Verified by injecting an artificially-slow scan so the requests
# actually overlap in time.


async def test_arbitrage_coalesces_simultaneous_requests(cache, monkeypatch):
    """Three concurrent /api/arbitrage requests on the same cache state
    must trigger scan_all_arbs exactly ONCE. They all share the first
    caller's task via the coalesce helper."""
    import asyncio
    import time
    import httpx
    from httpx import ASGITransport
    import server.api.arbitrage as arb_mod
    from server.odds import coalesce

    _seed_two_book_h2h(cache)
    # Make sure no in-flight state leaks in from another test in the module.
    coalesce._inflight.clear()

    call_count = {"n": 0}
    real_scan = arb_mod.scan_all_arbs

    def slow_scan(*args, **kwargs):
        # Artificial delay so the second and third requests have time
        # to join the in-flight task before the first one returns.
        call_count["n"] += 1
        time.sleep(0.10)
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(arb_mod, "scan_all_arbs", slow_scan)

    app = FastAPI()
    app.include_router(build_arb_router(cache))

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        r1, r2, r3 = await asyncio.gather(
            client.get("/api/arbitrage"),
            client.get("/api/arbitrage"),
            client.get("/api/arbitrage"),
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
    assert r1.json() == r2.json() == r3.json()
    # Coalescing: ONE underlying scan despite three concurrent requests.
    assert call_count["n"] == 1, (
        f"expected 1 scan (coalesced), got {call_count['n']}"
    )
