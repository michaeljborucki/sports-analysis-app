"""Tests for FetcherRegistry._resolve_keys (A5 — 24h TTL)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.odds.fetcher import FetcherRegistry, _RESOLVED_KEYS_TTL
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
