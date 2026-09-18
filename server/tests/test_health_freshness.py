from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.health import build_router
from server.odds.cache import OddsCache, init_schema_on_path


class _Fetcher:
    is_running = False

    def all_enabled_tiers(self):
        return []


def test_health_uses_newest_actual_odds_row_over_legacy_fetcher_timestamp(tmp_path):
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    old = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
    fresh = datetime(2026, 8, 29, 22, 4, tzinfo=timezone.utc)
    cache.set_status(last_fetch_at=old)
    cache.upsert([{
        "event_id": "e1", "sport_key": "mlb", "home_team": "Home",
        "away_team": "Away", "commence_time": (fresh + timedelta(hours=2)).isoformat(),
        "bookmaker_key": "coral33", "market_key": "h2h",
        "outcome_name": "Home", "outcome_point": 0,
        "price_american": -110, "fetched_at": fresh.isoformat(),
    }])
    app = FastAPI()
    app.include_router(build_router(cache, _Fetcher()))

    body = TestClient(app).get("/api/health").json()
    assert body["last_fetch_at"] == "2026-08-29T22:04:00Z"


def test_health_does_not_report_a_dead_fetchers_timestamp_in_betting_db_mode(
    tmp_path, monkeypatch,
):
    """In betting_db mode the native Odds API fetcher no longer runs, so its
    `fetcher_status` row is frozen (2026-08-29 on the live box). Whenever the
    local offer table is momentarily empty, falling back to that row made
    /api/health report a three-week-old "last fetch". Report nothing instead.
    """
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    cache.set_status(last_fetch_at=datetime(2026, 8, 29, 2, 38, tzinfo=timezone.utc))
    app = FastAPI()
    app.include_router(build_router(cache, _Fetcher()))

    body = TestClient(app).get("/api/health").json()
    assert body["last_fetch_at"] is None


def test_native_mode_still_falls_back_to_the_fetcher_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    cache.set_status(last_fetch_at=datetime(2026, 8, 29, 2, 38, tzinfo=timezone.utc))
    app = FastAPI()
    app.include_router(build_router(cache, _Fetcher()))

    body = TestClient(app).get("/api/health").json()
    assert body["last_fetch_at"] == "2026-08-29T02:38:00Z"
