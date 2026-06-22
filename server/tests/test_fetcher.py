"""Tests for FetcherRegistry._resolve_keys (A5 — 24h TTL) and gather
semantics (Round-2 perf fixes: bounded fan-out across sport keys + tier
runners under a single per-instance semaphore)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.odds.fetcher import (
    ODDS_API_CONCURRENCY,
    FetcherRegistry,
    _RESOLVED_KEYS_TTL,
)
from server.odds.market_config import TierConfig
from server.sports import Sport


def _make_registry(resolve_return=None, resolve_raises: Exception | None = None):
    """Build a FetcherRegistry with a mock OddsAPIClient."""
    client = MagicMock()
    if resolve_raises is not None:
        client.resolve_sport_keys = AsyncMock(side_effect=resolve_raises)
    else:
        client.resolve_sport_keys = AsyncMock(return_value=resolve_return or [])
    return FetcherRegistry(
        config=MagicMock(),
        sports=[],
        cache=MagicMock(),
        client=client,
        settings_store=MagicMock(),
    ), client


def _sport(key: str = "tennis", odds_api_keys: list[str] | None = None) -> Sport:
    """Build a Sport with the exact dataclass shape (frozen, with
    Path-typed agent_dir and tuple-typed odds_api_sport_keys)."""
    keys = tuple(odds_api_keys) if odds_api_keys else (f"{key}_atp_*",)
    return Sport(
        key=key,
        label=key.upper(),
        odds_api_sport_keys=keys,
        agent_dir=Path("/tmp"),
        markets_config="",
    )


@pytest.mark.asyncio
async def test_first_call_resolves_and_caches():
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    keys = await reg._resolve_keys(sp, now=now)
    assert keys == ["tennis_atp_french_open"]
    assert client.resolve_sport_keys.await_count == 1


@pytest.mark.asyncio
async def test_within_ttl_returns_cached_no_second_call():
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    await reg._resolve_keys(sp, now=now)
    keys = await reg._resolve_keys(sp, now=now + timedelta(hours=23))
    assert keys == ["tennis_atp_french_open"]
    assert client.resolve_sport_keys.await_count == 1


@pytest.mark.asyncio
async def test_after_ttl_re_resolves():
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    await reg._resolve_keys(sp, now=now)
    client.resolve_sport_keys.return_value = ["tennis_atp_wimbledon"]
    keys = await reg._resolve_keys(sp, now=now + timedelta(hours=25))
    assert keys == ["tennis_atp_wimbledon"]
    assert client.resolve_sport_keys.await_count == 2


@pytest.mark.asyncio
async def test_refresh_failure_preserves_cached_keys():
    """A transient refresh failure should NOT overwrite a previously-good
    cached set. The timestamp also stays put so next call retries."""
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    await reg._resolve_keys(sp, now=now)
    client.resolve_sport_keys.side_effect = Exception("network error")
    keys = await reg._resolve_keys(sp, now=now + timedelta(hours=25))
    assert keys == ["tennis_atp_french_open"]
    # Timestamp NOT updated — next call retries even though TTL hasn't elapsed
    client.resolve_sport_keys.side_effect = None
    client.resolve_sport_keys.return_value = ["tennis_atp_wimbledon"]
    keys2 = await reg._resolve_keys(sp, now=now + timedelta(hours=25, minutes=1))
    assert keys2 == ["tennis_atp_wimbledon"]


@pytest.mark.asyncio
async def test_first_call_failure_falls_back_to_static_keys():
    """First-time resolve failure caches the static-key fallback (strips
    pattern entries) so we don't retry-storm on every tier tick."""
    reg, client = _make_registry(resolve_raises=Exception("network error"))
    sp = _sport(odds_api_keys=["baseball_mlb", "tennis_atp_*"])
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    keys = await reg._resolve_keys(sp, now=now)
    assert keys == ["baseball_mlb"]
    keys2 = await reg._resolve_keys(sp, now=now + timedelta(hours=1))
    assert keys2 == ["baseball_mlb"]
    assert client.resolve_sport_keys.await_count == 1


# ---------- _run_main fan-out (Round-2 perf fix #1) ----------


def _make_tier(name: str = "main") -> TierConfig:
    return TierConfig(
        name=name,
        enabled=True,
        interval_seconds=300,
        regions=["us"],
        markets=["h2h"],
    )


@pytest.mark.asyncio
async def test_run_main_fans_out_sport_keys_under_sem():
    """`_run_main` should hit every resolved sport key in parallel, capped
    at `ODDS_API_CONCURRENCY`. We assert two things:

      1) all keys produce a fetch_game_level call (no key dropped)
      2) peak concurrent in-flight calls never exceeds ODDS_API_CONCURRENCY
    """
    sp = _sport(odds_api_keys=["tennis_atp_a", "tennis_atp_b", "tennis_atp_c",
                                "tennis_atp_d", "tennis_atp_e", "tennis_atp_f"])
    reg, client = _make_registry(
        resolve_return=list(sp.odds_api_sport_keys),
    )

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def fake_fetch(*, sport_key: str, markets, regions):
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return [], {"requests_remaining": "100"}

    client.fetch_game_level = AsyncMock(side_effect=fake_fetch)
    # The main path also writes via the cache; stub those out to no-ops.
    reg.cache.upsert = MagicMock()
    reg.cache.purge_finished_games = MagicMock()
    reg.cache.set_status = MagicMock()

    await reg._run_main(sp, _make_tier())

    assert client.fetch_game_level.await_count == 6
    assert peak <= ODDS_API_CONCURRENCY, (
        f"peak concurrent fetch_game_level={peak} exceeded "
        f"ODDS_API_CONCURRENCY={ODDS_API_CONCURRENCY}"
    )


