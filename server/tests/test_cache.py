from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


def test_upsert_and_read_single_row(cache: OddsCache):
    now = datetime.now(timezone.utc)
    cache.upsert([
        {
            "event_id": "evt_1",
            "home_team": "Yankees", "away_team": "Red Sox",
            "commence_time": now,
            "bookmaker_key": "draftkings",
            "market_key": "h2h",
            "outcome_name": "Yankees",
            "outcome_point": None,
            "price_american": -138,
            "fetched_at": now,
        }
    ])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -138


def test_upsert_overwrites_same_key(cache: OddsCache):
    now = datetime.now(timezone.utc)
    base = {
        "event_id": "evt_1",
        "home_team": "Yankees", "away_team": "Red Sox",
        "commence_time": now,
        "bookmaker_key": "draftkings",
        "market_key": "h2h",
        "outcome_name": "Yankees",
        "outcome_point": None,
        "fetched_at": now,
    }
    cache.upsert([{**base, "price_american": -138}])
    cache.upsert([{**base, "price_american": -140}])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -140


def test_status_upsert(cache: OddsCache):
    now = datetime.now(timezone.utc)
    cache.set_status(last_fetch_at=now, requests_remaining=500)
    status = cache.get_status()
    assert status is not None
    assert status["requests_remaining"] == 500


def test_version_increments_on_upsert(cache: OddsCache):
    """The monotonic version counter must bump on every state-changing op
    so scanner endpoints can use it as a cheap cache-fingerprint."""
    now = datetime.now(timezone.utc)
    base_row = {
        "event_id": "evt_1",
        "home_team": "Yankees", "away_team": "Red Sox",
        "commence_time": now,
        "bookmaker_key": "draftkings",
        "market_key": "h2h",
        "outcome_name": "Yankees",
        "outcome_point": None,
        "price_american": -138,
        "fetched_at": now,
    }

    # Starts at zero.
    assert cache.version == 0

    # Each upsert call bumps by exactly one (per-call, not per-row).
    cache.upsert([base_row])
    assert cache.version == 1

    cache.upsert([base_row, {**base_row, "outcome_name": "Red Sox", "price_american": 120}])
    assert cache.version == 2

    # Empty input is a no-op — must NOT bump (would needlessly invalidate
    # scanner memos every quiet poll cycle).
    cache.upsert([])
    assert cache.version == 2

    # Purges that actually delete rows bump too.
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    removed = cache.purge_finished_games(now=far_future, past_hours=0)
    assert removed > 0
    assert cache.version == 3

    # Purges that delete nothing don't bump.
    removed = cache.purge_finished_games(now=far_future, past_hours=0)
    assert removed == 0
    assert cache.version == 3


def test_version_bumps_on_stale_and_book_purge(cache: OddsCache):
    """purge_stale_rows and purge_live_rows_for_book also alter scanner
    state, so they must bump the version when they actually delete rows."""
    now = datetime.now(timezone.utc)
    cache.upsert([
        {
            "event_id": "evt_1",
            "home_team": "A", "away_team": "B",
            "commence_time": now,
            "bookmaker_key": "coral33",
            "market_key": "h2h",
            "outcome_name": "A",
            "outcome_point": None,
            "price_american": 110,
            "fetched_at": now,
        }
    ])
    v_after_upsert = cache.version

    # The row's `fetched_at` is "now" — purge with a future cutoff so its
    # age exceeds max_age_seconds=0.
    from datetime import timedelta
    future = now + timedelta(hours=1)
    removed = cache.purge_stale_rows(now=future, max_age_seconds=0)
    assert removed == 1
    assert cache.version == v_after_upsert + 1

    # Re-seed and exercise the live-rows purge.
    cache.upsert([
        {
            "event_id": "evt_2",
            "home_team": "A", "away_team": "B",
            "commence_time": now,
            "bookmaker_key": "coral33",
            "market_key": "h2h",
            "outcome_name": "A",
            "outcome_point": None,
            "price_american": 110,
            "fetched_at": now,
        }
    ])
    v_before_live = cache.version
    removed = cache.purge_live_rows_for_book("coral33", future)
    assert removed == 1
    assert cache.version == v_before_live + 1
