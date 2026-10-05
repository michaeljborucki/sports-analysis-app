"""Tests for the FLAG-GATED betting-db odds read source.

The flag defaults to "native"; every test here sets ODDS_SOURCE
explicitly via monkeypatch so nothing leaks between tests.

The betting-db fixture DB is seeded through betting-db's OWN `Store`
(imported off sys.path) rather than hand-rolled SQL, so the shape under
test is the shape the real poller writes. If betting-db isn't checked
out next to this repo the module skips rather than fails.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.cache import OddsCache


BETTING_DB_REPO = Path.home() / "personal_workspace/betting-db"

pytestmark = pytest.mark.skipif(
    not (BETTING_DB_REPO / "betting_db" / "store.py").exists(),
    reason="betting-db repo not present",
)

if str(BETTING_DB_REPO) not in sys.path:
    sys.path.insert(0, str(BETTING_DB_REPO))


NOW = datetime.now(timezone.utc)
COMMENCE = NOW + timedelta(hours=3)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _clear_memo():
    """`_mapped_rows` is memoized on a few-second time bucket; tests swap
    BETTING_DB_PATH far faster than that, so clear it around every case."""
    from server.odds import bettingdb_source
    bettingdb_source._reset_memo_for_tests()
    yield
    bettingdb_source._reset_memo_for_tests()


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


def _seed(db_path: Path, events, rows, fetched_at: datetime) -> None:
    """Write one snapshot through betting-db's own Store."""
    from betting_db.store import Store

    store = Store(str(db_path))
    store.init_db()
    store.apply_snapshot(events=events, rows=rows, fetched_at=_z(fetched_at))
    store.close()


def _event(event_id: str, commence: datetime, sport_key="baseball_mlb",
           league_key="mlb", home="New York Yankees", away="Boston Red Sox"):
    from betting_db.parse import EventRow
    return EventRow(
        event_id=event_id, sport_key=sport_key, league_key=league_key,
        home_team=home, away_team=away, commence_time=_z(commence),
    )


def _odds(event_id: str, market_key: str, outcome_name: str, *,
          book="draftkings", description=None, point=None, price=-110):
    from betting_db.parse import OddsRow
    return OddsRow(
        event_id=event_id, bookmaker_key=book, market_key=market_key,
        outcome_name=outcome_name, outcome_description=description,
        outcome_point=point, price_american=price,
        price_decimal=2.0,
    )


@pytest.fixture
def betting_db(tmp_path: Path, monkeypatch) -> Path:
    """A temp betting-db seeded via betting-db's own Store."""
    from betting_db.parse import EventRow, OddsRow
    from betting_db.store import Store

    db_path = tmp_path / "odds.db"
    store = Store(str(db_path))
    store.init_db()
    store.apply_snapshot(
        events=[
            EventRow(
                event_id="evt_1",
                sport_key="baseball_mlb",
                league_key="mlb",
                home_team="New York Yankees",
                away_team="Boston Red Sox",
                commence_time=_z(COMMENCE),
            ),
        ],
        rows=[
            # h2h — betting-db stores NULL point for a pointless market.
            OddsRow(
                event_id="evt_1", bookmaker_key="draftkings",
                market_key="h2h", outcome_name="New York Yankees",
                outcome_description=None, outcome_point=None,
                price_american=-138, price_decimal=1.72,
            ),
            # Pointless NON-h2h market: exercises NULL -> 0.0 without the
            # h2h reverse-sentinel masking it.
            OddsRow(
                event_id="evt_1", bookmaker_key="draftkings",
                market_key="pitcher_record_a_win", outcome_name="Yes",
                outcome_description="Gerrit Cole", outcome_point=None,
                price_american=110, price_decimal=2.1,
            ),
            # Player prop: description must fold into outcome_name.
            OddsRow(
                event_id="evt_1", bookmaker_key="draftkings",
                market_key="batter_home_runs", outcome_name="Over",
                outcome_description="Aaron Judge", outcome_point=0.5,
                price_american=145, price_decimal=2.45,
            ),
        ],
        fetched_at=_z(NOW),
    )
    store.close()
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    return db_path