@pytest.mark.asyncio
async def test_run_main_continues_on_per_key_exception():
    """A single bad sport_key (any exception) must NOT abort the cycle —
    we use `return_exceptions=True` so the remaining keys still execute.
    """
    sp = _sport(odds_api_keys=["a", "b", "c"])
    reg, client = _make_registry(resolve_return=list(sp.odds_api_sport_keys))

    async def fake_fetch(*, sport_key: str, markets, regions):
        if sport_key == "b":
            raise RuntimeError("simulated normalize bug")
        return [], {}

    client.fetch_game_level = AsyncMock(side_effect=fake_fetch)
    reg.cache.upsert = MagicMock()
    reg.cache.purge_finished_games = MagicMock()
    reg.cache.set_status = MagicMock()

    # Should complete without raising.
    await reg._run_main(sp, _make_tier())
    # All three keys were attempted (b raised; a and c succeeded).
    assert client.fetch_game_level.await_count == 3
    # Freshness chip still stamped.
    assert reg.cache.set_status.called


@pytest.mark.asyncio
async def test_per_event_uses_instance_sem_not_fresh_one():
    """Regression guard: `_run_per_event` MUST acquire `self._sem`, not a
    freshly-allocated `asyncio.Semaphore(ODDS_API_CONCURRENCY)` per call.
    Hoisting the sem to `__init__` was the whole point of the fix — if a
    fresh sem is created each call, two simultaneous tier ticks
    collectively exceed the plan's req/sec cap."""
    sp = _sport(odds_api_keys=["a"])
    reg, client = _make_registry(resolve_return=["a"])

    # Stub event listing to return a handful of synthetic events.
    reg.cache.distinct_events = MagicMock(
        return_value=[{"event_id": f"evt_{i}"} for i in range(8)]
    )
    reg.cache.upsert = MagicMock()
    reg.cache.set_status = MagicMock()

    # Acquire reg._sem before invoking — capacity 0 → all fetches should
    # block. If `_run_per_event` used a fresh local sem, the calls would
    # proceed; the in-flight assert below would catch the regression.
    for _ in range(ODDS_API_CONCURRENCY):
        await reg._sem.acquire()

    call_count = 0

    async def fake_fetch(*, sport_key, event_id, markets, regions):
        nonlocal call_count
        call_count += 1
        return [], {}

    client.fetch_event_markets = AsyncMock(side_effect=fake_fetch)

    tier = TierConfig(
        name="alternates", enabled=True, interval_seconds=300,
        regions=["us"], markets=["alternate_spreads"],
    )
    task = asyncio.create_task(reg._run_per_event(sp, tier))
    # Give the scheduler a moment to dispatch the sub-tasks. If a fresh
    # sem were used, fetch_event_markets would have been called by now.
    await asyncio.sleep(0.05)
    assert call_count == 0, (
        "fetch_event_markets should be blocked on the drained per-instance "
        f"sem, but it ran {call_count} times — likely a fresh sem is being "
        "created per call."
    )
    # Release the sem so the task can finish (and we don't leak it).
    for _ in range(ODDS_API_CONCURRENCY):
        reg._sem.release()
    await task
    # All 8 events did eventually fetch.
    assert call_count == 8


@pytest.mark.asyncio
async def test_refresh_all_now_caps_concurrent_tier_runners(monkeypatch):
    """`refresh_all_now` must bound the number of simultaneously-executing
    tier runners — otherwise the UI button stacks `len(enabled)` tasks
    (~27) that each fan out further. Cap = ODDS_API_CONCURRENCY."""
    reg, _client = _make_registry()
    reg.config.odds_api_key = "k"

    # Fake out the enabled-tier list so we can drive it with arbitrary
    # fan-out.
    sports_in = [_sport(key=f"sport_{i}", odds_api_keys=[f"k_{i}"]) for i in range(10)]
    tiers = [_make_tier()] * 10
    reg.all_enabled_tiers = MagicMock(
        return_value=list(zip(sports_in, tiers))
    )

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()
    completed = 0

    async def fake_runner():
        nonlocal in_flight, peak, completed
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
            completed += 1

    # Replace _tier_runner with one that returns the instrumented coroutine.
    reg._tier_runner = MagicMock(return_value=fake_runner)

    result = reg.refresh_all_now()
    assert result["status"] == "triggered"
    assert len(result["triggered"]) == 10

    # Let the spawned tasks drain.
    for _ in range(50):
        if completed == 10:
            break
        await asyncio.sleep(0.02)
    assert completed == 10
    assert peak <= ODDS_API_CONCURRENCY, (
        f"refresh_all_now peak concurrent runners={peak} exceeded "
        f"ODDS_API_CONCURRENCY={ODDS_API_CONCURRENCY}"
    )
