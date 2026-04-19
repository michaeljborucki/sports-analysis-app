from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ODDS_API_KEY", "")  # disables fetcher
    monkeypatch.setenv("BET_CARD_DIR", str(Path(__file__).parent / "fixtures"))
    monkeypatch.setenv("BETS_CSV", str(Path(__file__).parent / "fixtures" / "bets_example.csv"))

    import server.config as config_mod

    original_from_env = config_mod.Config.from_env

    def patched_from_env():
        c = original_from_env()
        c.cache_db = tmp_path / "cache.db"
        return c

    monkeypatch.setattr(config_mod.Config, "from_env", staticmethod(patched_from_env))

    from server.main import create_app
    return create_app()


def test_health_endpoint(app):
    with TestClient(app) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "last_fetch_at" in body


def test_odds_endpoint_empty_cache(app):
    with TestClient(app) as c:
        r = c.get("/api/odds/mlb")
    assert r.status_code == 200
    body = r.json()
    assert body["games"] == []
    assert body["stale_seconds"] == 0


def test_picks_endpoint_returns_valid_status(app):
    # Today (runtime) likely doesn't match fixture date — accept either outcome
    with TestClient(app) as c:
        r = c.get("/api/picks/mlb")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "no_picks_today")


def test_openapi_schema_accessible(app):
    with TestClient(app) as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/odds/mlb" in r.json()["paths"]
    assert "/api/picks/mlb" in r.json()["paths"]
