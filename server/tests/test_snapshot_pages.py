from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.odds import build_router as odds_router
from server.api.systems import build_router as systems_router
from server.odds.cache import OddsCache
from server.odds.normalize import rows_to_games
from server.systems.store import SystemSignalStore


NOW = datetime.now(timezone.utc)


def _mlb_row(outcome: str, price: int) -> dict:
    return {
        "event_id": "mlb-game",
        "sport_key": "mlb",
        "league_key": None,
        "league_title": None,
        "home_team": "Arizona Diamondbacks",
        "away_team": "Philadelphia Phillies",
        "commence_time": NOW + timedelta(hours=2),
        "bookmaker_key": "draftkings",
        "market_key": "h2h",
        "outcome_name": outcome,
        "outcome_point": None,
        "price_american": price,
        "fetched_at": NOW,
        "wager_type": None,
        "max_stake_dollars": None,
    }


class FakeSnapshotService:
    def __init__(self) -> None:
        games = tuple(rows_to_games([
            _mlb_row("Arizona Diamondbacks", 120),
            _mlb_row("Philadelphia Phillies", -130),
        ], now=NOW))
        self.snapshot = SimpleNamespace(
            generation=3,
            non_prop_games_by_sport={"mlb": games},
            system_rows=tuple(),
        )

    async def get(self):
        return self.snapshot


def test_odds_endpoint_uses_snapshot_without_reading_source_cache():
    cache = MagicMock()
    cache.all_current_family.side_effect = AssertionError("legacy cache read")
    cache.get_status.return_value = {}
    app = FastAPI()
    app.include_router(odds_router(cache, FakeSnapshotService()))

    response = TestClient(app).get("/api/odds/mlb")

    assert response.status_code == 200
    assert [game["event_id"] for game in response.json()["games"]] == [
        "mlb-game"
    ]
    cache.all_current_family.assert_not_called()


def test_systems_endpoint_uses_snapshot_rows_without_reading_source_cache(
    tmp_path,
):
    cache = OddsCache(tmp_path / "cache.db")
    cache.init()
    cache.all_current_markets = MagicMock(
        side_effect=AssertionError("legacy cache read")
    )
    snapshots = FakeSnapshotService()
    snapshots.snapshot.system_rows = (
        _mlb_row("Arizona Diamondbacks", 120),
        _mlb_row("Philadelphia Phillies", -130),
    )

    async def no_context(games, requested_date):
        return {}, []

    app = FastAPI()
    app.include_router(systems_router(
        cache,
        signal_store=SystemSignalStore(cache.path),
        context_enricher=no_context,
        now_fn=lambda: NOW,
        snapshot_service=snapshots,
    ))

    response = TestClient(app).get(f"/api/systems?date={NOW.date().isoformat()}")

    assert response.status_code == 200
    cache.all_current_markets.assert_not_called()
