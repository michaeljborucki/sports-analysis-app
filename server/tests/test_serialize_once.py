"""Scanner endpoints render their JSON once (in the threadpool) and memoize
the bytes. The response must stay byte-identical to what FastAPI produced
when the handlers returned pydantic models through `response_model=`.

Each test fetches the endpoint, re-parses the body into the declared
response model, serves that model through a plain `response_model=` route
(the previous code path) and requires the exact same bytes back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from server.api import arbitrage, dashboard, ev, free_bets, low_hold, profit_boost
from server.api.serialization import model_json_bytes
from server.odds.cache import OddsCache
from server.odds.latest_snapshot import LatestOddsSnapshotService
from server.sports import all_sports


class _StubFetcher:
    is_running = False

    def all_enabled_tiers(self):
        return []


def _rows(now: datetime) -> list[dict]:
    """Two MLB games with a sharp anchor and soft books priced so that every
    scanner (arb, low-hold, EV, free-bet, profit-boost) has output. Unicode
    team names exercise `ensure_ascii=False`."""
    out: list[dict] = []
    games = [
        ("evt_a", "Yankees", "Red Sox", now + timedelta(hours=1)),
        ("evt_b", "Señores de Nueva York", "Atlético Boston", now + timedelta(hours=2)),
        # No arb here, but a +EV DraftKings line: EV rows tagged
        # also_in_arb=False.
        ("evt_c", "Cubs", "Mets", now + timedelta(hours=2, minutes=30)),
    ]
    arb_prices = {
        # book: (home h2h, away h2h, home -1.5, away +1.5)
        "pinnacle": (-105, -105, 150, -170),
        "draftkings": (120, -140, 165, -200),
        "fanduel": (-150, 125, 130, -150),
        "betmgm": (-110, -110, 145, -175),
    }
    quiet_prices = {
        "pinnacle": (-110, -110, 150, -170),
        "draftkings": (103, -125, 152, -185),
        "fanduel": (-115, -105, 140, -175),
        "betmgm": (-110, -110, 145, -175),
    }
    for event_id, home, away, ct in games:
        prices = quiet_prices if event_id == "evt_c" else arb_prices
        for book, (h, a, hs, as_) in prices.items():
            base = {
                "event_id": event_id, "sport_key": "mlb",
                "home_team": home, "away_team": away,
                "commence_time": ct, "bookmaker_key": book,
                "fetched_at": now,
            }
            out += [
                {**base, "market_key": "h2h", "outcome_name": home,
                 "outcome_point": None, "price_american": h},
                {**base, "market_key": "h2h", "outcome_name": away,
                 "outcome_point": None, "price_american": a},
                {**base, "market_key": "spreads", "outcome_name": home,
                 "outcome_point": -1.5, "price_american": hs},
                {**base, "market_key": "spreads", "outcome_name": away,
                 "outcome_point": 1.5, "price_american": as_},
            ]
    return out


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    c.upsert(_rows(datetime.now(timezone.utc)))
    return c


def _assert_same_as_model_path(body: bytes, model_cls: type[BaseModel]) -> None:
    parsed = model_cls.model_validate_json(body)
    legacy = FastAPI()

    @legacy.get("/legacy", response_model=model_cls)
    def _legacy():
        return parsed

    with TestClient(legacy) as lc:
        assert lc.get("/legacy").content == body


ENDPOINTS = [
    ("/api/arbitrage", arbitrage, arbitrage.ArbResponse),
    ("/api/low-hold", low_hold, low_hold.LowHoldResponse),
    ("/api/ev", ev, ev.EVResponse),
    ("/api/free-bets", free_bets, free_bets.FreeBetResponse),
    ("/api/profit_boost", profit_boost, profit_boost.ProfitBoostResponse),
]


@pytest.mark.parametrize("use_snapshot", [False, True])
@pytest.mark.parametrize("path,module,model_cls", ENDPOINTS)
def test_scanner_bytes_match_response_model_serialization(
    cache, path, module, model_cls, use_snapshot,
):
    snapshots = LatestOddsSnapshotService(cache) if use_snapshot else None
    app = FastAPI()
    app.include_router(module.build_router(cache, snapshots))
    with TestClient(app) as client:
        first = client.get(path)
        memo_hit = client.get(path)

    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "application/json"
    body = first.content
    assert first.json()["opportunities"], f"fixture produced no {path} rows"
    # Memo hits serve the very same bytes.
    assert memo_hit.content == body
    _assert_same_as_model_path(body, model_cls)


def test_dashboard_bytes_match_response_model_serialization(cache):
    app = FastAPI()
    app.include_router(
        dashboard.build_router(cache, _StubFetcher(), all_sports())
    )
    with TestClient(app) as client:
        r = client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["top_arbs"] and data["upcoming_games"]
    _assert_same_as_model_path(r.content, dashboard.DashboardResponse)


def test_dashboard_upcoming_games_are_slim(cache):
    """Starting-soon rows carry only the header fields the card renders —
    no markets tree."""
    app = FastAPI()
    app.include_router(
        dashboard.build_router(cache, _StubFetcher(), all_sports())
    )
    with TestClient(app) as client:
        games = client.get("/api/dashboard").json()["upcoming_games"]
    assert [g["event_id"] for g in games] == ["evt_a", "evt_b", "evt_c"]
    for g in games:
        assert set(g) == {
            "event_id", "sport_key", "home_team", "away_team", "commence_time",
        }


def test_model_json_bytes_matches_fastapi_on_float_and_unicode_edges():
    """Pydantic's `model_dump_json` writes 1e-05 as 0.00001; FastAPI (via
    json.dumps) writes 1e-05. The helper must follow FastAPI."""

    class Edge(BaseModel):
        tiny: float
        huge: float
        neg_zero: float
        name: str
        when: datetime
        maybe: float | None = None

    m = Edge(
        tiny=1e-05, huge=1e16, neg_zero=-0.0, name="Señor “quotes” ⚾",
        when=datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc),
    )
    app = FastAPI()

    @app.get("/edge", response_model=Edge)
    def _edge():
        return m

    with TestClient(app) as c:
        assert c.get("/edge").content == model_json_bytes(m)


# ────────── /api/ev arb pre-scan: once per snapshot generation ──────────

def test_ev_arb_prescan_runs_once_per_snapshot_generation(cache, monkeypatch):
    import server.odds.arbitrage as arb_odds

    calls = {"n": 0}
    real_scan = arb_odds.scan_all_arbs

    def counting_scan(*args, **kwargs):
        calls["n"] += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(arb_odds, "scan_all_arbs", counting_scan)

    snapshots = LatestOddsSnapshotService(cache, refresh_interval_seconds=0)
    app = FastAPI()
    app.include_router(ev.build_router(cache, snapshots))
    with TestClient(app) as client:
        # Distinct query params = distinct EV memo keys = distinct scans,
        # but one shared arb pre-scan.
        for min_ev in (0.5, 1.0, 2.0):
            assert client.get("/api/ev", params={"min_ev": min_ev}).status_code == 200
        assert client.get("/api/ev", params={"sort": "asc"}).status_code == 200
        assert calls["n"] == 1
        # tag_arb=false never needs it.
        client.get("/api/ev", params={"tag_arb": "false"})
        assert calls["n"] == 1

        # New data -> new snapshot generation -> exactly one more pre-scan.
        now = datetime.now(timezone.utc)
        cache.upsert([{**r, "price_american": r["price_american"] + 1}
                      for r in _rows(now)[:2]])
        cache._flush_version_now()  # what version_flush_loop does in prod
        client.get("/api/ev", params={"min_ev": 0.5})  # kicks the rebuild
        client.portal.call(snapshots.wait_until_idle)
        assert snapshots.current.generation == 2
        client.get("/api/ev", params={"min_ev": 0.5})
        client.get("/api/ev", params={"min_ev": 1.0})
        assert calls["n"] == 2


def test_ev_arb_tags_identical_with_memoized_prescan(cache):
    """Snapshot path (memoized arb keys) and the inline path (fresh
    scan_all_arbs per request) tag exactly the same rows."""
    def _opps(snapshots):
        app = FastAPI()
        app.include_router(ev.build_router(cache, snapshots))
        with TestClient(app) as client:
            return client.get("/api/ev", params={"min_ev": 0}).json()["opportunities"]

    memoized = _opps(LatestOddsSnapshotService(cache))
    inline = _opps(None)
    assert memoized == inline
    assert any(o["also_in_arb"] for o in memoized)
    assert any(not o["also_in_arb"] for o in memoized)
