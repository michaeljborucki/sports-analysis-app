"""Normalizer tests for coral33 Get_LeagueLines2 responses.

Uses real HAR-captured responses saved under server/tests/fixtures/coral33/
as ground-truth input, with a stub event matcher.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.odds.books.coral33.normalizer import normalize_league_lines


FIXTURES = Path(__file__).parent / "fixtures" / "coral33"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _always_match(sport, home, away, commence):
    """Stub matcher — produces a deterministic event_id from the team names so
    tests can assert on structure without a real cache."""
    return f"EV:{sport}:{home}|{away}@{commence.isoformat()}"


def _never_match(sport, home, away, commence):
    return None


def test_nba_game_main_lines_emit_expected_markets():
    resp = _load("BASKETBALL_NBA_Game.json")
    now = datetime(2026, 4, 19, 18, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        resp, period="Game", sport_key="nba",
        fetched_at=now, match_event=_always_match,
    )

    market_keys = {r["market_key"] for r in rows}
    assert "h2h" in market_keys
    assert "spreads" in market_keys
    assert "totals" in market_keys
    # NBA has team totals on the main game line
    assert "team_totals" in market_keys

    # Every row has required schema fields and no market suffix
    for r in rows:
        assert r["bookmaker_key"] == "coral33"
        assert r["sport_key"] == "nba"
        assert r["event_id"].startswith("EV:")
        assert isinstance(r["price_american"], int)
        assert r["price_american"] != 0
        assert "_h" not in r["market_key"] and "_q" not in r["market_key"]


def test_nba_first_quarter_adds_q1_suffix():
    resp = _load("BASKETBALL_NBA_1st_Quarter.json")
    now = datetime(2026, 4, 19, 18, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        resp, period="1st Quarter", sport_key="nba",
        fetched_at=now, match_event=_always_match,
    )
    keys = {r["market_key"] for r in rows}
    # All emitted market keys must carry the _q1 suffix
    assert all(k.endswith("_q1") for k in keys), keys


def test_nhl_game_periods_resolve_to_p_suffix():
    resp = _load("HOCKEY_NHL_1st_Period.json")
    now = datetime(2026, 4, 19, 18, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        resp, period="1st Period", sport_key="nhl",
        fetched_at=now, match_event=_always_match,
    )
    keys = {r["market_key"] for r in rows}
    assert all(k.endswith("_p1") for k in keys), keys


def test_alt_line_emits_alternate_market_keys():
    resp = _load("BASKETBALL_NBA_ALT_LINE_Game.json")
    now = datetime(2026, 4, 19, 18, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        resp, period="Game", sport_key="nba",
        fetched_at=now, match_event=_always_match,
        is_alternate=True,
    )
    market_keys = {r["market_key"] for r in rows}
    # Alt mode writes under alternate_* keys
    assert "alternate_spreads" in market_keys
    # Alt rows don't emit ML
    assert "h2h" not in market_keys
    # Team names must have "Alt Line" suffix stripped before matching
    for r in rows:
        assert "Alt Line" not in r["home_team"]
        assert "Alt Line" not in r["away_team"]


def test_alt_line_with_no_total_only_emits_spread():
    """NHL alt fixture has row 1 with spread but no total. Make sure
    we don't fabricate zero-priced totals."""
    resp = _load("HOCKEY_HOCKEY_ALTER_Game.json")
    now = datetime(2026, 4, 19, 18, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        resp, period="Game", sport_key="nhl",
        fetched_at=now, match_event=_always_match,
        is_alternate=True,
    )
    # No row should have price_american == 0
    assert all(r["price_american"] != 0 for r in rows)


def test_orphan_events_are_dropped():
    resp = _load("BASKETBALL_NBA_Game.json")
    now = datetime(2026, 4, 19, 18, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        resp, period="Game", sport_key="nba",
        fetched_at=now, match_event=_never_match,
    )
    assert rows == []


def test_circled_games_skipped():
    """Rows with Status != 'O' are dropped (circled / closed)."""
    resp = _load("BASKETBALL_NBA_Game.json")
    # Simulate: mark one line as circled
    assert resp["Lines"]
    resp["Lines"][0] = {**resp["Lines"][0], "Status": "C"}
    rows = normalize_league_lines(
        resp, period="Game", sport_key="nba",
        fetched_at=datetime(2026, 4, 19, 18, tzinfo=timezone.utc),
        match_event=_always_match,
    )
    # First game's event_id should not appear
    # (this depends on the stub which uses team names; construct the expected
    # event id and assert absence)
    first = _load("BASKETBALL_NBA_Game.json")["Lines"][0]
    away = first["Team1ID"].strip()
    home = first["Team2ID"].strip()
    prefix = f"EV:nba:{home}|{away}"
    assert not any(r["event_id"].startswith(prefix) for r in rows)


def test_favored_team_determines_spread_sign():
    resp = _load("BASKETBALL_NBA_Game.json")
    # Grab raw Team1/Team2/Spread/FavoredTeamID for a well-defined game
    game = resp["Lines"][0]
    team1 = game["Team1ID"].strip()
    team2 = game["Team2ID"].strip()
    fav = game["FavoredTeamID"].strip()
    raw_spread = float(game["Spread"])  # negative, belongs to fav

    rows = normalize_league_lines(
        resp, period="Game", sport_key="nba",
        fetched_at=datetime(2026, 4, 19, 18, tzinfo=timezone.utc),
        match_event=_always_match,
    )
    spread_rows = [r for r in rows if r["market_key"] == "spreads"
                   and r["outcome_name"] in (team1, team2)]
    by_team = {r["outcome_name"]: r for r in spread_rows}
    assert len(by_team) == 2
    if fav == team1:
        assert by_team[team1]["outcome_point"] == raw_spread
        assert by_team[team2]["outcome_point"] == -raw_spread
    elif fav == team2:
        assert by_team[team2]["outcome_point"] == raw_spread
        assert by_team[team1]["outcome_point"] == -raw_spread


def test_unknown_period_produces_no_rows():
    resp = _load("BASKETBALL_NBA_Game.json")
    rows = normalize_league_lines(
        resp, period="5th Quarter Overtime Extreme",  # not in PERIOD_SUFFIX
        sport_key="nba",
        fetched_at=datetime(2026, 4, 19, 18, tzinfo=timezone.utc),
        match_event=_always_match,
    )
    assert rows == []
