import sqlite3
import time
import pytest
from server.odds.cache import init_schema_on_path
from server.sidecar.active_signals import (
    arm_signal, update_total_placed, list_active, get_signal,
)
from server.sidecar.settings import KellyFraction


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    c = sqlite3.connect(path)
    yield c
    c.close()


def test_arm_signal_inserts_row(conn):
    arm_signal(
        conn, ev_row_id="rid-1", kelly_fraction=KellyFraction.HALF,
        bankroll_at_arm=10000, commence_time=int(time.time()) + 3600,
    )
    sig = get_signal(conn, "rid-1")
    assert sig.kelly_fraction == "half"
    assert sig.bankroll_at_arm == 10000
    assert sig.total_placed == 0


def test_arm_signal_is_idempotent(conn):
    """Calling arm twice on the same row_id does NOT reset total_placed."""
    now = int(time.time())
    arm_signal(conn, "rid-2", KellyFraction.HALF, 10000, now + 3600)
    update_total_placed(conn, "rid-2", 130)
    arm_signal(conn, "rid-2", KellyFraction.HALF, 10000, now + 3600)
    assert get_signal(conn, "rid-2").total_placed == 130


def test_list_active_filters_by_commence_time(conn):
    now = int(time.time())
    arm_signal(conn, "future", KellyFraction.HALF, 10000, now + 3600)
    arm_signal(conn, "past", KellyFraction.HALF, 10000, now - 60)
    active = list_active(conn, now=now)
    ids = {s.ev_row_id for s in active}
    assert "future" in ids
    assert "past" not in ids


def test_update_total_placed_accumulates(conn):
    now = int(time.time())
    arm_signal(conn, "rid-3", KellyFraction.HALF, 10000, now + 3600)
    update_total_placed(conn, "rid-3", 100)
    update_total_placed(conn, "rid-3", 30)
    assert get_signal(conn, "rid-3").total_placed == 130
