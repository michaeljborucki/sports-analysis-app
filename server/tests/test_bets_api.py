from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.odds.cache import OddsCache
from server.odds.bets import BetRow, upsert_bets
from server.api.bets import build_router as bets_router


@pytest.fixture
def app_and_cache(tmp_path: Path):
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    app = FastAPI()
    app.include_router(bets_router(cache))
    upsert_bets(cache, [BetRow(
        source_book="coral33", external_id="t1", customer_id="cust1",
        accepted_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        settled_at=datetime(2026, 6, 19, 23, tzinfo=timezone.utc),
        status="win", wager_type="straight", total_picks=1,
        sport_key="mlb", event_id=None,
        home_team="LAD", away_team="SF",
        market_key="h2h", outcome_name="LAD", outcome_point=0.0,
        odds_american=-145, stake=50.0, to_win=34.5,
        settled_amount=84.5, is_free_play=False,
        raw_description="LAD ML", imported_at=None,
    )])
    return app, cache


def test_get_bets_returns_unified_rows(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    r = client.get("/api/bets")
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 1
    assert body["bets"][0]["source_book"] == "coral33"


def test_get_bets_filters_by_book(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    assert client.get("/api/bets?book=coral33").json()["total_count"] == 1
    assert client.get("/api/bets?book=kalshi").json()["total_count"] == 0


def test_get_rollups_returns_all_windows(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    r = client.get("/api/bets/rollups")
    assert r.status_code == 200
    body = r.json()
    for k in ("window_30d", "window_90d", "lifetime", "by_book", "by_sport", "by_market"):
        assert k in body
    assert body["lifetime"]["count"] == 1
    assert len(body["by_book"]) == 1
    assert body["by_book"][0]["source_book"] == "coral33"


import io


def test_csv_import_round_trip(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    csv_body = (
        "date,book,sport,event,market,side,odds,stake,result\n"
        "2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W\n"
        "2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending\n"
    )
    r = client.post(
        "/api/bets/import",
        files={"file": ("bets.csv", io.BytesIO(csv_body.encode()), "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 2
    assert body["rejected"] == []
    list_r = client.get("/api/bets?book=imported")
    assert list_r.json()["total_count"] == 2


def test_csv_import_reports_bad_rows(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    csv_body = (
        "date,book,sport,event,market,side,odds,stake,result\n"
        "not-a-date,DK,nba,X @ Y,h2h,X,-110,50,W\n"
        "2026-06-19,DK,nba,A @ B,h2h,A,+110,25,L\n"
    )
    r = client.post(
        "/api/bets/import",
        files={"file": ("bets.csv", io.BytesIO(csv_body.encode()), "text/csv")},
    )
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["row"] == 2


def test_template_endpoint_returns_csv(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    r = client.get("/api/bets/import/template")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "date,book,sport" in r.text
