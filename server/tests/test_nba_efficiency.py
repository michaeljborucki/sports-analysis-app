"""NBA possession-efficiency model (server/nba/efficiency.py)."""
from __future__ import annotations

import pytest

from server.nba.efficiency import (
    GameBox,
    TeamGame,
    TeamRating,
    build_ratings,
    parse_counts,
    possessions,
    predict_pace_matched,
    predict_points,
)
from server.nba.service import _usable, season_months


def _rating(pace, off, de, games=10):
    poss = pace * games
    return TeamRating("x", games=games, possessions=poss, points_for=round(off * poss),
                      points_against=round(de * poss), opp_possessions=poss)


def test_user_example_bos_at_det():
    """The pasted worked example: BOS 1.159 off / 1.085 def / 98.5 pace,
    DET 1.124 off / 1.054 def / 103.1 pace."""
    bos = TeamRating("bos", 1, 98.5, 0, 0, 1.0)
    bos.points_for, bos.points_against = 1.159 * 98.5, 1.085 * 1.0
    det = TeamRating("det", 1, 103.1, 0, 0, 1.0)
    det.points_for, det.points_against = 1.124 * 103.1, 1.054 * 1.0
    b, d = predict_points(bos, det), predict_points(det, bos)
    assert b["off_estimate"] == pytest.approx(114.16, abs=0.01)
    assert b["def_estimate"] == pytest.approx(103.82, abs=0.01)
    assert b["points"] == pytest.approx(108.99, abs=0.01)   # the paste says 108.88 (arithmetic slip)
    assert d["off_estimate"] == pytest.approx(115.88, abs=0.01)
    assert d["def_estimate"] == pytest.approx(111.86, abs=0.01)
    assert d["points"] == pytest.approx(113.87, abs=0.01)


def test_pace_matched_puts_both_teams_on_one_pace():
    slow, fast = _rating(98.0, 1.15, 1.10), _rating(104.0, 1.15, 1.10)
    # Identical efficiencies: own-pace model favors the faster team by ~6.9,
    # pace-matched calls it even.
    own = predict_points(fast, slow)["points"] - predict_points(slow, fast)["points"]
    assert own == pytest.approx(6.0 * 1.125, abs=0.05)
    assert predict_pace_matched(fast, slow) == pytest.approx(predict_pace_matched(slow, fast), abs=0.05)


def test_parse_counts_and_possessions_from_espn_box():
    stats = [
        {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "40-86"},
        {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "12-18"},
        {"name": "offensiveRebounds", "displayValue": "4"},
        {"name": "turnovers", "displayValue": "15"},
        {"name": "totalTurnovers", "displayValue": "16"},
    ]
    counts = parse_counts(stats)
    assert counts == {"fga": 86, "fta": 18, "oreb": 4, "tov": 16}
    assert possessions(counts) == pytest.approx(86 - 4 + 16 + 0.44 * 18)


def test_partial_box_is_rejected():
    assert parse_counts([{"name": "offensiveRebounds", "displayValue": "4"}]) is None


def test_build_ratings_credits_both_sides():
    box = GameBox("1", TeamGame("h", 110, 100.0), TeamGame("a", 100, 98.0))
    r = build_ratings([box])
    assert r["h"].off_eff == pytest.approx(1.10)
    assert r["h"].def_eff == pytest.approx(100 / 98.0)
    assert r["a"].pace == pytest.approx(98.0)


def test_only_completed_regular_season_games_count():
    def ev(stype, done, ctype="STD"):
        return {"season": {"type": stype},
                "competitions": [{"type": {"abbreviation": ctype},
                                  "status": {"type": {"completed": done}}}]}
    assert _usable(ev(2, True))
    assert not _usable(ev(2, True, "ALLSTAR"))
    assert not _usable(ev(1, True))   # preseason
    assert not _usable(ev(3, True))   # playoffs
    assert not _usable(ev(2, False))


def test_season_months_span_october_to_june():
    months = season_months(2027)
    assert months[0] == (2026, 10) and months[-1] == (2027, 6)
