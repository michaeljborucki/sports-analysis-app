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


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


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
