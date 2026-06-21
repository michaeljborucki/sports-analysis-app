from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from server.odds.cache import OddsCache
from server.odds.bets import query_bets


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _fill(**overrides) -> dict:
    """A realistic Kalshi /portfolio/fills entry."""
    base = {
        "fill_id": "fill_abc",
        "ticker": "KXNBA-26JUN21BOSMIA-BOS",
        "side": "yes",
        "price": 45,
        "count": 100,
        "created_time": "2026-06-19T18:00:00Z",
        "is_taker": True,
    }
    base.update(overrides)
    return base


async def _run_sync(cache: OddsCache, fills: list[dict]):
    from server.odds.books.kalshi.portfolio_sync import sync_kalshi_fills
    client = MagicMock()
    client.get_portfolio_fills = AsyncMock(return_value=fills)
    return await sync_kalshi_fills(client=client, cache=cache)


def test_sync_inserts_one_bet_per_fill(cache):
    n = asyncio.run(_run_sync(cache, [_fill(fill_id="a"), _fill(fill_id="b")]))
    assert n == 2
    rows = query_bets(cache, book="kalshi")
    assert {r["external_id"] for r in rows} == {"a", "b"}


def test_sync_translates_price_to_american_odds(cache):
    asyncio.run(_run_sync(cache, [_fill(fill_id="a", price=45, side="yes")]))
    rows = query_bets(cache, book="kalshi")
    assert rows[0]["odds_american"] is not None
    assert rows[0]["odds_american"] > 0


def test_sync_translates_stake_from_price_and_count(cache):
    asyncio.run(_run_sync(cache, [_fill(fill_id="a", price=45, count=100)]))
    rows = query_bets(cache, book="kalshi")
    assert rows[0]["stake"] == pytest.approx(45.0, abs=0.01)


def test_sync_is_idempotent(cache):
    fills = [_fill(fill_id="a")]
    asyncio.run(_run_sync(cache, fills))
    asyncio.run(_run_sync(cache, fills))
    assert len(query_bets(cache, book="kalshi")) == 1
