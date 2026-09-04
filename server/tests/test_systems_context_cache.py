import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from server.systems.context_cache import SystemContextCache


@pytest.mark.asyncio
async def test_fresh_cache_hit_does_not_call_loader(tmp_path):
    now = datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)
    cache = SystemContextCache(tmp_path / "cache.db", clock=lambda: now)
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return {"week": 1}

    first = await cache.get_or_refresh("espn", "cfb-scoreboard", date(2026, 8, 29), timedelta(minutes=15), loader)
    second = await cache.get_or_refresh("espn", "cfb-scoreboard", date(2026, 8, 29), timedelta(minutes=15), loader)

    assert first.payload == second.payload == {"week": 1}
    assert calls == 1
    assert cache.generation == 1


@pytest.mark.asyncio
async def test_expired_entry_refreshes_and_increments_generation(tmp_path):
    current = [datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)]
    cache = SystemContextCache(tmp_path / "cache.db", clock=lambda: current[0])
    values = iter(({"value": 1}, {"value": 2}))

    async def loader():
        return next(values)

    await cache.get_or_refresh("mlb", "standings", date(2026, 8, 29), timedelta(minutes=5), loader)
    current[0] += timedelta(minutes=6)
    refreshed = await cache.get_or_refresh("mlb", "standings", date(2026, 8, 29), timedelta(minutes=5), loader)

    assert refreshed.payload == {"value": 2}
    assert cache.generation == 2


@pytest.mark.asyncio
async def test_expired_entry_is_served_stale_when_refresh_fails(tmp_path):
    current = [datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)]
    cache = SystemContextCache(tmp_path / "cache.db", clock=lambda: current[0])

    async def initial():
        return {"temperature_f": 88}

    await cache.get_or_refresh("weather", "venue-1", date(2026, 8, 29), timedelta(minutes=5), initial)
    current[0] += timedelta(minutes=6)

    async def failed():
        raise TimeoutError()

    result = await cache.get_or_refresh("weather", "venue-1", date(2026, 8, 29), timedelta(minutes=5), failed)
    assert result.payload == {"temperature_f": 88}
    assert result.is_stale is True
    assert "TimeoutError" in result.warning
    assert "6m old" in result.warning
    assert cache.generation == 1


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_loader_call(tmp_path):
    now = datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)
    cache = SystemContextCache(tmp_path / "cache.db", clock=lambda: now)
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        await asyncio.sleep(.02)
        return {"payload": "once"}

    results = await asyncio.gather(*[
        cache.get_or_refresh("espn", "nfl", date(2026, 8, 29), timedelta(minutes=15), loader)
        for _ in range(5)
    ])
    assert calls == 1
    assert [result.payload for result in results] == [{"payload": "once"}] * 5
