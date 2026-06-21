"""Tests for the Kalshi orderbook → max_stake_dollars translator."""
import json
from pathlib import Path

import pytest


SAMPLE = {
    "orderbook": {
        "yes": [
            [40, 200],
            [42, 100],
            [45, 50],
        ],
        "no": [
            [55, 150],
            [58, 80],
        ],
    }
}


def test_yes_side_size_from_no_bids():
    """A row with ws_side='yes' needs the YES ASK, derived from the
    best NO BID: yes_ask_cents = 100 - best_no_bid_cents.
    Best NO bid = 58c, size 80 → yes_ask = 42c, size = 80 contracts.
    max_stake_dollars = 0.42 * 80 = 33.60.
    """
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    result = max_stake_for_side(SAMPLE, ws_side="yes")
    assert result == pytest.approx(33.60, abs=0.01)


def test_no_side_size_from_yes_bids():
    """ws_side='no' needs the NO ASK from the best YES BID:
    Best YES bid = 45c, size 50 → no_ask = 55c, size = 50.
    max_stake_dollars = 0.55 * 50 = 27.50.
    """
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    result = max_stake_for_side(SAMPLE, ws_side="no")
    assert result == pytest.approx(27.50, abs=0.01)


def test_empty_opposite_side_returns_none():
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    empty = {"orderbook": {"yes": [], "no": []}}
    assert max_stake_for_side(empty, ws_side="yes") is None


def test_malformed_orderbook_returns_none():
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    assert max_stake_for_side({}, ws_side="yes") is None
    assert max_stake_for_side({"orderbook": {}}, ws_side="yes") is None
    assert max_stake_for_side(None, ws_side="yes") is None


def test_dict_format_entries_also_supported():
    """Some Kalshi responses use [{price, size}] dict format; we
    tolerate both."""
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    sample = {"orderbook": {
        "no": [
            {"price": 58, "size": 80},
        ],
        "yes": [],
    }}
    result = max_stake_for_side(sample, ws_side="yes")
    assert result == pytest.approx(33.60, abs=0.01)


def test_fixture_loads_and_parses():
    """Smoke-test against the bundled fixture."""
    from server.odds.books.kalshi.orderbook_depth import max_stake_for_side
    path = Path(__file__).parent / "fixtures" / "kalshi_orderbook.json"
    data = json.loads(path.read_text())
    for side in ("yes", "no"):
        result = max_stake_for_side(data, ws_side=side)
        assert result is None or result > 0
