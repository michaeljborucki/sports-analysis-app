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
    so scanner endpoints can use it as a cheap cache-fingerprint.

    Bumps are debounced — each state-changing op sets a dirty flag and
    the next flush tick applies a single increment. We force the flush
    inline here via `_flush_version_now()` so the test exercises the
    same end-state callers see after a 200ms window."""
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

    # Each upsert call sets the dirty flag; the flush converts it to
    # exactly one increment (per-window, not per-call).
    cache.upsert([base_row])
    cache._flush_version_now()
    assert cache.version == 1

    cache.upsert([base_row, {**base_row, "outcome_name": "Red Sox", "price_american": 120}])
    cache._flush_version_now()
    assert cache.version == 2

    # Empty input is a no-op — must NOT bump (would needlessly invalidate
    # scanner memos every quiet poll cycle).
    cache.upsert([])
    cache._flush_version_now()
    assert cache.version == 2

    # Purges that actually delete rows bump too.
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    removed = cache.purge_finished_games(now=far_future, past_hours=0)
    assert removed > 0
    cache._flush_version_now()
    assert cache.version == 3

    # Purges that delete nothing don't bump.
    removed = cache.purge_finished_games(now=far_future, past_hours=0)
    assert removed == 0
    cache._flush_version_now()
    assert cache.version == 3


def test_version_bumps_on_stale_and_book_purge(cache: OddsCache):
    """purge_stale_rows and purge_live_rows_for_book also alter scanner
    state, so they must bump the version when they actually delete rows.

    Same debounce dynamics as the upsert path: each op flips the dirty
    flag, the explicit flush converts it to a single increment."""
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
    cache._flush_version_now()
    v_after_upsert = cache.version

    # The row's `fetched_at` is "now" — purge with a future cutoff so its
    # age exceeds max_age_seconds=0.
    from datetime import timedelta
    future = now + timedelta(hours=1)
    removed = cache.purge_stale_rows(now=future, max_age_seconds=0)
    assert removed == 1
    cache._flush_version_now()
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
    cache._flush_version_now()
    v_before_live = cache.version
    removed = cache.purge_live_rows_for_book("coral33", future)
    assert removed == 1
    cache._flush_version_now()
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


# ─────────────── Composite index for GROUP BY event_id ────────────────


def test_composite_event_commence_index_exists(tmp_path):
    """The idx_odds_event_commence covering index is what lets
    distinct_events / events_in_close_window use a single index walk
    instead of a full-table SCAN."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        names = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
    assert "idx_odds_event_commence" in names


def test_distinct_events_plan_uses_index(tmp_path):
    """EXPLAIN QUERY PLAN for distinct_events()'s SQL must show
    USING INDEX idx_odds_event_commence — never SCAN of the heap."""
    from datetime import datetime, timezone, timedelta
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    fixed_now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    cache.upsert([
        {"event_id": f"e{i}", "sport_key": "nba", "home_team": "A",
         "away_team": "B", "commence_time": fixed_now + timedelta(hours=i),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "A",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now}
        for i in range(3)
    ])
    # Match the exact SQL distinct_events builds for the no-filter path.
    q = (
        "SELECT event_id, MAX(sport_key) AS sport_key, "
        "MAX(commence_time) AS commence_time, "
        "MAX(home_team) AS home_team, MAX(away_team) AS away_team "
        "FROM odds_snapshot GROUP BY event_id"
    )
    with cache._conn() as c:
        plan = c.execute(f"EXPLAIN QUERY PLAN {q}").fetchall()
    plan_str = " | ".join(str(dict(r)) for r in plan)
    # SQLite emits something like "SCAN odds_snapshot USING COVERING INDEX
    # idx_odds_event_commence" — the absence of a bare "SCAN
    # odds_snapshot" (no USING INDEX qualifier) is the win.
    assert "idx_odds_event_commence" in plan_str, (
        f"GROUP BY event_id did not use the composite index. Plan: {plan_str}"
    )


# ────────────── A1: _bump_version 200ms debounce ──────────────────


def test_bump_version_does_not_increment_synchronously(tmp_path):
    """`_bump_version()` only flips the dirty flag; the counter stays
    put until the flush loop (or `_flush_version_now()`) runs."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    assert cache.version == 0
    for _ in range(1000):
        cache._bump_version()
    assert cache.version == 0
    assert cache._version_dirty is True


def test_flush_version_collapses_burst_to_single_increment(tmp_path):
    """1000 rapid `_bump_version` calls + one flush tick = exactly
    one increment. This is the whole point of the debounce."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    for _ in range(1000):
        cache._bump_version()
    bumped = cache._flush_version_now()
    assert bumped is True
    assert cache.version == 1
    assert cache._version_dirty is False


