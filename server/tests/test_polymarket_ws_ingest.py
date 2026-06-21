"""Tests for the Polymarket WS ingestor's depth-capture path."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.odds.books.polymarket.ws_ingest import PolymarketIngestor
from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _template_row(asset_id: str) -> dict:
    now = datetime(2026, 6, 21, tzinfo=timezone.utc)
    return {
        "_asset_id": asset_id,
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -150,
        "fetched_at": now,
    }


def test_book_message_captures_max_stake_dollars(cache):
    ing = PolymarketIngestor(cache=cache)
    ing.register_rows([_template_row("0xabc")])
    msg = {
        "event_type": "book",
        "asset_id": "0xabc",
        "asks": [
            {"price": "0.70", "size": "500"},
            {"price": "0.65", "size": "1000"},
            {"price": "0.62", "size": "234.5"},  # min price → best ask
        ],
        "timestamp": "1782070000000",
    }
    n = ing.process_message(msg)
    assert n == 1
    rows = cache.all_current()
    # best ask = 0.62, size = 234.5 → 0.62 * 234.5 = 145.39
    assert rows[0]["max_stake_dollars"] == pytest.approx(145.39, abs=0.01)


def test_book_message_with_no_asks_keeps_max_stake_null(cache):
    ing = PolymarketIngestor(cache=cache)
    ing.register_rows([_template_row("0xabc")])
    msg = {"event_type": "book", "asset_id": "0xabc", "asks": []}
    n = ing.process_message(msg)
    assert n == 0


def test_price_change_leaves_max_stake_dollars_unchanged(cache):
    """Polymarket delta messages don't carry size; we leave the existing
    max_stake_dollars in place rather than nulling it (via COALESCE in
    cache.upsert)."""
    ing = PolymarketIngestor(cache=cache)
    ing.register_rows([_template_row("0xabc")])
    # First, a book message sets size
    ing.process_message({
        "event_type": "book", "asset_id": "0xabc",
        "asks": [{"price": "0.62", "size": "100"}],
        "timestamp": "1782070000000",
    })
    # Then a price_change updates only price
    ing.process_message({
        "event_type": "price_change",
        "asset_id": "0xabc",
        "price_changes": [
            {"asset_id": "0xabc", "best_ask": "0.60", "best_bid": "0.55"}
        ],
        "timestamp": "1782070001000",
    })
    rows = cache.all_current()
    # Size from the first book event should persist; only price changed
    assert rows[0]["max_stake_dollars"] == pytest.approx(62.0, abs=0.01)