def _native_equivalent_rows(cache: OddsCache) -> list[dict]:
    """The SAME three outcomes, ingested the normal way: Odds API JSON ->
    normalize_odds_response -> cache.upsert -> all_current. This is the
    reference shape the adapter has to match."""
    from server.odds.normalize import normalize_odds_response

    rows = normalize_odds_response(
        [{
            "id": "evt_1",
            "home_team": "New York Yankees",
            "away_team": "Boston Red Sox",
            "commence_time": _z(COMMENCE),
            "bookmakers": [{
                "key": "draftkings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "New York Yankees", "price": -138},
                    ]},
                    {"key": "pitcher_record_a_win", "outcomes": [
                        {"name": "Yes", "description": "Gerrit Cole",
                         "price": 110},
                    ]},
                    {"key": "batter_home_runs", "outcomes": [
                        {"name": "Over", "description": "Aaron Judge",
                         "point": 0.5, "price": 145},
                    ]},
                ],
            }],
        }],
        fetched_at=NOW,
        sport_key="mlb",
    )
    cache.upsert(rows)
    return cache.all_current()


def _by_market(rows: list[dict]) -> dict[str, dict]:
    return {r["market_key"]: r for r in rows}


# ───────────────────────── default flag is inert ─────────────────────

def test_default_flag_is_native(monkeypatch):
    monkeypatch.delenv("ODDS_SOURCE", raising=False)
    from server.config import Config
    assert Config.from_env().odds_source == "native"


