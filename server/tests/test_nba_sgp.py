"""NBA same-game-parlay screener (server/nba/sgp.py)."""
from __future__ import annotations

import pytest

from server.nba.sgp import (
    PlayerGame,
    best_rung,
    breakeven_american,
    dvp,
    dvp_ranks,
    evaluate_player,
    parse_player_lines,
    position_group,
    usage_pct,
    wilson_lower,
)


def _g(pts, reb, ast, eid="e", team="t", opp="o", pos="G", mins=30, fga=15, fta=5, tov=2, stl=1, blk=0, aid="p"):
    return PlayerGame(aid, "P", pos, team, opp, eid, "2026-01-01T00:00Z",
                      mins, fga, fta, tov, pts, reb, ast, stl, blk)


def test_user_example_break_even_is_minus_900():
    """100% / 95% / 95% legs → ~90% → the book must beat about −900."""
    assert breakeven_american(0.90) == -900
    assert breakeven_american(0.5) == -100
    assert breakeven_american(0.25) == 300
    assert breakeven_american(1.0) is None


def test_best_rung_takes_highest_line_at_93_percent():
    values = [12] * 19 + [8]                    # 10+ hits 19/20 = 95%
    assert best_rung(values, (10, 15)) == {"line": 10, "hits": 19, "n": 20, "rate": 0.95}
    assert best_rung([5] * 20, (10, 15)) is None


def test_joint_rate_is_empirical_not_the_product():
    # Misses land in the SAME game (correlated legs): joint 19/20, product 0.9025.
    games = [_g(20, 6, 4) for _ in range(19)] + [_g(4, 1, 0)]
    r = evaluate_player(games)
    assert {k: v["line"] for k, v in r["legs"].items()} == {"points": 20, "rebounds": 6, "assists": 4}
    assert r["joint"] == {"hits": 19, "n": 20, "rate": 0.95}
    assert r["product"] == pytest.approx(0.95 ** 3)
    assert r["floor"] == pytest.approx(0.85)
    assert r["conservative"] < 0.95
    assert r["breakeven"] == -1900


def test_missing_leg_means_no_parlay():
    r = evaluate_player([_g(20, 1, 4) for _ in range(20)])   # never 3+ rebounds
    assert r["legs"]["rebounds"] is None and r["joint"] is None


def test_wilson_lower_bound_is_below_raw_rate():
    assert wilson_lower(19, 20) < 0.95
    assert wilson_lower(20, 20) < 1.0
    assert wilson_lower(0, 0) is None


def test_usage_matches_hand_calculation():
    # Player used 15 + .44*5 + 2 = 19.2 in 30 of 240 team minutes; team used 100.
    g = _g(20, 5, 5)
    usage = usage_pct([g], {("e", "t"): (100.0, 240)})
    assert usage == pytest.approx(100 * 19.2 / (30 / 48 * 100))


def test_dvp_rank_one_allows_the_most():
    games = [
        _g(30, 0, 0, eid="1", opp="soft", stl=0, tov=0),
        _g(10, 0, 0, eid="2", opp="hard", stl=0, tov=0),
    ]
    table = dvp(games)
    assert table["soft"]["G"] == 30 and table["hard"]["G"] == 10
    assert dvp_ranks(table)["soft"]["G"] == 1


def test_position_groups():
    assert [position_group(p) for p in ("PG", "SG", "G", "SF", "PF", "F", "C", None)] == list("GGGFFFCF")


def test_parse_player_lines_skips_dnp():
    block = {"statistics": [{
        "keys": ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
                 "freeThrowsMade-freeThrowsAttempted", "rebounds", "assists",
                 "turnovers", "steals", "blocks"],
        "athletes": [
            {"athlete": {"id": 1, "displayName": "A", "position": {"abbreviation": "PG"}},
             "stats": ["34", "28", "10-20", "6-7", "5", "9", "3", "2", "0"]},
            {"athlete": {"id": 2, "displayName": "B"}, "didNotPlay": True, "stats": []},
        ],
    }]}
    assert parse_player_lines(block) == [["1", "A", "G", 34, 20, 7, 3, 28, 5, 9, 2, 0]]
