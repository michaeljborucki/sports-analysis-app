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


def test_bets_table_created(tmp_path):
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(bets)")}
    assert {
        "source_book", "external_id", "customer_id", "accepted_at",
        "settled_at", "status",
        "wager_type", "total_picks", "sport_key", "event_id",
        "home_team", "away_team", "market_key", "outcome_name",
        "outcome_point", "odds_american", "stake", "to_win",
        "settled_amount", "is_free_play", "raw_description", "imported_at",
    }.issubset(cols)


def test_bets_indexes_created(tmp_path):
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_bets_accepted", "idx_bets_event", "idx_bets_book", "idx_bets_status"}.issubset(names)


def test_max_stake_dollars_column_exists(tmp_path):
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(odds_snapshot)")}
    assert "max_stake_dollars" in cols


def test_upsert_persists_max_stake_dollars(tmp_path):
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -145, "fetched_at": now,
        "max_stake_dollars": 234.50,
    }])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["max_stake_dollars"] == 234.50


def test_upsert_without_max_stake_dollars_is_null(tmp_path):
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "draftkings",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "price_american": -145, "fetched_at": now,
    }])
    rows = cache.all_current()
    assert rows[0]["max_stake_dollars"] is None


def test_price_change_preserves_max_stake_via_coalesce(tmp_path):
    """A book event sets size; a follow-up upsert with max_stake=None
    must preserve the prior non-null value (COALESCE in DO UPDATE SET)."""
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    base = {
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now,
        "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None,
        "fetched_at": now,
    }
    cache.upsert([{**base, "price_american": -150, "max_stake_dollars": 100.0}])
    cache.upsert([{**base, "price_american": -148}])  # no max_stake_dollars
    rows = cache.all_current()
    assert rows[0]["price_american"] == -148
    assert rows[0]["max_stake_dollars"] == 100.0  # preserved


def test_purge_live_rows_grace_window_preserves_recent(tmp_path):
    """Rows whose commence_time is within `grace_seconds` of now should
    NOT be purged — they may be delayed / soft-start games."""
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    recent = {
        "event_id": "ev_recent", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now - timedelta(minutes=10),
        "bookmaker_key": "coral33",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -145,
        "fetched_at": now,
    }
    old = {**recent, "event_id": "ev_old",
           "commence_time": now - timedelta(minutes=45)}
    cache.upsert([recent, old])
    removed = cache.purge_live_rows_for_book("coral33", now, grace_seconds=1800)
    assert removed == 1
    remaining = {r["event_id"] for r in cache.all_current()}
    assert "ev_recent" in remaining
    assert "ev_old" not in remaining


def test_purge_live_rows_default_grace_is_zero(tmp_path):
    """Without grace_seconds (existing call sites), behavior is
    unchanged — anything with commence_time <= now is purged."""
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    row = {
        "event_id": "ev_at_kickoff", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now - timedelta(seconds=1),
        "bookmaker_key": "coral33",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -145,
        "fetched_at": now,
    }
    cache.upsert([row])
    removed = cache.purge_live_rows_for_book("coral33", now)
    assert removed == 1


# ─────────────────── A8: distinct_events SQL pushdown ─────────────────


def test_distinct_events_no_filter_returns_all(tmp_path):
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "event_id": f"ev_{i}", "sport_key": "nba",
            "home_team": "BOS", "away_team": "MIA",
            "commence_time": now + timedelta(hours=h),
            "bookmaker_key": "dk", "market_key": "h2h",
            "outcome_name": "BOS", "outcome_point": None,
            "price_american": -110, "fetched_at": now,
        }
        for i, h in enumerate([1, 10, 30, 50])
    ]
    cache.upsert(rows)
    result = cache.distinct_events()
    assert {r["event_id"] for r in result} == {"ev_0", "ev_1", "ev_2", "ev_3"}


def test_distinct_events_within_hours_ahead_filters(tmp_path):
    """SQL pushdown via HAVING returns only events with MAX(commence_time)
    in [now, now+24h]."""
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    fixed_now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    rows = [
        {"event_id": "ev_soon",  "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now + timedelta(hours=1),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
        {"event_id": "ev_far",   "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now + timedelta(hours=30),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
        {"event_id": "ev_past",  "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now - timedelta(hours=5),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
    ]
    cache.upsert(rows)
    result = cache.distinct_events(within_hours_ahead=24, now=fixed_now)
    eids = {r["event_id"] for r in result}
    assert eids == {"ev_soon"}
    soon = next(r for r in result if r["event_id"] == "ev_soon")
    assert isinstance(soon["commence_time"], datetime)


def test_distinct_events_sport_filter_and_time_filter_combined(tmp_path):
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    fixed_now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    rows = [
        {"event_id": "nba_soon", "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now + timedelta(hours=1),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
        {"event_id": "mlb_soon", "sport_key": "mlb", "home_team": "LAD",
         "away_team": "SF", "commence_time": fixed_now + timedelta(hours=1),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "LAD",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
    ]
    cache.upsert(rows)
    result = cache.distinct_events(
        within_hours_ahead=24, sport_key="nba", now=fixed_now,
    )
    assert {r["event_id"] for r in result} == {"nba_soon"}
