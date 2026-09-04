from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.systems import build_router
from server.odds.cache import OddsCache, init_schema_on_path
from server.systems.store import SystemSignalStore


def test_systems_endpoint_returns_all_primary_systems_without_fetching_odds(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    app = FastAPI()

    async def no_context(games, requested_date):
        return {}, []

    app.include_router(build_router(
        cache,
        signal_store=SystemSignalStore(path),
        context_enricher=no_context,
        now_fn=lambda: datetime(2026, 8, 29, 16, tzinfo=timezone.utc),
    ))
    response = TestClient(app).get("/api/systems?date=2026-08-29")
    assert response.status_code == 200
    body = response.json()
    assert len(body["evaluations"]) == 26
    assert body["summary"]["disabled"] == 3
    assert body["summary"]["qualifying_wagers"] == 0
    # An empty odds cache is an empty calendar, not missing context.
    assert all(item["status"] in ("disabled", "no_slate") for item in body["evaluations"])
    assert all(item["missing_fields"] == [] for item in body["evaluations"])
    assert body["summary"]["no_slate"] == 23


def test_systems_endpoint_memoizes_unchanged_analysis_and_invalidates_on_odds_version(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    app = FastAPI()
    calls = 0

    async def counted_context(games, requested_date):
        nonlocal calls
        calls += 1
        return {}, []

    app.include_router(build_router(
        cache, signal_store=SystemSignalStore(path), context_enricher=counted_context,
        now_fn=lambda: datetime(2026, 8, 29, 16, tzinfo=timezone.utc),
    ))
    client = TestClient(app)
    assert client.get("/api/systems?date=2026-08-29").status_code == 200
    assert client.get("/api/systems?date=2026-08-29").status_code == 200
    assert calls == 1

    cache._version += 1
    assert client.get("/api/systems?date=2026-08-29").status_code == 200
    assert calls == 2


def test_systems_endpoint_exposes_upcoming_as_every_game_after_tomorrow(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    app = FastAPI()

    async def no_context(games, requested_date):
        return {}, []

    app.include_router(build_router(
        cache, signal_store=SystemSignalStore(path), context_enricher=no_context,
        now_fn=lambda: datetime(2026, 8, 29, 16, tzinfo=timezone.utc),
    ))
    response = TestClient(app).get("/api/systems?timeframe=upcoming")

    assert response.status_code == 200
    assert response.json()["timeframe"] == "upcoming"
    assert response.json()["requested_date"] == "2026-08-31"
