from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import arbitrage, ev, free_bets, low_hold, profit_boost


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
