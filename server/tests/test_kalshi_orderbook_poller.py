"""Tests for the Kalshi orderbook poller."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _template_for(event_id: str, outcome_name: str = "BOS") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "event_id": event_id, "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": outcome_name,
        "outcome_point": None,
        "price_american": -145,
        "fetched_at": now,
    }


def test_poll_writes_max_stake_dollars(cache):
    from server.odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
    # Seed a row in the cache so we can verify the upsert lands
    cache.upsert([_template_for("e1")])
    ingestor = MagicMock()
    ingestor.registered_tickers.return_value = ["KX-A"]
    ingestor._templates = {"KX-A": [(_template_for("e1"), "yes")]}
    client = MagicMock()
    client.get_orderbook = AsyncMock(return_value={
        "orderbook": {
            "yes": [[40, 200], [45, 50]],
            "no":  [[55, 150], [58, 80]],
        }
    })
    asyncio.run(poll_kalshi_orderbooks(client=client, ingestor=ingestor, cache=cache))
    rows = cache.all_current()
    assert len(rows) == 1
    # YES side: best NO bid = 58c × 80 → 42c × 80 contracts = $33.60
    assert rows[0]["max_stake_dollars"] == pytest.approx(33.60, abs=0.01)


def test_poll_skips_unknown_tickers(cache):
    from server.odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
    ingestor = MagicMock()
    ingestor.registered_tickers.return_value = ["KX-A"]
    ingestor._templates = {}  # not registered
    client = MagicMock()
    client.get_orderbook = AsyncMock(return_value={"orderbook": {"yes": [], "no": []}})
    # Should not raise even when the ticker has no template
    asyncio.run(poll_kalshi_orderbooks(client=client, ingestor=ingestor, cache=cache))


def test_poll_tolerates_client_failure(cache):
    from server.odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
    cache.upsert([_template_for("e1", "BOS"), _template_for("e2", "OKC")])
    ingestor = MagicMock()
    ingestor.registered_tickers.return_value = ["KX-A", "KX-B"]
    ingestor._templates = {
        "KX-A": [(_template_for("e1", "BOS"), "yes")],
        "KX-B": [(_template_for("e2", "OKC"), "yes")],
    }
    client = MagicMock()
    client.get_orderbook = AsyncMock(side_effect=[
        Exception("kaboom"),
        {"orderbook": {"yes": [[40, 100]], "no": [[55, 100]]}},
    ])
    asyncio.run(poll_kalshi_orderbooks(client=client, ingestor=ingestor, cache=cache))
    rows = cache.all_current()
    # KX-B should have been updated despite KX-A failing
    sizes = [r["max_stake_dollars"] for r in rows]
    assert any(s is not None for s in sizes)
