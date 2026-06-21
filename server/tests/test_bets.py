from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from server.odds.cache import OddsCache
from server.odds.bets import BetRow, upsert_bets, query_bets


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _row(**overrides) -> BetRow:
    base = BetRow(
        source_book="coral33", external_id="t1", customer_id="cust1",
        accepted_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        settled_at=None, status="open", wager_type="straight",
        total_picks=1, sport_key="mlb", event_id="ev1",
        home_team="LAD", away_team="SF", market_key="h2h",
        outcome_name="LAD", outcome_point=0.0, odds_american=-145,
        stake=50.0, to_win=34.5, settled_amount=None,
        is_free_play=False, raw_description=None, imported_at=None,
    )
    return base.replace(**overrides)


def test_upsert_inserts_new_row(cache):
    upsert_bets(cache, [_row()])
    rows = query_bets(cache)
    assert len(rows) == 1
    assert rows[0]["source_book"] == "coral33"
    assert rows[0]["external_id"] == "t1"


def test_upsert_is_idempotent(cache):
    upsert_bets(cache, [_row()])
    upsert_bets(cache, [_row()])
    rows = query_bets(cache)
    assert len(rows) == 1


def test_upsert_updates_status_on_repeat(cache):
    upsert_bets(cache, [_row(status="open")])
    upsert_bets(cache, [_row(status="win", settled_amount=84.5)])
    rows = query_bets(cache)
    assert len(rows) == 1
    assert rows[0]["status"] == "win"
    assert rows[0]["settled_amount"] == 84.5


def test_query_filters_by_book(cache):
    upsert_bets(cache, [
        _row(source_book="coral33", external_id="a"),
        _row(source_book="kalshi", external_id="b"),
    ])
    rows = query_bets(cache, book="kalshi")
    assert len(rows) == 1
    assert rows[0]["source_book"] == "kalshi"


def test_query_filters_by_status(cache):
    upsert_bets(cache, [
        _row(external_id="a", status="open"),
        _row(external_id="b", status="win"),
    ])
    rows = query_bets(cache, status="win")
    assert {r["external_id"] for r in rows} == {"b"}