def test_flush_with_no_pending_bump_is_noop(tmp_path):
    """A flush with no dirty flag set must not move the counter and
    must report no bump applied."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    assert cache._flush_version_now() is False
    assert cache.version == 0


def test_bump_after_flush_increments_on_next_flush(tmp_path):
    """After a flush clears the flag, a single new bump increments by
    1 on the next flush — there's no "consumed-quota" coupling."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    cache._bump_version()
    cache._flush_version_now()
    assert cache.version == 1
    cache._bump_version()
    cache._flush_version_now()
    assert cache.version == 2


async def test_version_flush_loop_coalesces_burst(tmp_path):
    """End-to-end via the actual background loop: a burst of bumps
    during one flush interval produces ONE increment."""
    import asyncio
    from server.odds import cache as cache_mod
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    # Tighten the interval so the test runs in milliseconds rather
    # than seconds. The loop reads VERSION_FLUSH_INTERVAL_S each
    # iteration, so monkeypatching at module level works.
    original = cache_mod.VERSION_FLUSH_INTERVAL_S
    cache_mod.VERSION_FLUSH_INTERVAL_S = 0.02
    task = asyncio.create_task(cache.version_flush_loop())
    try:
        for _ in range(1000):
            cache._bump_version()
        # One full flush interval plus a generous safety margin.
        await asyncio.sleep(0.08)
        assert cache.version == 1
    finally:
        cache_mod.VERSION_FLUSH_INTERVAL_S = original
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ───────────── all_current_cached: shared per-version memo ──────────


def test_all_current_cached_returns_same_object_within_version(tmp_path):
    """Two consecutive `all_current_cached()` calls with no version
    bump between them return the SAME list object — what makes the
    5-scanner Edges-page tick cheap."""
    from datetime import datetime, timezone
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "evt_1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now, "bookmaker_key": "dk",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -110, "fetched_at": now,
    }])
    cache._flush_version_now()
    rows_a = cache.all_current_cached()
    rows_b = cache.all_current_cached()
    assert rows_a is rows_b  # identity, not equality


def test_all_current_cached_rebuilds_after_version_bump(tmp_path):
    """A version bump invalidates the per-version memo so the next
    call rebuilds against the current row set."""
    from datetime import datetime, timezone
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    cache.upsert([{
        "event_id": "evt_1", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now, "bookmaker_key": "dk",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -110, "fetched_at": now,
    }])
    cache._flush_version_now()
    first = cache.all_current_cached()
    assert len(first) == 1

    cache.upsert([{
        "event_id": "evt_2", "sport_key": "nba",
        "home_team": "LAL", "away_team": "GSW",
        "commence_time": now, "bookmaker_key": "dk",
        "market_key": "h2h", "outcome_name": "LAL",
        "outcome_point": None, "price_american": -110, "fetched_at": now,
    }])
    cache._flush_version_now()
    second = cache.all_current_cached()
    assert second is not first
    assert len(second) == 2


# ──────────────── find_closing_lines_bulk ────────────────


def _seed_closing(cache: OddsCache, items: list[tuple]) -> None:
    """items: list of (event_id, market_key, outcome_name, outcome_point, close_odds)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    rows = []
    for event_id, market_key, outcome_name, point, close_odds in items:
        rows.append({
            "event_id": event_id, "sport_key": "mlb",
            "home_team": "A", "away_team": "B",
            "market_key": market_key, "outcome_name": outcome_name,
            "outcome_point": point,
            "close_odds": close_odds, "close_prob_devig": 0.5,
            "commence_time": now, "captured_at": now,
            "source_books": "consensus",
        })
    cache.upsert_closing_lines(rows)


def test_find_closing_lines_bulk_empty_input(tmp_path):
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    assert cache.find_closing_lines_bulk([]) == {}


def test_find_closing_lines_bulk_matches_single_path(tmp_path):
    """A row addressed via bulk matches what `find_closing_line` returns
    for the same address — single-row callers and bulk callers see the
    same data."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    _seed_closing(cache, [
        ("evt_1", "h2h", "Yankees", 0.0, -150),
        ("evt_1", "totals", "Over", 8.5, -110),
        ("evt_2", "spreads", "Yankees", -1.5, 145),
    ])
    addresses = [
        ("evt_1", "h2h", "Yankees", None),
        ("evt_1", "totals", "Over", 8.5),
        ("evt_2", "spreads", "Yankees", -1.5),
    ]
    bulk = cache.find_closing_lines_bulk(addresses)
    assert set(bulk.keys()) == set(addresses)
    # Compare against the single-row helper on the same addresses.
    for ev, mk, on, pt in addresses:
        single = cache.find_closing_line(ev, mk, on, pt)
        assert single is not None
        bulk_row = bulk[(ev, mk, on, pt)]
        assert bulk_row["close_odds"] == single["close_odds"]
        assert bulk_row["event_id"] == single["event_id"]


