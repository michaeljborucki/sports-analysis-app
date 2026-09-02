from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from server.odds.latest_snapshot import LatestOddsSnapshotService
from scripts.benchmark_critical_pages import Measurement, format_measurements


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
    assert {
        market["market_key"]
        for market in snapshot.non_prop_games[0]["markets"]
    } == {"h2h"}
    assert cache.calls == 1


@pytest.mark.asyncio
async def test_simultaneous_first_read_builds_the_snapshot_once():
    cache = FakeCache()
    service = LatestOddsSnapshotService(cache)

    first, second = await asyncio.gather(service.get(), service.get())

    assert first is second
    assert cache.calls == 1


@pytest.mark.asyncio
async def test_changed_source_serves_current_snapshot_while_one_refresh_runs():
    cache = FakeCache()
    service = LatestOddsSnapshotService(cache, refresh_interval_seconds=60)
    first = await service.get()
    cache.read_version = ("source", 2)

    started = time.perf_counter()
    stale_one, stale_two = await asyncio.gather(service.get(), service.get())
    elapsed = time.perf_counter() - started

    assert stale_one is first
    assert stale_two is first
    assert elapsed < 0.03
    assert service.refreshing is True
    await service.wait_until_idle()
    current = await service.get()
    assert current.generation == 2
    assert current.source_version == ("source", 2)
    assert cache.calls == 2


@pytest.mark.asyncio
async def test_failed_refresh_keeps_last_good_snapshot_and_records_error():
    cache = FakeCache()
    service = LatestOddsSnapshotService(cache)
    first = await service.get()
    cache.read_version = ("source", 2)

    def fail() -> list[dict]:
        cache.calls += 1
        raise RuntimeError("snapshot source unavailable")

    cache.all_current = fail
    assert await service.get() is first
    await service.wait_until_idle()

    assert service.current is first
    assert service.last_error == "snapshot source unavailable"


@pytest.mark.asyncio
async def test_start_and_stop_manage_one_background_loop():
    cache = FakeCache()
    service = LatestOddsSnapshotService(cache, refresh_interval_seconds=0.01)

    await service.start()
    assert service.current is not None
    assert service.running is True

    await service.stop()
    assert service.running is False


def test_benchmark_formatter_reports_latency_status_and_size():
    output = format_measurements([
        Measurement("health", 200, 0.027, 457),
        Measurement("edges-arb", 200, 0.429, 140_994),
    ])

    assert output.splitlines() == [
        "endpoint\tstatus\tseconds\tbytes",
        "health\t200\t0.027\t457",
        "edges-arb\t200\t0.429\t140994",
    ]
