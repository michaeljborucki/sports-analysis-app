from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from server.odds.latest_snapshot import LatestOddsSnapshotService


NOW = datetime.now(timezone.utc)


def _row(market_key: str, outcome_name: str, *, description=None) -> dict:
    return {
        "event_id": "game-1",
        "sport_key": "mlb",
        "league_key": None,
        "league_title": None,
        "home_team": "Arizona Diamondbacks",
        "away_team": "Philadelphia Phillies",
        "commence_time": (NOW + timedelta(hours=2)).isoformat(),
        "bookmaker_key": "draftkings",
        "market_key": market_key,
        "outcome_name": outcome_name,
        "outcome_point": None,
        "price_american": -110,
        "fetched_at": NOW.isoformat(),
        "wager_type": None,
        "max_stake_dollars": None,
    }


class FakeCache:
    def __init__(self) -> None:
        self.read_version = ("source", 1)
        self.calls = 0
        self.rows = [
            _row("h2h", "Arizona Diamondbacks"),
            _row("batter_hits", "Corbin Carroll Over"),
        ]

    def all_current(self) -> list[dict]:
        self.calls += 1
        time.sleep(0.05)
        return self.rows


@pytest.mark.asyncio
async def test_first_snapshot_captures_rows_games_and_source_version():
    cache = FakeCache()
    service = LatestOddsSnapshotService(cache)

    snapshot = await service.get()

    assert snapshot.generation == 1
    assert snapshot.source_version == ("source", 1)
    assert isinstance(snapshot.rows, tuple)
    assert isinstance(snapshot.games, tuple)
    assert {row["market_key"] for row in snapshot.rows} == {"h2h", "batter_hits"}
    assert {market["market_key"] for market in snapshot.games[0]["markets"]} == {
        "h2h",
        "batter_hits",
    }
    assert cache.calls == 1


@pytest.mark.asyncio
async def test_simultaneous_first_read_builds_the_snapshot_once():
    cache = FakeCache()
    service = LatestOddsSnapshotService(cache)

    first, second = await asyncio.gather(service.get(), service.get())

    assert first is second
    assert cache.calls == 1
