"""Regression test for the doubleheader matcher in historical_backfill_date.

The Odds API returns BOTH games of a doubleheader at the same snapshot time
under different event_ids. The matcher must pick the correct event for each
scheduled game by commence_time proximity — NOT by the simple `(away, home)
→ event` dict that loses one of them.

The bug we fixed (2026-04-20): TB@STL on 2026-03-28 had two events; the dict
overwrite kept the wrong one (game 2 with no markets), causing zero captures
for the entire date until we re-ran with the fix.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from scrapers import closing_lines as cl
from scrapers.odds import OddsData


def _odds(away, home, commence_iso, event_id):
    o = OddsData(home=home, away=away, commence_time=commence_iso, event_id=event_id)
    o.moneyline = {"home": -120, "away": +110}
    o.run_line = {"home": -1.5, "home_odds": +130, "away": 1.5, "away_odds": -150}
    o.total = {"line": 8.5, "over_odds": -110, "under_odds": -110}
    return o


def test_doubleheader_picks_event_closest_to_schedule_first_pitch(tmp_path, monkeypatch):
    """Two TB@STL events at the same snapshot; matcher must pick the one whose
    commence_time matches the schedule's first_pitch."""
    csv_path = tmp_path / "closing_lines.csv"
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))

    # Schedule: TB@STL game 1 at 18:15 UTC (the one we want to capture)
    schedule = [{
        "game_pk": 12345,
        "away_team": "TB",
        "home_team": "STL",
        "game_date": "2026-03-28T18:15:00Z",
        "away_pitcher": "Snell",
        "home_pitcher": "Wainwright",
    }]

    # Snapshot returns BOTH games of the doubleheader.
    # The matcher should pick event_g1 (commence_time matches schedule's 18:15).
    snapshot_events = [
        _odds("TB", "STL", "2026-03-28T18:15:00Z", event_id="event_g1"),
        _odds("TB", "STL", "2026-03-28T22:15:00Z", event_id="event_g2"),
    ]

    with patch("scrapers.pitchers.get_probable_starters", return_value=schedule), \
         patch("scrapers.closing_lines.get_historical_mlb_odds", return_value=snapshot_events), \
         patch("scrapers.closing_lines.get_historical_event_odds",
               return_value=({}, {})) as mock_event_call:
        cl.historical_backfill_date("2026-03-28", include_additional=True)

    # The per-event additional fetch should have been called for event_g1, NOT event_g2
    called_event_ids = [call.args[0] for call in mock_event_call.call_args_list]
    assert "event_g1" in called_event_ids, "matcher should pick the game-1 event"
    assert "event_g2" not in called_event_ids, "matcher should not pick game-2 event"


def test_no_doubleheader_picks_only_match(tmp_path, monkeypatch):
    """Single game in snapshot — should still work (regression for the simple case)."""
    csv_path = tmp_path / "closing_lines.csv"
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))

    schedule = [{
        "game_pk": 99,
        "away_team": "BOS",
        "home_team": "NYY",
        "game_date": "2026-04-15T23:00:00Z",
        "away_pitcher": "X",
        "home_pitcher": "Y",
    }]
    events = [_odds("BOS", "NYY", "2026-04-15T23:00:00Z", event_id="solo_event")]

    with patch("scrapers.pitchers.get_probable_starters", return_value=schedule), \
         patch("scrapers.closing_lines.get_historical_mlb_odds", return_value=events), \
         patch("scrapers.closing_lines.get_historical_event_odds",
               return_value=({}, {})) as mock_event_call:
        cl.historical_backfill_date("2026-04-15", include_additional=True)

    called_ids = [call.args[0] for call in mock_event_call.call_args_list]
    assert called_ids == ["solo_event"]


def test_game_not_in_snapshot_is_skipped(tmp_path, monkeypatch):
    """Schedule has a game but snapshot doesn't — matcher skips it cleanly (no crash)."""
    csv_path = tmp_path / "closing_lines.csv"
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))

    schedule = [{
        "game_pk": 1, "away_team": "TB", "home_team": "STL",
        "game_date": "2026-03-28T18:15:00Z",
        "away_pitcher": "X", "home_pitcher": "Y",
    }]
    # Snapshot returns a different game entirely
    events = [_odds("BOS", "NYY", "2026-03-28T18:15:00Z", event_id="other")]

    with patch("scrapers.pitchers.get_probable_starters", return_value=schedule), \
         patch("scrapers.closing_lines.get_historical_mlb_odds", return_value=events), \
         patch("scrapers.closing_lines.get_historical_event_odds",
               return_value=({}, {})) as mock_event_call:
        summary = cl.historical_backfill_date("2026-03-28", include_additional=True)

    # No event call should have been made for our scheduled game
    called_ids = [call.args[0] for call in mock_event_call.call_args_list]
    assert "other" not in called_ids
    assert summary["captured_games"] == 0
