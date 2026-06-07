"""Tests for the shared live-odds feed client and the feed-first path in
get_ncaab_odds. The direct Odds API path is covered by test_odds.py."""
from unittest.mock import MagicMock, patch

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


def _enable(monkeypatch, base="http://test-backend:8000", sport="ncaab"):
    monkeypatch.setattr(feed_mod, "ODDS_FEED_BASE_URL", base)
    monkeypatch.setattr(feed_mod, "ODDS_FEED_SPORT", sport)
    monkeypatch.setattr(feed_mod, "ODDS_FEED_TTL_SECONDS", 20)
    reset_cache()


def test_feed_disabled_when_sport_unset(monkeypatch):
    # Default ncaab config leaves ODDS_FEED_SPORT empty (backend has no
    # college-basketball sport yet), so the feed must be inert.
    monkeypatch.setattr(feed_mod, "ODDS_FEED_BASE_URL", "http://x:8000")
    monkeypatch.setattr(feed_mod, "ODDS_FEED_SPORT", "")
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
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"data": [{"id": "e1"}]}
    with patch.object(feed_mod.requests, "get", return_value=resp) as mock_get:
        get_feed_events()
        get_feed_events()
    assert mock_get.call_count == 1


def test_get_feed_event_lookup(monkeypatch):
    _enable(monkeypatch)
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"data": [{"id": "a"}, {"id": "b"}]}
    with patch.object(feed_mod.requests, "get", return_value=resp):
        assert get_feed_event("b") == {"id": "b"}
        assert get_feed_event("missing") is None


def _sample_event():
    return {
        "id": "feedevt1",
        "sport_key": "ncaab",
        "commence_time": "2026-06-07T23:05:00Z",
        "home_team": "Duke Blue Devils",
        "away_team": "Kentucky Wildcats",
        "bookmakers": [
            {"key": "fanduel", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Duke Blue Devils", "price": -150},
                    {"name": "Kentucky Wildcats", "price": 130},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -110, "point": 145.5},
                    {"name": "Under", "price": -110, "point": 145.5},
                ]},
            ]},
            {"key": "draftkings", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Duke Blue Devils", "price": -145},
                    {"name": "Kentucky Wildcats", "price": 125},
                ]},
            ]},
        ],
    }


def test_get_ncaab_odds_uses_feed(monkeypatch):
    import scrapers.odds as odds_mod
    monkeypatch.setattr(odds_mod, "feed_enabled", lambda: True)
    monkeypatch.setattr(odds_mod, "get_feed_events", lambda: [_sample_event()])
    # Direct Odds API must NOT be touched when the feed serves the data.
    monkeypatch.setattr(odds_mod.requests, "get",
                        MagicMock(side_effect=AssertionError("hit Odds API")))

    results = odds_mod.get_ncaab_odds()
    assert len(results) == 1
    od = results[0]
    assert od.home == "Duke Blue Devils"
    assert od.away == "Kentucky Wildcats"
    # Consensus moneyline across the two books (median of -150 and -145).
    assert od.moneyline["home"] == round((-150 + -145) / 2)
    assert od.total["line"] == 145.5


def test_get_ncaab_odds_falls_back_on_feed_error(monkeypatch):
    import scrapers.odds as odds_mod

    def boom():
        raise FeedUnavailable("backend down")

    monkeypatch.setattr(odds_mod, "feed_enabled", lambda: True)
    monkeypatch.setattr(odds_mod, "get_feed_events", boom)
    resp = MagicMock(status_code=200)
    resp.json.return_value = [_sample_event()]
    resp.headers = {"x-requests-remaining": "450"}
    with patch.object(odds_mod.requests, "get", return_value=resp):
        results = odds_mod.get_ncaab_odds()
    assert len(results) == 1  # fell through to the direct API path
