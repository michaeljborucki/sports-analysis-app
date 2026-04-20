from __future__ import annotations

from datetime import datetime, timedelta, timezone

from server.odds.books.coral33.event_matcher import Coral33EventMatcher


def _events_nba():
    return [
        {
            "event_id": "abc123",
            "home_team": "San Antonio Spurs",
            "away_team": "Portland Trail Blazers",
            "commence_time": datetime(2026, 4, 19, 19, 0, tzinfo=timezone.utc),
        },
        {
            "event_id": "xyz789",
            "home_team": "Boston Celtics",
            "away_team": "Miami Heat",
            "commence_time": datetime(2026, 4, 19, 22, 0, tzinfo=timezone.utc),
        },
    ]


def _stub(sport_key: str):
    return _events_nba() if sport_key == "nba" else []


def test_exact_match():
    m = Coral33EventMatcher(_stub)
    eid = m.match(
        "nba",
        home="San Antonio Spurs",
        away="Portland Trail Blazers",
        commence=datetime(2026, 4, 19, 19, 0, tzinfo=timezone.utc),
    )
    assert eid == "abc123"


def test_reversed_home_away_still_matches():
    """coral33 and Odds API can disagree about who's "home" — we accept either
    orientation since the event is the same."""
    m = Coral33EventMatcher(_stub)
    eid = m.match(
        "nba",
        home="Portland Trail Blazers",
        away="San Antonio Spurs",
        commence=datetime(2026, 4, 19, 19, 0, tzinfo=timezone.utc),
    )
    assert eid == "abc123"


def test_case_and_punctuation_ignored():
    m = Coral33EventMatcher(_stub)
    eid = m.match(
        "nba",
        home="SAN antonio SPURS!!!",
        away="portland trail  blazers",
        commence=datetime(2026, 4, 19, 19, 0, tzinfo=timezone.utc),
    )
    assert eid == "abc123"


def test_time_window_accepts_small_drift():
    m = Coral33EventMatcher(_stub)
    eid = m.match(
        "nba",
        home="San Antonio Spurs",
        away="Portland Trail Blazers",
        commence=datetime(2026, 4, 19, 19, 7, tzinfo=timezone.utc),  # +7 min
    )
    assert eid == "abc123"


def test_time_window_rejects_large_drift():
    m = Coral33EventMatcher(_stub)
    eid = m.match(
        "nba",
        home="San Antonio Spurs",
        away="Portland Trail Blazers",
        commence=datetime(2026, 4, 19, 19, 30, tzinfo=timezone.utc),  # +30 min
    )
    assert eid is None


def test_alias_map_resolves_name_mismatch():
    m = Coral33EventMatcher(_stub, team_aliases={
        "nba": {"la clippers": "los angeles clippers"}
    })
    # Add an LA Clippers event to the stub
    events = [{
        "event_id": "lac1",
        "home_team": "Los Angeles Clippers",
        "away_team": "Golden State Warriors",
        "commence_time": datetime(2026, 4, 19, 20, 0, tzinfo=timezone.utc),
    }]
    matcher = Coral33EventMatcher(lambda s: events if s == "nba" else [],
                                  team_aliases={"nba": {"la clippers": "los angeles clippers"}})
    eid = matcher.match("nba", home="LA Clippers", away="Golden State Warriors",
                        commence=datetime(2026, 4, 19, 20, 0, tzinfo=timezone.utc))
    assert eid == "lac1"


def test_no_match_returns_none():
    m = Coral33EventMatcher(_stub)
    eid = m.match("nba", home="Fake Team A", away="Fake Team B",
                  commence=datetime(2026, 4, 19, 19, 0, tzinfo=timezone.utc))
    assert eid is None


def test_naive_datetime_treated_as_utc():
    m = Coral33EventMatcher(_stub)
    eid = m.match("nba", home="San Antonio Spurs", away="Portland Trail Blazers",
                  commence=datetime(2026, 4, 19, 19, 0))  # tz-naive
    assert eid == "abc123"


def test_picks_closest_event_when_multiple_match():
    """If two events match by team name (unusual but possible with repeated
    matchups in day), pick the nearer commence time."""
    events = [
        {"event_id": "early", "home_team": "A", "away_team": "B",
         "commence_time": datetime(2026, 4, 19, 18, 50, tzinfo=timezone.utc)},
        {"event_id": "late",  "home_team": "A", "away_team": "B",
         "commence_time": datetime(2026, 4, 19, 19, 9, tzinfo=timezone.utc)},
    ]
    m = Coral33EventMatcher(lambda s: events)
    eid = m.match("nba", home="A", away="B",
                  commence=datetime(2026, 4, 19, 19, 7, tzinfo=timezone.utc))
    assert eid == "late"  # 2 min off vs 17 min off
