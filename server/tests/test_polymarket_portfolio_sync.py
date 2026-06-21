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


def _trade(**overrides) -> dict:
    base = {
        "trade_id": "0xabc-1",
        "market": "celtics-vs-heat-2026-06-21",
        "outcome": "Celtics",
        "side": "BUY",
        "price": "0.62",
        "size": "100",
        "timestamp": "2026-06-19T19:00:00Z",
    }
    base.update(overrides)
    return base


async def _run_sync(cache: OddsCache, trades: list[dict], wallet: str = "0xABC"):
    from server.odds.books.polymarket.portfolio_sync import sync_polymarket_trades
    client = MagicMock()
    client.get_user_trades = AsyncMock(return_value=trades)
    return await sync_polymarket_trades(
        client=client, cache=cache, wallet_address=wallet,
    )


def test_sync_inserts_one_bet_per_trade(cache):
    n = asyncio.run(_run_sync(cache, [
        _trade(trade_id="a"), _trade(trade_id="b"),
    ]))
    assert n == 2
    rows = query_bets(cache, book="polymarket")
    assert {r["external_id"] for r in rows} == {"a", "b"}


def test_sync_translates_price_to_american(cache):
    asyncio.run(_run_sync(cache, [_trade(trade_id="a", price="0.62")]))
    rows = query_bets(cache, book="polymarket")
    assert rows[0]["odds_american"] < 0


def test_sync_noop_when_wallet_empty(cache):
    n = asyncio.run(_run_sync(cache, [_trade()], wallet=""))
    assert n == 0


def test_sync_is_idempotent(cache):
    trades = [_trade(trade_id="a")]
    asyncio.run(_run_sync(cache, trades))
    asyncio.run(_run_sync(cache, trades))
    assert len(query_bets(cache, book="polymarket")) == 1
