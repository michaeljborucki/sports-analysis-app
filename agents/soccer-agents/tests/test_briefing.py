import pytest
from briefing import build_briefing

MOCK_MATCH_DATA = {
    "home_team": "Inter Miami CF",
    "away_team": "LA Galaxy",
    "league": "MLS",
    "matchday": "15",
    "venue": "Chase Stadium",
    "kickoff_time": "2026-03-25T23:30Z",
    "odds": {
        "asian_handicap": {"home": -0.5, "home_odds": -110, "away": 0.5, "away_odds": -110},
        "total": {"line": 2.5, "over_odds": -115, "under_odds": -105},
        "btts": {"yes_odds": -110, "no_odds": -110},
        "moneyline_1x2": {"home": -120, "draw": 260, "away": 300},
        "implied_probs": {"ah_home": 0.52, "ah_away": 0.48, "over": 0.54, "under": 0.46},
    },
    "home_stats": {
        "record": "8-3-4", "points": 27, "goals_for": 24, "goals_against": 15,
        "goal_diff": 9, "standing": "1st in Eastern Conference",
    },
    "away_stats": {
        "record": "6-5-4", "points": 22, "goals_for": 20, "goals_against": 18,
        "goal_diff": 2, "standing": "4th in Western Conference",
    },
    "home_xg": {"xg_per_match": 1.6, "xga_per_match": 1.0, "xg_overperformance": 0.2},
    "away_xg": {"xg_per_match": 1.3, "xga_per_match": 1.2, "xg_overperformance": 0.0},
    "home_injuries": [{"player": "Messi", "status": "Out", "injury": "Knee"}],
    "away_injuries": [],
    "context": {"home_motivation": "Title race", "away_motivation": "Mid-table",
                 "derby": False, "fixture_congestion": "Normal"},
}


def test_briefing_contains_soccer_sections():
    brief = build_briefing(MOCK_MATCH_DATA)
    assert "SOCCER MATCH PREDICTION" in brief
    assert "Asian Handicap" in brief
    assert "BTTS" in brief
    assert "xG" in brief
    assert "SQUAD AVAILABILITY" in brief
    assert "Inter Miami CF" in brief
    assert "LA Galaxy" in brief


def test_briefing_no_mlb_remnants():
    brief = build_briefing(MOCK_MATCH_DATA)
    assert "MLB" not in brief
    assert "PITCHING" not in brief
    assert "BULLPEN" not in brief
    assert "RUN LINE" not in brief
    assert "FIRST 5" not in brief
    assert "F5" not in brief
    assert "BALLPARK" not in brief


def test_briefing_contains_prediction_task():
    brief = build_briefing(MOCK_MATCH_DATA)
    assert "ASIAN HANDICAP" in brief
    assert "TOTAL GOALS" in brief
    assert "BOTH TEAMS TO SCORE" in brief
