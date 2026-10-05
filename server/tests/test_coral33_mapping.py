from __future__ import annotations

from pathlib import Path

from server.odds.books.coral33.mapping import (
    PERIOD_SUFFIX,
    load_coral33_config,
)


CONFIG = Path(__file__).parent.parent / "config" / "coral33.toml"


def test_default_config_loads():
    cfg = load_coral33_config(CONFIG)
    assert "nba" in cfg.sports
    assert "nhl" in cfg.sports
    assert "mlb" in cfg.sports
    assert "nfl" in cfg.sports
    assert "ncaaf" in cfg.sports
    assert cfg.sports["nba"].sport_type == "BASKETBALL"
    assert "NBA" in cfg.sports["nba"].subtypes_main
    assert "NBA ALT LINE" in cfg.sports["nba"].subtypes_alt
    assert cfg.sports["nfl"].sport_type == "FOOTBALL"
    for period in ["Game", "1st Half", "1st Quarter", "2nd Quarter", "3rd Quarter", "4th Quarter"]:
        assert ("FOOTBALL", "NFL", period) in cfg.sports["nfl"].main_period_calls
    assert ("FOOTBALL", "NFL PRESEAS", "Game") in cfg.sports["nfl"].main_period_calls
    assert cfg.sports["nfl"].alt_calls == [("FOOTBALL", "NFLALTLINE", "Game")]
    assert cfg.sports["nfl"].prop_calls == [("FOOTBALL", "NFLPLRPROPS", "Game")]
    assert cfg.sports["ncaaf"].main_period_calls == [
        ("FOOTBALL", "COLLEGE", "Game"),
        ("FOOTBALL", "COLLEGE", "1st Half"),
        ("FOOTBALL", "COLLEXT", "Game"),
        ("FOOTBALL", "COLLEXT", "1st Half"),
    ]


def test_main_period_call_expansion():
    cfg = load_coral33_config(CONFIG)
    calls = cfg.sports["nba"].main_period_calls
    # Cartesian of subtypes_main × periods
    assert ("BASKETBALL", "NBA", "Game") in calls
    assert ("BASKETBALL", "NBA", "1st Quarter") in calls
    # "NBA PRESEASO" (summer-league / preseason slate) folds into the NBA sport
    # key and inherits every period.
    assert ("BASKETBALL", "NBA PRESEASO", "Game") in calls
    # 2 subtypes × 7 periods
    assert len(calls) == 14


def test_alt_calls_fixed_to_game_period():
    cfg = load_coral33_config(CONFIG)
    alts = cfg.sports["nba"].alt_calls
    assert alts == [("BASKETBALL", "NBA ALT LINE", "Game")]


def test_ncaaf_alt_calls():
    """COLLALT is the college-football alt-line board — Game period only,
    same shape as NBA/MLB alt lines."""
    cfg = load_coral33_config(CONFIG)
    assert cfg.sports["ncaaf"].alt_calls == [("FOOTBALL", "COLLALT", "Game")]


def test_period_suffixes_cover_expected_names():
    expected = {"Game", "1st Half", "2nd Half",
                "1st Quarter", "2nd Quarter", "3rd Quarter", "4th Quarter",
                "1st Period", "2nd Period", "3rd Period",
                "1st 5 Innings"}
    assert expected.issubset(set(PERIOD_SUFFIX.keys()))
    assert PERIOD_SUFFIX["Game"] == ""
    assert PERIOD_SUFFIX["1st Quarter"] == "_q1"


# --- Regressions from the 2026-09-04 NCAAF orphan audit -------------------

def _ncaaf_matcher(events):
    from server.odds.books.coral33.event_matcher import Coral33EventMatcher
    return Coral33EventMatcher(lambda sk: events, {"ncaaf": {"long island": "liu"}},
                               window_minutes=30)


def _ev(away, home, iso):
    return {"event_id": "e1", "home_team": home, "away_team": away,
            "commence_time": iso}


def test_tv_half_hour_shift_is_not_defeated_by_coral_seconds_offset():
    """coral33 stamps GameDateTime with :01. A game listed exactly one TV
    half-hour apart measured 1801s against the 1800s window and orphaned."""
    from server.odds.books.coral33.normalizer import _parse_coral_datetime
    evs = [_ev("Western Michigan Broncos", "Michigan Wolverines",
               "2026-09-05T23:00:00Z")]
    m = _ncaaf_matcher(evs)
    got = m.match("ncaaf", "Michigan", "Western Michigan",
                  _parse_coral_datetime("2026-09-05 17:30:01.000"))
    assert got is not None and got["home_team"] == "Michigan Wolverines"


def test_compass_initial_expands_to_full_direction():
    """'N Carolina A&T' must reach 'North Carolina A&T Aggies'."""
    from server.odds.books.coral33.normalizer import _parse_coral_datetime
    evs = [_ev("North Carolina A&T Aggies", "Georgia State Panthers",
               "2026-09-04T23:00:00Z")]
    m = _ncaaf_matcher(evs)
    got = m.match("ncaaf", "Georgia St", "N Carolina A&T",
                  _parse_coral_datetime("2026-09-04 17:00:01.000"))
    assert got is not None and got["away_team"] == "North Carolina A&T Aggies"


def test_long_island_alias_reaches_liu():
    from server.odds.books.coral33.normalizer import _parse_coral_datetime
    evs = [_ev("LIU Sharks", "Kansas Jayhawks", "2026-09-05T00:00:00Z")]
    m = _ncaaf_matcher(evs)
    got = m.match("ncaaf", "Kansas", "Long Island",
                  _parse_coral_datetime("2026-09-04 18:00:01.000"))
    assert got is not None and got["away_team"] == "LIU Sharks"


def test_ambiguous_prefix_still_orphans_rather_than_guessing():
    """The window fix must not make prefix matching reckless: 'Michigan' with
    two same-window candidates stays an orphan."""
    from server.odds.books.coral33.normalizer import _parse_coral_datetime
    evs = [_ev("Toledo Rockets", "Michigan Wolverines", "2026-09-05T23:00:00Z"),
           _ev("Ball State Cardinals", "Michigan State Spartans",
               "2026-09-05T23:00:00Z")]
    m = _ncaaf_matcher(evs)
    assert m.match("ncaaf", "Michigan", "Some Unlisted Team",
                   _parse_coral_datetime("2026-09-05 17:30:01.000")) is None
