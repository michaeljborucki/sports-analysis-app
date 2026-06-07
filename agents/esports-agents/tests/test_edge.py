import pytest
from edge import (
    analyze_all_edges, check_moneyline_edge,
    check_map_handicap_edge, check_total_maps_edge,
    kelly_criterion,
)
from scrapers.odds import OddsData
from games.cs2 import config as cs2_config


def _make_odds(ml_a=-175, ml_b=145):
    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": ml_a, "team_b": ml_b},
        map_handicap={
            "team_a_line": -1.5, "team_a_odds": 150,
            "team_b_line": 1.5, "team_b_odds": -180,
        },
        total_maps={"line": 2.5, "over_odds": -130, "under_odds": 110},
    )
    od.compute_implied_probs()
    return od


def test_moneyline_edge_detected():
    sim = {"team_a_win_prob": 0.75, "team_b_win_prob": 0.25, "confidence": "high"}
    odds = _make_odds(ml_a=-150, ml_b=130)
    result = check_moneyline_edge(sim, odds, threshold=0.05)
    assert result is not None
    assert result["side"] == "team_a"
    assert result["edge"] > 0.05


def test_moneyline_no_edge():
    sim = {"team_a_win_prob": 0.55, "team_b_win_prob": 0.45, "confidence": "low"}
    odds = _make_odds(ml_a=-130, ml_b=110)
    result = check_moneyline_edge(sim, odds, threshold=0.05)
    # Edge should be small — 0.55 vs ~0.565 implied = negative edge
    assert result is None


def test_moneyline_edge_team_b():
    sim = {"team_a_win_prob": 0.30, "team_b_win_prob": 0.70, "confidence": "high"}
    odds = _make_odds(ml_a=-150, ml_b=130)
    result = check_moneyline_edge(sim, odds, threshold=0.05)
    assert result is not None
    assert result["side"] == "team_b"


def test_map_handicap_edge():
    sim = {"favorite_cover_prob": 0.60, "confidence": "medium"}
    odds = _make_odds()
    result = check_map_handicap_edge(sim, odds, threshold=0.06)
    assert result is not None


def test_map_handicap_no_edge():
    sim = {"favorite_cover_prob": 0.40, "confidence": "low"}
    odds = _make_odds()
    result = check_map_handicap_edge(sim, odds, threshold=0.06)
    # 0.40 is below implied, no edge
    assert result is None or result["side"] == "underdog"


def test_total_maps_over_edge():
    sim = {"over_prob": 0.65, "under_prob": 0.35, "confidence": "medium"}
    odds = _make_odds()
    result = check_total_maps_edge(sim, odds, threshold=0.05)
    assert result is not None
    assert result["side"] == "over"


def test_total_maps_under_edge():
    sim = {"over_prob": 0.30, "under_prob": 0.70, "confidence": "medium"}
    odds = _make_odds()
    result = check_total_maps_edge(sim, odds, threshold=0.05)
    assert result is not None
    assert result["side"] == "under"


def test_analyze_all_edges_bo3():
    sim = {
        "moneyline": {"team_a_win_prob": 0.75, "team_b_win_prob": 0.25, "confidence": "high"},
        "map_handicap": {"favorite_cover_prob": 0.60, "confidence": "medium"},
        "total_maps": {"over_prob": 0.65, "under_prob": 0.35, "confidence": "medium"},
    }
    odds = _make_odds()
    bets = analyze_all_edges(sim, odds, format="bo3", game_config=cs2_config)
    assert isinstance(bets, list)
    for bet in bets:
        assert "bet_type" in bet
        assert "side" in bet
        assert "edge" in bet
        assert "kelly_pct" in bet


def test_analyze_all_edges_bo1_skips_handicap_and_total():
    sim = {
        "moneyline": {"team_a_win_prob": 0.80, "team_b_win_prob": 0.20, "confidence": "high"},
        "map_handicap": {"favorite_cover_prob": 0.60, "confidence": "medium"},
        "total_maps": {"over_prob": 0.65, "under_prob": 0.35, "confidence": "medium"},
    }
    odds = _make_odds()
    bets = analyze_all_edges(sim, odds, format="bo1", game_config=cs2_config)
    bet_types = [b["bet_type"] for b in bets]
    assert "map_handicap" not in bet_types
    assert "total_maps" not in bet_types


def test_kelly_criterion():
    # 60% win prob at +100 odds (even money)
    kelly = kelly_criterion(0.60, 100)
    assert kelly > 0
    assert kelly < 0.10  # Quarter-Kelly should be modest
