"""Tests for the shared live-odds feed client and the feed-first paths in the
odds scrapers. The direct Odds API paths are covered by test_odds.py."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import requests

import scrapers.odds_feed as feed_mod
from scrapers.odds_feed import (
    FeedUnavailable,
    feed_enabled,
    get_feed_event,
    get_feed_events,
    reset_cache,
)


def _enable(monkeypatch, base="http://test-backend:8000", sport="mlb", max_stale=900):
    monkeypatch.setattr(feed_mod, "ODDS_FEED_BASE_URL", base)
    monkeypatch.setattr(feed_mod, "ODDS_FEED_SPORT", sport)
    monkeypatch.setattr(feed_mod, "ODDS_FEED_TTL_SECONDS", 20)
    monkeypatch.setattr(feed_mod, "ODDS_FEED_MAX_STALE_SECONDS", max_stale)
    reset_cache()


def _ok_resp(events, stale_seconds=5):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"data": events, "stale_seconds": stale_seconds}
    return resp


# ───────────────────────── feed client ─────────────────────────

def test_feed_disabled_raises(monkeypatch):
    monkeypatch.setattr(feed_mod, "ODDS_FEED_BASE_URL", "")
    reset_cache()
    assert not feed_enabled()
    with pytest.raises(FeedUnavailable):
        get_feed_events()


def test_feed_success(monkeypatch):
    _enable(monkeypatch)
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"data": [{"id": "e1"}], "stale_seconds": 5}
    with patch.object(feed_mod.requests, "get", return_value=resp):
        events = get_feed_events()
    assert events == [{"id": "e1"}]


def test_feed_non_200_raises(monkeypatch):
    _enable(monkeypatch)
    resp = MagicMock(status_code=503)
    with patch.object(feed_mod.requests, "get", return_value=resp):
        with pytest.raises(FeedUnavailable):
            get_feed_events()


def test_feed_connection_error_raises(monkeypatch):
    _enable(monkeypatch)
    with patch.object(feed_mod.requests, "get",
                      side_effect=requests.ConnectionError("refused")):
        with pytest.raises(FeedUnavailable):
            get_feed_events()


def test_feed_memoized_within_ttl(monkeypatch):
    _enable(monkeypatch)
    with patch.object(feed_mod.requests, "get", return_value=_ok_resp([{"id": "e1"}])) as mock_get:
        get_feed_events()
        get_feed_events()
    assert mock_get.call_count == 1


def test_get_feed_event_lookup(monkeypatch):
    _enable(monkeypatch)
    resp = _ok_resp([{"id": "a"}, {"id": "b"}])
    with patch.object(feed_mod.requests, "get", return_value=resp):
        assert get_feed_event("b") == {"id": "b"}
        assert get_feed_event("missing") is None


# ───────────────────────── staleness guard ─────────────────────────

def test_feed_rejects_stale(monkeypatch):
    _enable(monkeypatch, max_stale=900)
    with patch.object(feed_mod.requests, "get", return_value=_ok_resp([{"id": "e1"}], stale_seconds=1200)):
        with pytest.raises(FeedUnavailable):
            get_feed_events()


def test_feed_rejects_never_fetched(monkeypatch):
    _enable(monkeypatch, max_stale=900)
    with patch.object(feed_mod.requests, "get", return_value=_ok_resp([{"id": "e1"}], stale_seconds=None)):
        with pytest.raises(FeedUnavailable):
            get_feed_events()


def test_feed_accepts_fresh_under_threshold(monkeypatch):
    _enable(monkeypatch, max_stale=900)
    with patch.object(feed_mod.requests, "get", return_value=_ok_resp([{"id": "e1"}], stale_seconds=120)):
        assert get_feed_events() == [{"id": "e1"}]


def test_feed_stale_guard_disabled(monkeypatch):
    _enable(monkeypatch, max_stale=0)
    with patch.object(feed_mod.requests, "get", return_value=_ok_resp([{"id": "e1"}], stale_seconds=None)):
        assert get_feed_events() == [{"id": "e1"}]


# ─────────────────────── market coverage warning ───────────────────────

def test_warn_missing_markets_flags_absent(caplog):
    from scrapers.odds_feed import warn_missing_markets
    events = [{"bookmakers": [{"markets": [{"key": "h2h"}, {"key": "totals"}]}]}]
    with caplog.at_level("WARNING"):
        missing = warn_missing_markets(events, {"h2h", "totals", "spreads", "team_totals"}, "mlb")
    assert missing == ["spreads", "team_totals"]
    assert "spreads" in caplog.text and "team_totals" in caplog.text


def test_warn_missing_markets_silent_when_all_present(caplog):
    from scrapers.odds_feed import warn_missing_markets
    events = [{"bookmakers": [{"markets": [{"key": "h2h"}, {"key": "spreads"}]}]}]
    with caplog.at_level("WARNING"):
        missing = warn_missing_markets(events, {"h2h", "spreads"}, "mlb")
    assert missing == []
    assert caplog.text == ""


def test_prop_market_keys_match_source():
    """_PROP_MARKET_KEYS is duplicated from props_edge.PROP_MARKETS to avoid a
    heavy import; pin them equal so they can't drift."""
    from scrapers.odds import _PROP_MARKET_KEYS
    from simulation.props_edge import PROP_MARKETS
    assert _PROP_MARKET_KEYS == set(PROP_MARKETS.split(","))


