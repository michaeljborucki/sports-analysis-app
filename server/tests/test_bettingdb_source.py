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
    with caplog.at_level("WARNING"):
        assert cache_mod._odds_source() == "native"
    assert "falling back to 'native'" in caplog.text
    # And the read path really is native — a missing betting-db is fine.
    assert cache.all_current() == []
