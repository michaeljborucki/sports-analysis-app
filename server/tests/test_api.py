from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ODDS_API_KEY", "")  # disables fetcher
    monkeypatch.setenv("BET_CARD_DIR", str(Path(__file__).parent / "fixtures"))
    monkeypatch.setenv("BETS_CSV", str(Path(__file__).parent / "fixtures" / "bets_example.csv"))

    import server.config as config_mod
    import server.user_settings as us_mod

    original_from_env = config_mod.Config.from_env

    def patched_from_env():
        c = original_from_env()
        c.cache_db = tmp_path / "cache.db"
        return c

    monkeypatch.setattr(config_mod.Config, "from_env", staticmethod(patched_from_env))
    # Isolate user settings — otherwise the real user_settings.json (edited
    # by running the backend) leaks into the test's view of enabled sports.
    monkeypatch.setattr(us_mod, "SETTINGS_PATH", tmp_path / "user_settings.json")

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


def test_odds_endpoint_rejects_unknown_sport(app):
    with TestClient(app) as c:
        r = c.get("/api/odds/notasport")
    assert r.status_code == 404


def test_raw_odds_endpoint_empty_cache(app):
    with TestClient(app) as c:
        r = c.get("/api/odds/mlb/raw")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert "fetched_at" in body
    assert "stale_seconds" in body


def test_raw_odds_endpoint_rejects_unknown_sport(app):
    with TestClient(app) as c:
        r = c.get("/api/odds/notasport/raw")
    assert r.status_code == 404


def test_picks_endpoint_returns_valid_status(app):
    with TestClient(app) as c:
        r = c.get("/api/picks/mlb")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "no_picks_today")


def test_sports_endpoint_lists_registered_sports(app):
    with TestClient(app) as c:
        r = c.get("/api/sports")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()["sports"]}
    # Registry in server/sports.py — update this set when sports are added.
    assert keys == {
        "mlb", "tennis", "nba", "wnba", "nhl", "baseball_ncaa", "asian_baseball",
        "soccer", "ufc", "boxing", "cricket",
    }


def test_openapi_schema_accessible(app):
    with TestClient(app) as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/odds/{sport}" in paths
    assert "/api/odds/{sport}/raw" in paths
    assert "/api/picks/{sport}" in paths
    assert "/api/props/{sport}" in paths
    assert "/api/sports" in paths
