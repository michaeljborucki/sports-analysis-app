from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import arbitrage, ev, free_bets, low_hold, profit_boost
from server.odds.latest_snapshot import LatestOddsSnapshotService


class FakeSnapshotService:
    def __init__(self) -> None:
        self.calls = 0
        self.snapshot = SimpleNamespace(
            generation=7,
            games=(),
            non_prop_games=(),
        )

    async def get(self):
        self.calls += 1
        return self.snapshot


def test_all_edge_endpoints_use_the_shared_snapshot_without_reading_cache():
    cache = MagicMock()
    cache.path = "/tmp/test-cache.db"
    cache.all_current.side_effect = AssertionError("legacy cache read")
    snapshots = FakeSnapshotService()
    app = FastAPI()
    for router in (
        arbitrage.build_router(cache, snapshots),
        low_hold.build_router(cache, snapshots),
        ev.build_router(cache, snapshots),
        free_bets.build_router(cache, snapshots),
        profit_boost.build_router(cache, snapshots),
    ):
        app.include_router(router)

    with TestClient(app) as client:
        for path in (
            "/api/arbitrage",
            "/api/low-hold",
            "/api/ev",
            "/api/free-bets",
            "/api/profit_boost",
        ):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)

    assert snapshots.calls == 5
    cache.all_current.assert_not_called()


@pytest.mark.parametrize("endpoint,router", [
    ("/api/arbitrage", arbitrage),
    ("/api/low-hold", low_hold),
])
def test_pair_endpoints_include_player_props_from_shared_snapshot(endpoint, router):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    rows = [
        {
            "event_id": "prop-game", "sport_key": "mlb",
            "home_team": "Home", "away_team": "Away",
            "commence_time": (now + timedelta(hours=2)).isoformat(),
            "bookmaker_key": book, "market_key": "batter_hits",
            "outcome_name": name, "outcome_point": 1.5,
            "price_american": 110, "fetched_at": now.isoformat(),
            "wager_type": "both" if book == "coral33" else None,
        }
        for book, name in [
            ("coral33", "Jane Doe Over"),
            ("fanduel", "Jane Doe Under"),
            # A different player's unmatched side must not create a pair.
            ("coral33", "Other Player Over"),
        ]
    ]
    cache = MagicMock()
    cache.path = "/tmp/props-snapshot-test.db"
    cache.read_version = 1
    cache.all_current.return_value = rows
    snapshots = LatestOddsSnapshotService(cache)
    app = FastAPI()
    app.include_router(router.build_router(cache, snapshots))

    with TestClient(app) as client:
        response = client.get(endpoint, params={"books": "coral33,fanduel"})

    assert response.status_code == 200
    opportunities = response.json()["opportunities"]
    assert len(opportunities) == 1
    prop = opportunities[0]
    assert prop["market_kind"] == "batter_hits"
    assert prop["point"] == 1.5
    assert {side["outcome_name"] for side in prop["sides"]} == {
        "jane doe Over", "jane doe Under",
    }
    assert next(s for s in prop["sides"] if s["book"] == "coral33")["wager_type"] == "both"
