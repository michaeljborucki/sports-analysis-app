"""Tests for multi-anchor date-only matching in PolymarketEventMatcher (M3)."""
from datetime import datetime, timedelta, timezone


def _et_utc(year, month, day, hour, minute=0):
    """ET datetime returned as a UTC-tz datetime. June 2026 is in EDT
    (UTC-4); this helper hardcodes that to keep the fixtures portable."""
    base = datetime(year, month, day, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(hours=hour + 4, minutes=minute)


def _events(*event_specs):
    """Build a (sport → events) callable for the matcher fixture."""
    by_sport: dict[str, list[dict]] = {}
    for sport, eid, home, away, commence in event_specs:
        by_sport.setdefault(sport, []).append({
            "event_id": eid, "home_team": home, "away_team": away,
            "commence_time": commence,
        })
    return lambda sport: by_sport.get(sport, [])


def test_multi_anchor_picks_closest_to_anchor():
    """Two same-team events on same day; multi-anchor scan picks the
    event closest to one of the candidate anchors."""
    from server.odds.books.polymarket.event_matcher import PolymarketEventMatcher
    events = _events(
        ("nba", "ev_day", "Boston Celtics", "Miami Heat", _et_utc(2026, 6, 21, 13, 0)),
        ("nba", "ev_pm",  "Boston Celtics", "Miami Heat", _et_utc(2026, 6, 21, 20, 0)),
    )
    matcher = PolymarketEventMatcher(cache_events_for_sport=events)
    # NBA anchors per _anchor_table: {7pm ET, 10pm ET}. 8pm event is
    # closer to 7pm anchor → picks ev_pm.
    result = matcher.match_multi_anchor(
        "nba", "Boston Celtics", "Miami Heat",
        candidate_commences=[
            _et_utc(2026, 6, 21, 19, 0),
            _et_utc(2026, 6, 21, 22, 0),
        ],
        tight_window_min=180,
    )
    assert result is not None
    assert result["event_id"] == "ev_pm"


def test_multi_anchor_returns_none_when_no_anchor_hits():
    """If all anchors are too far from any event, return None."""
    from server.odds.books.polymarket.event_matcher import PolymarketEventMatcher
    # A single event at 2am ET (way outside any anchor window)
    events = _events(
        ("nba", "ev1", "Boston Celtics", "Miami Heat", _et_utc(2026, 6, 21, 2, 0)),
    )
    matcher = PolymarketEventMatcher(cache_events_for_sport=events)
    result = matcher.match_multi_anchor(
        "nba", "Boston Celtics", "Miami Heat",
        candidate_commences=[
            _et_utc(2026, 6, 21, 19, 0),
            _et_utc(2026, 6, 21, 22, 0),
        ],
        tight_window_min=180,
    )
    assert result is None