def test_read_version_uses_betting_db_and_debounced_direct_generation(
    cache: OddsCache, betting_db, monkeypatch,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    first = cache.read_version
    assert first[0] == "betting_db"

    cache._bump_version()
    # Raw native-cache churn does not immediately invalidate scanner memos.
    assert cache.read_version == first

    cache._flush_direct_read_generation_now(force=True)
    second = cache.read_version
    assert second[:-1] == first[:-1]
    assert second[-1] == first[-1] + 1


def test_source_fingerprint_is_coalesced_within_stabilization_window(
    betting_db, monkeypatch,
):
    from server.odds import bettingdb_source
    original = bettingdb_source._source_fingerprint_uncached
    calls = 0

    def counted():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(
        bettingdb_source, "_source_fingerprint_uncached", counted,
    )

    assert bettingdb_source.source_fingerprint() == (
        bettingdb_source.source_fingerprint()
    )
    assert calls == 1


def test_family_filter_preserves_every_non_prop_market(
    cache: OddsCache, tmp_path, monkeypatch,
):
    db_path = tmp_path / "family.db"
    markets = (
        "h2h",
        "alternate_spreads",
        "h2h_1st_5_innings",
        "totals_1st_5_innings",
        "pitcher_strikeouts",
        "batter_home_runs",
        "player_points",
    )
    _seed(
        db_path,
        [_event("family_evt", COMMENCE)],
        [
            _odds(
                "family_evt", market, "Over",
                description="Test Player" if market.startswith(
                    ("pitcher_", "batter_", "player_")
                ) else None,
                point=0.5,
            )
            for market in markets
        ],
        NOW,
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    non_props = cache.all_current_family("mlb", prop_family=False)
    props = cache.all_current_family("mlb", prop_family=True)

    assert {row["market_key"] for row in non_props} == set(markets[:4])
    assert {row["market_key"] for row in props} == set(markets[4:])


def test_mapped_row_timing_logs_only_on_cache_miss(
    cache: OddsCache, betting_db, monkeypatch, caplog,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    caplog.set_level("INFO", logger="server.odds.bettingdb_source")

    cache.all_current_family("mlb", prop_family=False)
    cache.all_current_family("mlb", prop_family=False)

    timing = [
        record for record in caplog.records
        if record.getMessage().startswith("betting-db read")
    ]
    assert len(timing) == 1
    message = timing[0].getMessage()
    assert "rows=" in message
    assert "fetch_ms=" in message
    assert "map_ms=" in message
    assert "total_ms=" in message


def test_event_listers_do_not_materialize_odds_rows(
    cache: OddsCache, betting_db, monkeypatch,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    from server.odds import bettingdb_source

    monkeypatch.setattr(
        bettingdb_source,
        "_mapped_rows",
        lambda *args, **kwargs: pytest.fail("event listing scanned odds rows"),
    )

    events = cache.distinct_events(
        within_hours_ahead=24, sport_key="mlb", now=NOW,
    )
    close = bettingdb_source.events_in_close_window(
        cache,
        now=COMMENCE - timedelta(minutes=10),
        lead_minutes=15,
        trail_minutes=5,
    )

    assert [event["event_id"] for event in events] == ["evt_1"]
    assert [event["event_id"] for event in close] == ["evt_1"]


def test_repeated_event_matching_reuses_one_event_query(
    cache: OddsCache, betting_db, monkeypatch,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    from server.odds import bettingdb_source
    original = bettingdb_source._betting_db_events_uncached
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        bettingdb_source, "_betting_db_events_uncached", counted,
    )

    cache.distinct_events(sport_key="mlb")
    cache.distinct_events(sport_key="mlb")

    assert calls == 1


def test_family_filter_pushes_event_horizon_into_source(
    cache: OddsCache, tmp_path, monkeypatch,
):
    db_path = tmp_path / "horizon.db"
    far = NOW + timedelta(days=10)
    _seed(
        db_path,
        [_event("soon", COMMENCE), _event("far", far)],
        [
            _odds("soon", "h2h", "Home"),
            _odds("far", "h2h", "Home"),
        ],
        NOW,
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    rows = cache.all_current_family(
        "mlb",
        prop_family=False,
        commence_before=NOW + timedelta(days=2),
    )

    assert {row["event_id"] for row in rows} == {"soon"}


def test_native_mode_never_touches_betting_db(cache: OddsCache, monkeypatch):
    """With the default flag, reads come from the native cache even when
    BETTING_DB_PATH points at a file that does not exist."""
    monkeypatch.delenv("ODDS_SOURCE", raising=False)
    monkeypatch.setenv("BETTING_DB_PATH", "/nonexistent/odds.db")
    native = _native_equivalent_rows(cache)
    assert len(native) == 3
    assert cache.event_sport_key("evt_1") == "mlb"
    assert len(cache.distinct_events()) == 1


# ──────────────────── betting_db mode: shape parity ───────────────────

def test_all_current_matches_native_row_shape(
    cache: OddsCache, betting_db, monkeypatch,
):
    native = _by_market(_native_equivalent_rows(cache))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    adapted = _by_market(cache.all_current())

    assert set(adapted) == set(native)
    for market_key, native_row in native.items():
        adapted_row = adapted[market_key]
        # Exact column parity — same keys AND same values.
        assert list(adapted_row) == list(native_row), market_key
        assert adapted_row == native_row, market_key


def test_null_point_maps_to_zero(cache: OddsCache, betting_db, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    rows = _by_market(cache.all_current())
    # Pointless non-h2h market: betting-db NULL -> odds_snapshot's 0.0.
    assert rows["pitcher_record_a_win"]["outcome_point"] == 0.0
    # h2h keeps the native reverse-sentinel (0.0 read back as None).
    assert rows["h2h"]["outcome_point"] is None


def test_prop_description_folds_into_outcome_name(
    cache: OddsCache, betting_db, monkeypatch,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    rows = _by_market(cache.all_current())
    # `_encode_outcome_name` runs the description through
    # `normalize_player_name`, which case-folds — matching native exactly
    # is the point, so assert the folded form.
    assert rows["batter_home_runs"]["outcome_name"] == "aaron judge Over"
    assert rows["pitcher_record_a_win"]["outcome_name"] == "gerrit cole Yes"
    # …and no stray description column leaks through.
    assert "outcome_description" not in rows["batter_home_runs"]


def test_sport_key_maps_league_not_odds_api_key(
    cache: OddsCache, betting_db, monkeypatch,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    rows = cache.all_current()
    assert {r["sport_key"] for r in rows} == {"mlb"}
    # And the sport filter takes the APP key, like the native path.
    assert cache.all_current("mlb") == rows
    assert cache.all_current("nba") == []


def test_direct_book_rows_are_unioned_in(
    cache: OddsCache, betting_db, monkeypatch,
):
    """coral33 has no betting-db equivalent; its native rows must survive
    the switch or every EV/arb pairing silently disappears."""
    cache.upsert([{
        "event_id": "evt_1", "sport_key": "mlb",
        "home_team": "New York Yankees", "away_team": "Boston Red Sox",
        "commence_time": COMMENCE, "bookmaker_key": "coral33",
        "market_key": "h2h", "outcome_name": "New York Yankees",
        "outcome_point": None, "price_american": -130,
        "fetched_at": NOW, "wager_type": "both",
    }])
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    rows = cache.all_current()
    coral = [r for r in rows if r["bookmaker_key"] == "coral33"]
    assert len(coral) == 1
    assert coral[0]["wager_type"] == "both"
    assert {r["bookmaker_key"] for r in rows} == {"draftkings", "coral33"}


def test_event_listers_work_in_betting_db_mode(
    cache: OddsCache, betting_db, monkeypatch,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    assert cache.event_sport_key("evt_1") == "mlb"

    events = cache.distinct_events()
    assert len(events) == 1
    assert events[0]["event_id"] == "evt_1"
    assert events[0]["sport_key"] == "mlb"

    windowed = cache.distinct_events(within_hours_ahead=24, now=NOW)
    assert len(windowed) == 1
    assert isinstance(windowed[0]["commence_time"], datetime)

    assert cache.distinct_events(within_hours_ahead=1, now=NOW) == []

    close = cache.events_in_close_window(
        COMMENCE - timedelta(minutes=10), lead_minutes=15, trail_minutes=5,
    )
    assert [e["event_id"] for e in close] == ["evt_1"]


# ───────────── C1: spend-path guards (dead events cost nothing) ────────

def test_event_sport_key_none_for_event_past_commence_window(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """betting-db archives forever; betting-site purges 6h after
    commence. `refresh_event` bills a per-event Odds API request for any
    event_id this resolves, so an event outside the commence window must
    come back None ("unknown_event" -> no spend), exactly as the native
    purged-cache path does.
    """
    db_path = tmp_path / "odds.db"
    long_gone = NOW - timedelta(hours=30)
    _seed(
        db_path,
        [_event("evt_old", long_gone)],
        [_odds("evt_old", "h2h", "New York Yankees")],
        fetched_at=long_gone,
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert cache.event_sport_key("evt_old") is None
    # …and it never enters the paid per-event worklist either.
    assert cache.distinct_events() == []
    assert cache.all_current() == []


def test_event_sport_key_none_for_stale_but_upcoming_event(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """Inside the commence window but far past its cadence allowance —
    betting-db has stopped hearing about it. Still no spend."""
    db_path = tmp_path / "odds.db"
    soon = NOW + timedelta(hours=2)          # <12h band -> 300s interval
    _seed(
        db_path,
        [_event("evt_stale", soon)],
        [_odds("evt_stale", "h2h", "New York Yankees")],
        fetched_at=NOW - timedelta(hours=4),  # way past 2*300+300
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert cache.event_sport_key("evt_stale") is None


# ─────────────── C2: cadence-aware freshness allowance ────────────────

def test_allowed_age_follows_betting_db_cadence_bands():
    from server.odds.bettingdb_source import allowed_age_seconds
    assert allowed_age_seconds(-1) == 2 * 60 + 300      # live -> tightest
    assert allowed_age_seconds(0.5) == 2 * 60 + 300
    assert allowed_age_seconds(2) == 2 * 300 + 300
    assert allowed_age_seconds(18) == 2 * 1800 + 300
    assert allowed_age_seconds(100) == 2 * 3600 + 300
    assert allowed_age_seconds(500) == 2 * 21600 + 300
    assert allowed_age_seconds(5000) == 2 * 86400 + 300


def test_far_out_event_survives_a_25_minute_old_fetch(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """18h out sits in betting-db's <48h band (30min poll), so 25min old
    is FRESH. The old flat-600s rule would have wrongly dropped it —
    hiding most of the forward book."""
    db_path = tmp_path / "odds.db"
    _seed(
        db_path,
        [_event("evt_far", NOW + timedelta(hours=18))],
        [_odds("evt_far", "h2h", "New York Yankees")],
        fetched_at=NOW - timedelta(minutes=25),
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert [r["event_id"] for r in cache.all_current()] == ["evt_far"]
    assert cache.event_sport_key("evt_far") == "mlb"


def test_near_event_dropped_at_the_same_25_minute_age(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """2h out sits in the <12h band (5min poll) -> 15min allowance, so
    the SAME 25min age is stale."""
    db_path = tmp_path / "odds.db"
    _seed(
        db_path,
        [_event("evt_near", NOW + timedelta(hours=2))],
        [_odds("evt_near", "h2h", "New York Yankees")],
        fetched_at=NOW - timedelta(minutes=25),
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert cache.all_current() == []


# ───────────────────── I5: remaining shape guards ─────────────────────

def test_nrfi_bridge_rows_are_synthesized(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """The Odds API has no `nrfi` market — betting-site synthesizes it
    from totals_1st_1_innings @0.5 so coral33's NRFI line has something
    to pair against. betting_db mode must synthesize it too."""
    db_path = tmp_path / "odds.db"
    commence = NOW + timedelta(hours=3)
    _seed(
        db_path,
        [_event("evt_nrfi", commence)],
        [
            _odds("evt_nrfi", "totals_1st_1_innings", "Over",
                  point=0.5, price=120),
            _odds("evt_nrfi", "totals_1st_1_innings", "Under",
                  point=0.5, price=-150),
            # A non-0.5 line must NOT produce an nrfi row.
            _odds("evt_nrfi", "totals_1st_1_innings", "Over",
                  point=1.5, price=300),
        ],
        fetched_at=NOW,
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    nrfi = {
        r["outcome_name"]: r for r in cache.all_current()
        if r["market_key"] == "nrfi"
    }
    assert set(nrfi) == {"Yes", "No"}
    assert nrfi["Yes"]["price_american"] == 120     # Over -> Yes (YRFI)
    assert nrfi["No"]["price_american"] == -150     # Under -> No (NRFI)
    assert nrfi["Yes"]["outcome_point"] == 0.0


def test_kalshi_rows_from_betting_db_are_excluded(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """Mirrors normalize._EXCLUDE_BOOKMAKERS: the Odds API's kalshi copy
    is minutes stale, the direct poller owns that slot."""
    db_path = tmp_path / "odds.db"
    commence = NOW + timedelta(hours=3)
    _seed(
        db_path,
        [_event("evt_k", commence)],
        [
            _odds("evt_k", "h2h", "New York Yankees", book="kalshi"),
            _odds("evt_k", "h2h", "New York Yankees", book="draftkings"),
        ],
        fetched_at=NOW,
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert {r["bookmaker_key"] for r in cache.all_current()} == {"draftkings"}


def test_direct_book_row_wins_pk_collision_over_betting_db_copy(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """betting-db carries the Odds API's own `polymarket` quotes. In
    native mode those land in the SAME odds_snapshot PK slot as the
    direct WS feed's row, so exactly one survives — the direct one, which
    is fresher and the only one carrying max_stake_dollars."""
    db_path = tmp_path / "odds.db"
    commence = NOW + timedelta(hours=3)
    _seed(
        db_path,
        [_event("evt_pm", commence)],
        [_odds("evt_pm", "h2h", "New York Yankees",
               book="polymarket", price=-200)],
        fetched_at=NOW,
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    cache.upsert([{
        "event_id": "evt_pm", "sport_key": "mlb",
        "home_team": "New York Yankees", "away_team": "Boston Red Sox",
        "commence_time": commence, "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "New York Yankees",
        "outcome_point": None, "price_american": -180,
        "fetched_at": NOW, "max_stake_dollars": 450.0,
    }])
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    pm = [r for r in cache.all_current() if r["bookmaker_key"] == "polymarket"]
    assert len(pm) == 1
    assert pm[0]["price_american"] == -180        # the direct row
    assert pm[0]["max_stake_dollars"] == 450.0


def test_rows_with_null_teams_are_dropped(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """odds_snapshot declares home_team/away_team NOT NULL and consumers
    dereference them unguarded; betting-db allows NULL when odds land
    before their event is discovered."""
    db_path = tmp_path / "odds.db"
    commence = NOW + timedelta(hours=3)
    _seed(
        db_path,
        [_event("evt_ok", commence)],
        [_odds("evt_ok", "h2h", "New York Yankees")],
        fetched_at=NOW,
    )
    # betting-db's `latest_odds` declares home_team/away_team nullable,
    # but its Store can't emit that shape (it needs a matching event
    # row), so the row is written directly — this guard is defense
    # against the schema's own permissiveness, not against Store.
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO latest_odds (sport_key, league_key, event_id, "
        "commence_time, home_team, away_team, bookmaker_key, market_key, "
        "outcome_name, outcome_description, outcome_point, "
        "price_american, fetched_at) "
        "VALUES ('baseball_mlb','mlb','evt_ghost',?,NULL,NULL,"
        "'draftkings','h2h','Nobody',NULL,NULL,-110,?)",
        (_z(commence), _z(NOW)),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert [r["event_id"] for r in cache.all_current()] == ["evt_ok"]


def test_sport_filter_is_pushed_into_sql():
    """Prefix sports must use GLOB, not LIKE — LIKE's `_` is a
    single-char wildcard and would over-match."""
    from server.odds.bettingdb_source import _sport_filter_sql

    clause, params = _sport_filter_sql("tennis")
    assert "GLOB" in clause and "LIKE" not in clause
    assert "tennis_atp_*" in params and "tennis_wta_*" in params

    clause, params = _sport_filter_sql("nba")
    assert "sport_key IN" in clause
    # Summer League folds into the NBA tab, so both keys must be pushed.
    assert set(params) == {"basketball_nba", "basketball_nba_summer_league"}

    assert _sport_filter_sql(None) == ("", [])
    assert _sport_filter_sql("not_a_sport") == (" AND 0", [])


# ──────────────────── I4: ODDS_SOURCE validation ──────────────────────

def test_unknown_odds_source_falls_back_to_native(
    cache: OddsCache, monkeypatch, caplog,
):
    monkeypatch.setenv("ODDS_SOURCE", "betting-db")   # typo: hyphen
    monkeypatch.setenv("BETTING_DB_PATH", "/nonexistent/odds.db")
    from server.odds import cache as cache_mod
    # The warning is deduped per raw value; clear the record so this test
    # is order-independent.
    monkeypatch.setattr(cache_mod, "_warned_odds_source", cache_mod._UNSET)
    with caplog.at_level("WARNING"):
        assert cache_mod._odds_source() == "native"
    assert "falling back to 'native'" in caplog.text
    # And the read path really is native — a missing betting-db is fine.
    assert cache.all_current() == []


# ─────────────── memo memory bound (one bucket, one entry) ────────────

def test_memo_evicts_stale_buckets_rather_than_accumulating(
    cache: OddsCache, betting_db, monkeypatch,
):
    """A full-book scan is ~150k dicts. Retaining one entry per (sport,
    bucket) pair would pin several of those at once; only the CURRENT
    bucket may be held."""
    from server.odds import bettingdb_source as B

    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    fake_now = [1_000_000.0]
    monkeypatch.setattr(B.time, "time", lambda: fake_now[0])

    cache.all_current()            # caches sport_key=None
    cache.all_current("mlb")       # caches sport_key="mlb", same bucket
    assert set(B._MAPPED_ROWS_CACHE) == {None, "mlb"}
    bucket_a = B._MAPPED_ROWS_CACHE["mlb"][0]
    first_rows = B._MAPPED_ROWS_CACHE["mlb"][1]

    # Same bucket -> served from the memo, same list object, no re-scan.
    assert B._mapped_rows("mlb") is first_rows

    # Roll the clock past the TTL. The next call must drop BOTH stale
    # entries, leaving only the sport just fetched.
    fake_now[0] += B.MEMO_TTL_SECONDS * 3
    cache.all_current("mlb")

    assert set(B._MAPPED_ROWS_CACHE) == {"mlb"}
    bucket_b, second_rows = B._MAPPED_ROWS_CACHE["mlb"]
    assert bucket_b != bucket_a
    assert second_rows is not first_rows       # old rows released


def test_invalid_odds_source_warning_is_deduped(cache: OddsCache, monkeypatch, caplog):
    """The validation runs on every scanner read; a bad value must not
    spam a warning per request."""
    from server.odds import cache as cache_mod

    monkeypatch.setattr(cache_mod, "_warned_odds_source", cache_mod._UNSET)
    monkeypatch.setenv("ODDS_SOURCE", "bettingdb")   # invalid
    with caplog.at_level("WARNING"):
        for _ in range(5):
            assert cache_mod._odds_source() == "native"
    assert caplog.text.count("falling back to 'native'") == 1

    # A DIFFERENT bad value is a new fact and warns again.
    monkeypatch.setenv("ODDS_SOURCE", "betting_db_v2")
    with caplog.at_level("WARNING"):
        cache_mod._odds_source()
    assert caplog.text.count("falling back to 'native'") == 2


# ─────────────── sargable freshness bound (query-plan fix) ────────────

def test_freshness_sql_emits_a_sargable_fetched_at_floor():
    """`fetched_at >= CASE WHEN commence_time ... END` is row-dependent,
    so SQLite cannot use `idx_latest_fetched` and full-scans latest_odds
    (5.6M rows on the live DB -> 30-46s per read).

    Every CASE branch yields one of the cutoffs, so `fetched_at >=
    MIN(cutoffs)` is logically ENTAILED by the CASE and can be emitted
    as a plain indexable bound alongside it. It never changes the result
    set — it only lets the planner seek instead of scan.
    """
    from server.odds.bettingdb_source import _freshness_sql, _iso_z, allowed_age_seconds

    now = datetime(2026, 9, 20, 15, 4, 0, tzinfo=timezone.utc)
    clause, params = _freshness_sql(now)

    # A bare, parameterised fetched_at floor must exist OUTSIDE the CASE.
    before_case = clause.split("CASE")[0]
    assert "fetched_at >= ?" in before_case, (
        f"no sargable fetched_at floor emitted; clause={clause!r}"
    )

    # …and it must equal the loosest (oldest) cutoff — the catch-all band —
    # so it can never exclude a row the CASE would have admitted.
    loosest = _iso_z(now - timedelta(seconds=allowed_age_seconds(float("inf"))))
    assert loosest in params
    # The floor is the minimum over every cutoff the CASE can return.
    cutoffs = [p for p in params if isinstance(p, str) and p <= _iso_z(now)]
    assert loosest == min(cutoffs)


def test_catch_all_band_row_survives_the_sargable_floor(
    cache: OddsCache, tmp_path: Path, monkeypatch,
):
    """The loosest band (far-future event) tolerates a ~2-day-old fetch.
    That is exactly the row a too-tight sargable floor would silently
    drop, so guard it end-to-end rather than only at the SQL level."""
    db_path = tmp_path / "odds.db"
    # Bands top out at 720h (30d); BEYOND that is the catch-all, whose
    # allowance is 2*86400 + 300s = 48.08h. 40 days out + a 47h-old fetch
    # sits inside it.
    _seed(
        db_path,
        [_event("evt_catchall", NOW + timedelta(days=40))],
        [_odds("evt_catchall", "h2h", "New York Yankees")],
        fetched_at=NOW - timedelta(hours=47),
    )
    monkeypatch.setenv("BETTING_DB_PATH", str(db_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")

    assert [r["event_id"] for r in cache.all_current()] == ["evt_catchall"]


def test_memo_bucket_is_stamped_at_completion_not_at_entry(monkeypatch):
    """The memo stamps the bucket computed when the scan STARTED, then
    stores it after the scan returns. A scan longer than MEMO_TTL_SECONDS
    therefore lands in the cache already expired — on the live DB a 34s
    scan was filed under a bucket 7 windows in the past, so the very next
    caller missed and re-scanned. Four dashboard scanners = four full
    scans of the same data.

    Stamping at completion makes the entry live for its full TTL, without
    widening the window: rows are still at most MEMO_TTL_SECONDS old
    relative to when they were produced.
    """
    from server.odds import bettingdb_source as B

    clock = {"t": 1000.0}
    monkeypatch.setattr(B.time, "time", lambda: clock["t"])

    calls = {"n": 0}

    def slow_scan(*_a, **_k):
        calls["n"] += 1
        clock["t"] += 34.0          # scan takes 34s, TTL is 5s
        return [{"row": calls["n"]}]

    monkeypatch.setattr(B, "_mapped_rows_uncached", slow_scan)
    B._MAPPED_ROWS_CACHE.clear()

    first = B._mapped_rows(None)
    assert calls["n"] == 1

    # A caller arriving immediately after completion must reuse that scan.
    clock["t"] += 1.0
    second = B._mapped_rows(None)
    assert calls["n"] == 1, "memo missed on data that is 1 second old"
    assert second is first

    # …and must still expire once the TTL has genuinely elapsed.
    clock["t"] += B.MEMO_TTL_SECONDS + 1
    B._mapped_rows(None)
    assert calls["n"] == 2
