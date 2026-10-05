"""/api/dashboard must not block the event loop.

The dashboard reads the whole cache and runs a cross-sport arb scan. When
that ran inline in the async handler, every other request (even the
instant /api/cache-mode style reads) queued behind it for 30-60s. These
tests pin the fix: the heavy work runs off-loop, and simultaneous
dashboard requests share one computation.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import server.api.dashboard as dash_mod
from server.api.dashboard import build_router as build_dashboard_router
from server.odds import coalesce
from server.odds.cache import OddsCache


class _StubFetcher:
    is_running = False

    def all_enabled_tiers(self):
        return []


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    now = datetime.now(timezone.utc)
    c.upsert([
        {
            "event_id": "evt_1", "sport_key": "mlb",
            "home_team": "Yankees", "away_team": "Red Sox",
            "commence_time": now,
            "bookmaker_key": "draftkings",
            "market_key": "h2h",
            "outcome_name": name, "outcome_point": None,
            "price_american": -110, "fetched_at": now,
        }
        for name in ("Yankees", "Red Sox")
    ])
    return c


def _app(cache: OddsCache) -> FastAPI:
    app = FastAPI()
    app.include_router(build_dashboard_router(cache, _StubFetcher(), []))

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    return app


def _slow_scan(monkeypatch, delay_s: float) -> dict:
    calls = {"n": 0}
    real_scan = dash_mod.scan_all_arbs

    def slow(*args, **kwargs):
        calls["n"] += 1
        time.sleep(delay_s)  # blocking, like a real CPU-bound scan
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(dash_mod, "scan_all_arbs", slow)
    return calls


async def test_dashboard_does_not_block_other_requests(cache, monkeypatch):
    coalesce._inflight.clear()
    _slow_scan(monkeypatch, 0.6)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(cache)), base_url="http://t"
    ) as client:
        done: dict[str, float] = {}

        async def timed(name: str, path: str, delay: float = 0.0):
            await asyncio.sleep(delay)
            resp = await client.get(path)
            done[name] = time.perf_counter()
            return resp

        dash, ping = await asyncio.gather(
            timed("dash", "/api/dashboard"),
            timed("ping", "/ping", delay=0.1),  # arrives mid-scan
        )

    assert ping.status_code == 200
    assert dash.status_code == 200
    assert done["ping"] < done["dash"], "/ping was stuck behind the dashboard scan"


async def test_dashboard_coalesces_simultaneous_requests(cache, monkeypatch):
    coalesce._inflight.clear()
    calls = _slow_scan(monkeypatch, 0.1)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(cache)), base_url="http://t"
    ) as client:
        r1, r2, r3 = await asyncio.gather(
            client.get("/api/dashboard"),
            client.get("/api/dashboard"),
            client.get("/api/dashboard"),
        )

    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert r1.json() == r2.json() == r3.json()
    assert calls["n"] == 1, f"expected 1 scan, got {calls['n']}"


async def test_dashboard_books_param_is_part_of_the_key(cache, monkeypatch):
    coalesce._inflight.clear()
    calls = _slow_scan(monkeypatch, 0.0)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=_app(cache)), base_url="http://t"
    ) as client:
        await client.get("/api/dashboard")
        await client.get("/api/dashboard?books=draftkings")

    assert calls["n"] == 2


async def test_dashboard_reads_shared_snapshot_not_the_cache(cache, monkeypatch):
    """With the shared odds snapshot available, the dashboard must reuse its
    pre-normalized non-prop games instead of re-reading every cache row."""
    from server.odds.latest_snapshot import LatestOddsSnapshotService

    coalesce._inflight.clear()
    service = LatestOddsSnapshotService(cache)
    await service.get()  # build once, like the running app does

    def boom(*args, **kwargs):
        raise AssertionError("dashboard re-read the whole cache")

    monkeypatch.setattr(cache, "all_current", boom)

    app = FastAPI()
    app.include_router(
        build_dashboard_router(cache, _StubFetcher(), [], snapshot_service=service)
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/api/dashboard")

    assert resp.status_code == 200
