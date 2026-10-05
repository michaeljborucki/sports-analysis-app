
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ODDS_API_KEY", "")  # disables fetcher

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


def test_college_football_endpoint_includes_week_ahead_games(tmp_path):
    from datetime import datetime, timedelta, timezone

    from fastapi import FastAPI

    from server.api.odds import build_router
    from server.odds.cache import OddsCache

    cache = OddsCache(tmp_path / "ncaaf.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "ncaaf-week-ahead",
        "sport_key": "ncaaf",
        "home_team": "Colorado Buffaloes",
        "away_team": "Georgia Tech Yellow Jackets",
        "commence_time": now + timedelta(days=3),
        "bookmaker_key": "draftkings",
        "market_key": "h2h",
        "outcome_name": "Colorado Buffaloes",
        "outcome_point": None,
        "price_american": -110,
        "fetched_at": now,
    }])
    test_app = FastAPI()
    test_app.include_router(build_router(cache))

    with TestClient(test_app) as client:
        response = client.get("/api/odds/ncaaf")

    assert [game["event_id"] for game in response.json()["games"]] == [
        "ncaaf-week-ahead"
    ]


def test_sports_endpoint_lists_registered_sports(app):
    with TestClient(app) as c:
        r = c.get("/api/sports")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()["sports"]}
    # Registry in server/sports.py — update this set when sports are added.
    assert keys == {
        "mlb", "tennis", "nba", "wnba", "nhl", "baseball_ncaa", "asian_baseball",
            "soccer", "ufc", "boxing", "cricket", "nfl", "ncaaf",
    }


def test_openapi_schema_accessible(app):
    with TestClient(app) as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/odds/{sport}" in paths
    assert "/api/props/{sport}" in paths
    assert "/api/sports" in paths


def test_openapi_game_includes_league_metadata(app):
    with TestClient(app) as c:
        r = c.get("/openapi.json")
    assert r.status_code == 200
    game = r.json()["components"]["schemas"]["Game"]
    assert "league_key" in game["properties"]
    assert "league_title" in game["properties"]


def test_soccer_spread_registry_exposes_alternate_spreads(app):
    with TestClient(app) as c:
        sports = c.get("/api/sports").json()["sports"]

    soccer = next(sport for sport in sports if sport["key"] == "soccer")
    spread = next(group for group in soccer["market_groups"] if group["main_key"] == "spreads")
    assert spread["alt_key"] == "alternate_spreads"


# ────────── blocking handlers must not run on the event loop ──────────

@pytest.mark.parametrize("path", ["/api/health", "/api/cache-mode"])
def test_blocking_endpoints_are_not_coroutines(app, path):
    """`/api/cache-mode` runs `SELECT COUNT(*) ... FROM odds_snapshot`
    against cache.db AND cache.snapshot.db (584MB / 300MB) — a full scan
    each. `/api/health` reads the same cache synchronously.

    Declared `async def`, that blocking SQLite runs ON the event loop, so
    one slow call stalls every other request, the SSE flush loop and the
    heartbeat with it. Measured in this state: cache-mode 23.5s and health
    12.5s, concurrently, while the scanners were merely warm.

    A plain `def` handler is run in Starlette's threadpool instead, so a
    slow read costs that one request rather than the whole server.
    """
    import asyncio

    endpoints = [
        r.endpoint for r in app.routes
        if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", set())
    ]
    assert endpoints, f"no GET route registered for {path}"
    for fn in endpoints:
        assert not asyncio.iscoroutinefunction(fn), (
            f"{path} is `async def` but performs blocking sqlite I/O — "
            f"it will block the event loop; declare it `def`"
        )
