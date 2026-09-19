"""College-football player props via Coral33's NCAAPLRPROPS board.

The Odds API sells NCAAF props too, but that tier stays disabled — these
markets arrive free through the same Coral33 path NFL props already use.
"""
from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.odds.books.coral33.mapping import (
    PROP_STAT_TO_MARKET_KEY,
    load_coral33_config,
)
from server.odds.books.coral33.normalizer import normalize_player_props

_FIXTURE = Path("server/tests/fixtures/coral33/FOOTBALL_NCAAPLRPROPS_Game.json")
# The live capture's CorrelationID 113-g is Arizona St @ Kansas — Coral33's
# own COLLEGE board says so, and the players on it (Cutter Boley, who
# transferred to Arizona State for 2026) check out.
_PARENT = {
    "event_id": "ncaaf-evt-1",
    "home_team": "Kansas Jayhawks",
    "away_team": "Arizona State Sun Devils",
    "commence_time": "2026-09-19T16:00:00+00:00",
}


def test_ncaaf_pulls_the_player_prop_subtype():
    cfg = load_coral33_config(Path("server/config/coral33.toml"))
    ncaaf = cfg.sports["ncaaf"]
    assert ncaaf.subtypes_prop == ["NCAAPLRPROPS"]
    assert ("FOOTBALL", "NCAAPLRPROPS", "Game") in ncaaf.prop_calls


@pytest.mark.parametrize("stat,market", [
    ("Passing Yards", "player_pass_yds"),
    ("Rushing Yards", "player_rush_yds"),
    ("Receiving Yards", "player_reception_yds"),
    ("TD Passes", "player_pass_tds"),
])
def test_observed_college_stats_map_to_market_keys(stat, market):
    assert PROP_STAT_TO_MARKET_KEY["ncaaf"][stat] == market


def test_college_board_normalizes_into_cache_rows():
    payload = json.loads(_FIXTURE.read_text())
    rows = normalize_player_props(
        payload, "ncaaf", datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
        lambda _corr: _PARENT,
    )
    assert rows, "expected prop rows from the live NCAAPLRPROPS capture"
    assert {r["market_key"] for r in rows} <= {
        "player_pass_yds", "player_rush_yds",
        "player_reception_yds", "player_pass_tds",
    }
    boley = [r for r in rows
             if r["market_key"] == "player_pass_yds"
             and r["outcome_name"].startswith("cutter boley")]
    assert {r["outcome_name"] for r in boley} == {
        "cutter boley Over", "cutter boley Under",
    }
    over = next(r for r in boley if r["outcome_name"].endswith("Over"))
    assert over["outcome_point"] == 235.5
    assert over["price_american"] == -115
    assert over["event_id"] == "ncaaf-evt-1"
    assert over["bookmaker_key"] == "coral33"


def test_unknown_college_stat_is_reported_not_silently_dropped():
    seen = []
    payload = {"Lines": [{
        "Status": "O", "Team1ID": "Some Player", "Team2ID": "Kickoff Return Yards",
        "CorrelationID": "999-g", "TotalPoints": 20.5,
        "TtlPtsAdj1": -110, "TtlPtsAdj2": -110,
    }]}
    rows = normalize_player_props(
        payload, "ncaaf", datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
        lambda _corr: _PARENT, report_issue=lambda **kw: seen.append(kw),
    )
    assert rows == []
    assert seen and seen[0]["kind"] == "stat"
    assert seen[0]["raw_name"] == "Kickoff Return Yards"


def test_paid_odds_api_prop_tier_stays_disabled_but_markets_are_registered():
    """Registering the keys lights up the Props page and Settings; the
    metered fetch tier is the user's call and must stay off."""
    cfg = tomllib.loads(Path("server/config/markets.ncaaf.toml").read_text())
    props = cfg["player_props"]
    assert props["enabled"] is False
    assert props["regions"] == []
    assert "player_pass_yds" in props["markets"]
    assert "player_reception_yds" in props["markets"]


# ─── correlation-id collisions (2026-09-19) ──────────────────────────

def _prop_line(player="Cutter Boley", kickoff="2026-09-19 10:00:01.000"):
    return {"Status": "O", "Team1ID": player, "Team2ID": "Passing Yards",
            "CorrelationID": "113-g", "GameDateTime": kickoff,
            "TotalPoints": 235.5, "TtlPtsAdj1": -115, "TtlPtsAdj2": -115}


def test_prop_is_dropped_when_the_parent_kicks_off_at_another_time():
    """Defensive: a CorrelationID is only unique within one Coral33 board, so
    a lookup that ever returns a different game must not be trusted. A prop
    line carries its own kickoff; require the parent to agree with it."""
    seen = []
    wrong_parent = {
        "event_id": "other-evt", "home_team": "Ohio State Buckeyes",
        "away_team": "Kent State Golden Flashes",
        "commence_time": "2026-09-19T23:00:00+00:00",   # 13h from the prop line
    }
    rows = normalize_player_props(
        {"Lines": [_prop_line()]}, "ncaaf",
        datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc),
        lambda _c: wrong_parent, report_issue=lambda **kw: seen.append(kw),
    )
    assert rows == []
    assert any(i["kind"] == "prop_parent" and not i.get("resolved") for i in seen)


def test_prop_is_kept_when_the_parent_kickoff_agrees():
    right_parent = {
        "event_id": "kansas-evt", "home_team": "Kansas Jayhawks",
        "away_team": "Arizona State Sun Devils",
        "commence_time": "2026-09-19T16:00:00+00:00",   # == 10:00:01 coral local
    }
    rows = normalize_player_props(
        {"Lines": [_prop_line()]}, "ncaaf",
        datetime(2026, 9, 19, 9, 0, tzinfo=timezone.utc),
        lambda _c: right_parent,
    )
    assert len(rows) == 2
    assert all(r["event_id"] == "kansas-evt" for r in rows)


def test_correlation_index_is_scoped_per_sport():
    """One flat dict meant an MLB '113-g' could overwrite an NFL '113-g'."""
    from server.odds.books.coral33.fetcher import correlation_key
    assert correlation_key("nfl", "113-g") != correlation_key("ncaaf", "113-g")