def test_find_closing_lines_bulk_missing_addresses_absent(tmp_path):
    """Addresses with no closing line just aren't in the result — the
    caller checks `in` rather than relying on a sentinel."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    _seed_closing(cache, [("evt_1", "h2h", "Yankees", 0.0, -150)])
    bulk = cache.find_closing_lines_bulk([
        ("evt_1", "h2h", "Yankees", None),
        ("evt_999", "h2h", "Nobody", None),  # missing
    ])
    assert ("evt_1", "h2h", "Yankees", None) in bulk
    assert ("evt_999", "h2h", "Nobody", None) not in bulk
    assert len(bulk) == 1


def test_find_closing_lines_bulk_fires_one_query(tmp_path):
    """148 addresses must produce a SINGLE sqlite query — that's the
    whole point of the bulk helper (the /api/bets per-row loop is what
    we're replacing)."""
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    items = [(f"evt_{i}", "h2h", "Yankees", 0.0, -110) for i in range(148)]
    _seed_closing(cache, items)

    addresses = [(f"evt_{i}", "h2h", "Yankees", None) for i in range(148)]

    # Hook sqlite's trace callback to count SELECT executions on
    # closing_lines. Since find_closing_lines_bulk opens its own
    # connection via _conn(), monkeypatch _conn to wrap it with a
    # trace-counting callback.
    select_count = {"n": 0}
    original_conn = cache._conn

    def traced_conn():
        conn = original_conn()
        def callback(stmt: str):
            if "FROM closing_lines" in stmt or "FROM CLOSING_LINES" in stmt.upper():
                select_count["n"] += 1
        conn.set_trace_callback(callback)
        return conn

    cache._conn = traced_conn  # type: ignore[method-assign]
    try:
        bulk = cache.find_closing_lines_bulk(addresses)
    finally:
        cache._conn = original_conn  # type: ignore[method-assign]
    assert len(bulk) == 148
    assert select_count["n"] == 1, (
        f"expected 1 SELECT on closing_lines, got {select_count['n']}"
    )


# ──────────────── purge_closing_lines_older_than ────────────────


def test_purge_closing_lines_older_than_empty_db(tmp_path):
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    assert cache.purge_closing_lines_older_than(days=90) == 0


def test_purge_closing_lines_older_than_removes_only_old(tmp_path):
    """Rows whose commence_time is past the cutoff are deleted; recent
    rows survive."""
    from datetime import datetime, timezone, timedelta
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime.now(timezone.utc)
    old_ct = (now - timedelta(days=200)).isoformat()
    recent_ct = (now - timedelta(days=10)).isoformat()
    cache.upsert_closing_lines([
        {
            "event_id": "evt_old", "sport_key": "mlb",
            "home_team": "A", "away_team": "B",
            "market_key": "h2h", "outcome_name": "A", "outcome_point": 0.0,
            "close_odds": -110, "close_prob_devig": 0.5,
            "commence_time": old_ct, "captured_at": old_ct,
        },
        {
            "event_id": "evt_recent", "sport_key": "mlb",
            "home_team": "A", "away_team": "B",
            "market_key": "h2h", "outcome_name": "A", "outcome_point": 0.0,
            "close_odds": -110, "close_prob_devig": 0.5,
            "commence_time": recent_ct, "captured_at": recent_ct,
        },
    ])
    removed = cache.purge_closing_lines_older_than(days=90)
    assert removed == 1
    remaining = {r["event_id"] for r in cache.closing_lines_for_event("evt_old")}
    assert remaining == set()
    survivors = {r["event_id"] for r in cache.closing_lines_for_event("evt_recent")}
    assert survivors == {"evt_recent"}


def test_purge_closing_lines_idempotent(tmp_path):
    """Repeated purges past the first one return 0 — no spurious
    deletions, no errors."""
    from datetime import datetime, timezone, timedelta
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    old_ct = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    cache.upsert_closing_lines([{
        "event_id": "evt_old", "sport_key": "mlb",
        "home_team": "A", "away_team": "B",
        "market_key": "h2h", "outcome_name": "A", "outcome_point": 0.0,
        "close_odds": -110, "close_prob_devig": 0.5,
        "commence_time": old_ct, "captured_at": old_ct,
    }])
    assert cache.purge_closing_lines_older_than(days=90) == 1
    assert cache.purge_closing_lines_older_than(days=90) == 0