# ───────────────── feed-first paths in scrapers.odds ─────────────────

def _near_future_event():
    """A native-shape event a few hours out so it survives the day filter."""
    soon = datetime.now(timezone.utc) + timedelta(hours=3)
    commence = soon.strftime("%Y-%m-%dT%H:%M:%SZ")
    eastern_date = soon.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    event = {
        "id": "feedevt1",
        "sport_key": "mlb",
        "commence_time": commence,
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [{
            "key": "fanduel",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -150},
                    {"name": "Boston Red Sox", "price": 130},
                ]},
                {"key": "team_totals", "outcomes": [
                    {"name": "Over", "price": -115, "point": 4.5,
                     "description": "New York Yankees"},
                    {"name": "Under", "price": -105, "point": 4.5,
                     "description": "New York Yankees"},
                ]},
                {"key": "pitcher_strikeouts", "outcomes": [
                    {"name": "Over", "price": -120, "point": 5.5,
                     "description": "Drew Rasmussen"},
                    {"name": "Under", "price": 100, "point": 5.5,
                     "description": "Drew Rasmussen"},
                ]},
            ],
        }],
    }
    return event, eastern_date


def test_get_mlb_odds_uses_feed(monkeypatch):
    import scrapers.odds as odds_mod
    event, eastern_date = _near_future_event()
    monkeypatch.setattr(odds_mod, "feed_enabled", lambda: True)
    monkeypatch.setattr(odds_mod, "get_feed_events", lambda: [event])
    # Direct Odds API must NOT be touched when the feed serves the data.
    monkeypatch.setattr(odds_mod.requests, "get",
                        MagicMock(side_effect=AssertionError("hit Odds API")))

    results = odds_mod.get_mlb_odds(date=eastern_date)
    assert len(results) == 1
    assert results[0].home == "NYY"
    assert results[0].away == "BOS"
    assert results[0].moneyline["home"] == -150


def test_get_additional_odds_uses_feed(monkeypatch):
    import scrapers.odds as odds_mod
    event, _ = _near_future_event()
    monkeypatch.setattr(odds_mod, "feed_enabled", lambda: True)
    monkeypatch.setattr(odds_mod, "get_feed_event", lambda eid: event)
    monkeypatch.setattr(odds_mod.requests, "get",
                        MagicMock(side_effect=AssertionError("hit Odds API")))

    merged = odds_mod.get_additional_odds("feedevt1")
    # team_totals requested by ADDITIONAL_MARKETS; props filtered out.
    assert "team_totals" in merged
    assert "pitcher_strikeouts" not in merged
    tt_names = {o["name"] for o in merged["team_totals"]["outcomes"]}
    assert tt_names == {"Over", "Under"}


def test_get_additional_odds_feed_missing_event(monkeypatch):
    import scrapers.odds as odds_mod
    monkeypatch.setattr(odds_mod, "feed_enabled", lambda: True)
    monkeypatch.setattr(odds_mod, "get_feed_event", lambda eid: None)
    monkeypatch.setattr(odds_mod.requests, "get",
                        MagicMock(side_effect=AssertionError("hit Odds API")))
    assert odds_mod.get_additional_odds("nope") == {}


def test_get_additional_odds_falls_back_on_feed_error(monkeypatch):
    import scrapers.odds as odds_mod
    monkeypatch.setattr(odds_mod, "feed_enabled", lambda: True)

    def boom(_eid):
        raise FeedUnavailable("backend down")

    monkeypatch.setattr(odds_mod, "get_feed_event", boom)
    # Budget guard returns {} before any HTTP call — proves we reached the
    # direct path rather than crashing on the feed error.
    assert odds_mod.get_additional_odds("evt", api_requests_remaining=0) == {}


def test_get_prop_odds_uses_feed(monkeypatch):
    import simulation.props_edge as props_mod
    event, _ = _near_future_event()
    monkeypatch.setattr(props_mod, "feed_enabled", lambda: True)
    monkeypatch.setattr(props_mod, "get_feed_event", lambda eid: event)
    monkeypatch.setattr(props_mod.requests, "get",
                        MagicMock(side_effect=AssertionError("hit Odds API")))

    props = props_mod.get_prop_odds("feedevt1")
    assert "pitcher_strikeouts" in props
    assert props["pitcher_strikeouts"]["Drew Rasmussen"]["line"] == 5.5
    assert props["pitcher_strikeouts"]["Drew Rasmussen"]["over_odds"] == -120
