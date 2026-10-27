"""CFB points-per-play projection math (server/cfb/ppp.py)."""
import pytest

from server.cfb.ppp import (
    GameBox, TeamGame, build_ratings, parse_plays, predict_points,
)
from server.cfb.service import _game_box, _main_point


def test_parse_plays_is_pass_attempts_plus_rushes():
    stats = [
        {"name": "completionAttempts", "displayValue": "25/38"},
        {"name": "rushingAttempts", "displayValue": "27"},
    ]
    assert parse_plays(stats) == 65


def test_parse_plays_missing_piece_is_none_not_zero():
    assert parse_plays([{"name": "rushingAttempts", "displayValue": "27"}]) is None


def test_ratings_and_user_formula():
    # A vs B: A scores 35 on 70 plays, allows 21 on 60.
    # A vs C: A scores 21 on 70 plays, allows 28 on 80.
    boxes = [
        GameBox("1", TeamGame("A", 35, 70), TeamGame("B", 21, 60)),
        GameBox("2", TeamGame("C", 28, 80), TeamGame("A", 21, 70)),
    ]
    r = build_ratings(boxes)
    a, b = r["A"], r["B"]
    assert a.plays_per_game == 70
    assert a.off_ppp == pytest.approx(56 / 140)
    assert a.def_ppp == pytest.approx(49 / 140)
    assert b.def_ppp == pytest.approx(35 / 70)

    p = predict_points(a, b)
    # off: 70 × 0.4 = 28; def: 70 × 0.5 = 35; average 31.5
    assert p["off_estimate"] == pytest.approx(28.0)
    assert p["def_estimate"] == pytest.approx(35.0)
    assert p["points"] == pytest.approx(31.5)


def test_no_games_means_no_prediction():
    r = build_ratings([GameBox("1", TeamGame("A", 10, 50), TeamGame("B", 7, 55))])
    from server.cfb.ppp import TeamRating
    assert predict_points(r["A"], TeamRating("Z")) is None


def _event(home_score, away_score):
    return {"id": "9", "competitions": [{"competitors": [
        {"homeAway": "home", "score": home_score, "team": {"id": "1"}},
        {"homeAway": "away", "score": away_score, "team": {"id": "2"}},
    ]}]}


def test_game_box_requires_both_play_counts():
    assert _game_box(_event("21", "14"), {"1": 70, "2": None}) is None
    box = _game_box(_event("21", "14"), {"1": 70, "2": 62})
    assert (box.home.points, box.home.plays, box.away.points) == (21, 70, 14)


def test_main_point_takes_most_quoted_line_from_main_market():
    def price(pt):
        return {"bookmaker_key": "x", "price_american": -110, "point": pt}
    game = {"markets": [
        {"market_key": "spreads", "outcomes": [
            {"outcome_name": "Home", "prices": [price(-7.5), price(-7.5), price(-7)]},
        ]},
        {"market_key": "totals", "outcomes": [
            {"outcome_name": "Over", "prices": [price(51.5)]},
        ]},
    ]}
    assert _main_point(game, "spreads", "Home") == -7.5
    assert _main_point(game, "totals", "Over") == 51.5
    assert _main_point(game, "spreads", "Away") is None


def _sb_event(eid, home, away, hs, as_, completed=True):
    def comp(tid, ha, score):
        return {"homeAway": ha, "score": str(score),
                "team": {"id": tid, "displayName": f"Team {tid}", "abbreviation": tid}}
    return {
        "id": eid, "date": "2026-09-05T18:00Z",
        "competitions": [{
            "competitors": [comp(home, "home", hs), comp(away, "away", as_)],
            "status": {"type": {"completed": completed}},
        }],
    }


def test_fbs_and_fcs_slates_share_one_rating_pool(tmp_path):
    import asyncio

    from server.cfb.service import CfbPredictionService

    boards = {
        # week 1: FBS team A beats FCS team X; FCS X beats FCS Y.
        (80, 1): [_sb_event("1", "A", "X", 42, 7)],
        # groups=81 repeats FBS-vs-FCS games — must not double count.
        (81, 1): [_sb_event("1", "A", "X", 42, 7), _sb_event("2", "X", "Y", 28, 14)],
        # week 2 slate: one game per division.
        (80, 2): [_sb_event("3", "A", "B", 0, 0, completed=False)],
        (81, 2): [_sb_event("4", "Y", "X", 0, 0, completed=False)],
    }

    class Fake(CfbPredictionService):
        async def _scoreboard(self, client, week, group):
            w = week or 2
            return {"season": {"year": 2026}, "week": {"number": 2},
                    "events": boards.get((group, w), [])}

        async def _summary_plays(self, client, event_id):
            return {"A": 70, "X": 60, "Y": 65, "B": 66}

    out = asyncio.run(Fake(data_dir=tmp_path).get())
    by_id = {g["event_id"]: g for g in out["games"]}
    assert by_id["3"]["division"] == "fbs"
    assert by_id["4"]["division"] == "fcs"
    divisions = {t["team_id"]: t["division"] for t in out["teams"]}
    assert divisions == {"A": "fbs", "X": "fcs", "Y": "fcs"}
    x = next(t for t in out["teams"] if t["team_id"] == "X")
    # X's rates span its FBS game and its FCS game.
    assert x["games"] == 2
    a = next(t for t in out["teams"] if t["team_id"] == "A")
    assert a["games"] == 1
    assert len(out["games"]) == 2
    assert x["points_for_per_game"] == (7 + 28) / 2
    # FCS-vs-FCS game gets a projection; B has no games yet so its game doesn't.
    assert by_id["4"]["home"]["predicted_points"] is not None
    assert by_id["3"]["home"]["predicted_points"] is None
    # Cache keys: bare week for FBS, "fcs:<n>" for FCS.
    import json
    store = json.loads((tmp_path / "cfb_boxscores_2026.json").read_text())
    assert set(store["scoreboards"]) == {"1", "fcs:1"}
