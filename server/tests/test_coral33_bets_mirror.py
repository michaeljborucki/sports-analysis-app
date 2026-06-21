from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from server.odds.cache import OddsCache
from server.odds.bets import query_bets
from server.odds.books.coral33.wager_log import WagerLogEntry


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _wager(**overrides) -> WagerLogEntry:
    base = dict(
        customer_id="cust1",
        ticket_number=12345,
        accepted_at=datetime(2026, 6, 19, 18, 0, tzinfo=timezone.utc),
        settled_at=None, wager_status="O", wager_type="S",
        total_picks=1, amount_wagered=50.0, to_win_amount=34.5,
        amount_won=0.0, amount_lost=0.0, is_free_play=False,
        sport_type="Baseball", sport_sub_type="MLB",
        period=None, team1_id="Dodgers", team2_id="Giants",
        chosen_team_id="Dodgers", description="Dodgers ML",
        final_money=-145, adj_spread=0.0, adj_total_points=0.0,
    )
    base.update(overrides)
    return WagerLogEntry(**base)


def test_mirror_writes_one_row_per_ticket(cache):
    from server.odds.books.coral33.bets_mirror import (
        mirror_coral33_wager_log_to_bets,
    )
    wagers_by_cid = {
        "cust1": [_wager(ticket_number=1), _wager(ticket_number=2)],
    }
    n = mirror_coral33_wager_log_to_bets(cache, wagers_by_cid)
    assert n == 2
    rows = query_bets(cache, book="coral33")
    assert {r["external_id"] for r in rows} == {"1", "2"}


def test_mirror_is_idempotent_on_rerun(cache):
    from server.odds.books.coral33.bets_mirror import (
        mirror_coral33_wager_log_to_bets,
    )
    w = {"cust1": [_wager(ticket_number=1)]}
    mirror_coral33_wager_log_to_bets(cache, w)
    mirror_coral33_wager_log_to_bets(cache, w)
    assert len(query_bets(cache, book="coral33")) == 1


def test_mirror_updates_status_on_settlement(cache):
    from server.odds.books.coral33.bets_mirror import (
        mirror_coral33_wager_log_to_bets,
    )
    open_w = {"cust1": [_wager(ticket_number=1, wager_status="O")]}
    mirror_coral33_wager_log_to_bets(cache, open_w)
    settled_w = {"cust1": [_wager(
        ticket_number=1, wager_status="W",
        amount_won=84.5,
        settled_at=datetime(2026, 6, 19, 22, 0, tzinfo=timezone.utc),
    )]}
    mirror_coral33_wager_log_to_bets(cache, settled_w)
    rows = query_bets(cache, book="coral33")
    assert len(rows) == 1
    assert rows[0]["status"] == "win"
    assert rows[0]["settled_amount"] == 134.5
