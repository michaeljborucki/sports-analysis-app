"""Tests for coral33 player-prop normalization.

Uses the real HAR-captured NBAPLAYERPRO response as the ground truth.
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from server.odds.books.coral33.normalizer import (
    _parse_coral_datetime,
    normalize_player_props,
)


FIXTURES = Path(__file__).parent / "fixtures" / "coral33"
# Before the fixture's 2026-04-19 19:00 (coral local) kickoff, so the
# board reads as upcoming rather than live.
NOW = datetime(2026, 4, 19, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("stat,market", [
    ("Completions", "player_pass_completions"),
    ("Interceptions", "player_pass_interceptions"),
    ("Longest Completion", "player_pass_longest_completion"),
    ("Pass Attempts", "player_pass_attempts"),
    ("Passing Yards", "player_pass_yds"),
    ("Rushing Yards", "player_rush_yds"),
    ("TD Passes", "player_pass_tds"),
    ("Longest Reception", "player_reception_longest"),
    ("Receiving Yards", "player_reception_yds"),
    ("Receptions", "player_receptions"),
    ("Reception", "player_receptions"),
    ("Points", "player_kicking_points"),
])
def test_nfl_prop_stats_emit_matching_over_under_markets(stat, market):
    response = {"Lines": [{
        "Status": "O", "Team1ID": "Test Player", "Team2ID": stat,
        "TotalPoints": 20.5, "TtlPtsAdj1": -105, "TtlPtsAdj2": -125,
        "CorrelationID": "451-g   ",
    }]}
    rows = normalize_player_props(response, "nfl", NOW, _stub_lookup)
    assert len(rows) == 2
    assert {r["market_key"] for r in rows} == {market}
    assert [(r["outcome_name"], r["price_american"]) for r in rows] == [
        ("test player Over", -105), ("test player Under", -125),
    ]
    assert all(r["outcome_point"] == 20.5 and r["event_id"] == "EV:451-g" for r in rows)


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _stub_lookup(correlation_id: object) -> dict | None:
    """Treat any non-empty CorrelationID as matched to a synthetic event_id.

    The kickoff mirrors the fixture's own `GameDateTime`: a prop line and its
    parent game always share a start time, and the normalizer now rejects a
    parent that disagrees (coral33 reuses CorrelationIDs across boards).
    """
    if not correlation_id:
        return None
    return {
        "event_id": f"EV:{correlation_id}",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": _parse_coral_datetime("2026-04-19 19:00:01.000"),
    }


def test_nba_prop_response_emits_player_scoped_rows():
    resp = _load("BASKETBALL_NBAPLAYERPRO_Game.json")
    rows = normalize_player_props(
        resp, sport_key="nba", fetched_at=NOW, game_num_lookup=_stub_lookup,
    )
    # Every prop row pairs with an Over/Under on the same (player, point)
    assert rows, "NBA prop fixture produced no rows"
    for r in rows:
        assert r["bookmaker_key"] == "coral33"
        assert r["sport_key"] == "nba"
        assert r["market_key"].startswith("player_")
        assert r["outcome_name"].endswith((" Over", " Under"))
        assert isinstance(r["price_american"], int)

    # Points → player_points expected at minimum
    mk = {r["market_key"] for r in rows}
    assert "player_points" in mk


def test_nba_prop_outcome_pairs_are_per_player():
    resp = _load("BASKETBALL_NBAPLAYERPRO_Game.json")
    rows = normalize_player_props(
        resp, sport_key="nba", fetched_at=NOW, game_num_lookup=_stub_lookup,
    )
    # For each (market_key, player, point) bucket there should be exactly one
    # Over + one Under (2 rows).
    buckets: dict[tuple, int] = {}
    for r in rows:
        name = r["outcome_name"]
        if name.endswith(" Over"):
            player = name[:-5]
        elif name.endswith(" Under"):
            player = name[:-6]
        else:
            continue
        key = (r["market_key"], player, r["outcome_point"])
        buckets[key] = buckets.get(key, 0) + 1
    # No bucket should have more than 2 rows
    assert all(n == 2 for n in buckets.values()), buckets


def test_unknown_stat_name_is_dropped_not_crashed():
    resp = {"Lines": [{
        "Status": "O",
        "Team1ID": "Some Player",
        "Team2ID": "Mystery Stat",  # not in map → skip
        "TotalPoints": 10.5,
        "TtlPtsAdj1": 100,
        "TtlPtsAdj2": -110,
        "CorrelationID": "503-g",
    }]}
    rows = normalize_player_props(
        resp, sport_key="nba", fetched_at=NOW, game_num_lookup=_stub_lookup,
    )
    assert rows == []


def test_unknown_correlation_drops_row_as_orphan():
    resp = {"Lines": [{
        "Status": "O",
        "Team1ID": "Some Player",
        "Team2ID": "Points",
        "TotalPoints": 10.5,
        "TtlPtsAdj1": 100,
        "TtlPtsAdj2": -110,
        "CorrelationID": "zzz-g",
    }]}
    rows = normalize_player_props(
        resp, sport_key="nba", fetched_at=NOW,
        game_num_lookup=lambda _n: None,
    )
    assert rows == []


def test_live_game_prop_rows_are_dropped():
    resp = {"Lines": [{
        "Status": "O",
        "Team1ID": "Some Player",
        "Team2ID": "Points",
        "TotalPoints": 10.5,
        "TtlPtsAdj1": 100,
        "TtlPtsAdj2": -110,
        "CorrelationID": "503-g",
    }]}
    def lookup(cid):
        return {
            "event_id": "ev1", "home_team": "H", "away_team": "A",
            "commence_time": NOW.replace(hour=17),  # 1h before NOW → live
        }
    rows = normalize_player_props(
        resp, sport_key="nba", fetched_at=NOW, game_num_lookup=lookup,
    )
    assert rows == []


def test_unconfigured_sport_returns_empty():
    """NHL has no PROP_STAT_TO_MARKET_KEY entry yet — must return empty
    rather than crash."""
    resp = {"Lines": [{
        "Status": "O",
        "Team1ID": "Some Player",
        "Team2ID": "Points",
        "TotalPoints": 10.5,
        "TtlPtsAdj1": 100,
        "TtlPtsAdj2": -110,
        "CorrelationID": "503-g",
    }]}
    rows = normalize_player_props(
        resp, sport_key="nhl", fetched_at=NOW, game_num_lookup=_stub_lookup,
    )
    assert rows == []


def test_coral33_receiving_yards_typo_still_maps():
    """Regression: coral33 spelled the stat "Receving Yards" (no `i`) on
    CorrelationID 453-g from 2026-09-09, and the exact-match stat lookup
    silently dropped every receiving-yards line for that game (893 hits in
    mapping health before anyone noticed). The typo must map like the
    correctly-spelled stat."""
    response = {"Lines": [{
        "Status": "O", "Team1ID": "Puka Nacua", "Team2ID": "Receving Yards",
        "TotalPoints": 72.5, "TtlPtsAdj1": -115, "TtlPtsAdj2": -115,
        "CorrelationID": "453-g",
    }]}
    rows = normalize_player_props(response, "nfl", NOW, _stub_lookup)
    assert [r["market_key"] for r in rows] == [
        "player_reception_yds", "player_reception_yds",
    ]
    assert [r["outcome_name"] for r in rows] == [
        "puka nacua Over", "puka nacua Under",
    ]


def _suffix_response(name: str) -> dict:
    return {"Lines": [{
        "Status": "O", "Team1ID": name, "Team2ID": "Receiving Yards",
        "TotalPoints": 55.5, "TtlPtsAdj1": -110, "TtlPtsAdj2": -110,
        "CorrelationID": "451-g", "GameDateTime": "2026-04-19 19:00:01.000",
    }]}


def test_suffixless_coral_name_adopts_events_jr_spelling():
    rows = normalize_player_props(
        _suffix_response("Brian Thomas"), "nfl", NOW, _stub_lookup,
        known_players=lambda ev: {"brian thomas jr", "travis etienne"},
    )
    assert {r["outcome_name"] for r in rows} == {
        "brian thomas jr Over", "brian thomas jr Under",
    }


def test_suffix_bridge_leaves_exact_and_ambiguous_names_alone():
    # Bare name already on the event — no rewrite.
    rows = normalize_player_props(
        _suffix_response("Brian Thomas"), "nfl", NOW, _stub_lookup,
        known_players=lambda ev: {"brian thomas", "brian thomas jr"},
    )
    assert {r["outcome_name"] for r in rows} == {"brian thomas Over", "brian thomas Under"}
    # Sr and Jr both present — refuse to guess.
    rows = normalize_player_props(
        _suffix_response("Brian Thomas"), "nfl", NOW, _stub_lookup,
        known_players=lambda ev: {"brian thomas sr", "brian thomas jr"},
    )
    assert {r["outcome_name"] for r in rows} == {"brian thomas Over", "brian thomas Under"}
    # Unrelated longer name ("brian thomason") is not a suffix.
    rows = normalize_player_props(
        _suffix_response("Brian Thomas"), "nfl", NOW, _stub_lookup,
        known_players=lambda ev: {"brian thomason"},
    )
    assert {r["outcome_name"] for r in rows} == {"brian thomas Over", "brian thomas Under"}
