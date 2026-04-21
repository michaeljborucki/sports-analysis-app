"""Tests for coral33 player-prop normalization.

Uses the real HAR-captured NBAPLAYERPRO response as the ground truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from server.odds.books.coral33.normalizer import normalize_player_props


FIXTURES = Path(__file__).parent / "fixtures" / "coral33"
NOW = datetime(2026, 4, 20, 18, 0, tzinfo=timezone.utc)


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _stub_lookup(correlation_id: object) -> dict | None:
    """Treat any non-empty CorrelationID as matched to a synthetic event_id."""
    if not correlation_id:
        return None
    return {
        "event_id": f"EV:{correlation_id}",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": NOW.replace(hour=22),
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
