"""Tests for briefing.py."""
from briefing import build_briefing, _format_injuries


def test_format_injuries_empty():
    assert _format_injuries([]) == "No notable injuries"


def test_format_injuries():
    injuries = [
        {"player": "LeBron James", "status": "Out"},
        {"player": "AD", "status": "Questionable"},
    ]
    result = _format_injuries(injuries)
    assert "LeBron James" in result
    assert "Out" in result


def test_build_briefing_contains_nba_header():
    game_data = {
        "away_team": "LAL", "home_team": "BOS",
        "away_record": "40-25", "home_record": "50-15",
        "away_stats": {"ortg": 112.0, "drtg": 110.0, "net_rtg": 2.0, "pace": 100.0,
                       "efg_pct": 0.530, "tov_pct": 0.130, "three_rate": 0.380,
                       "three_pct": 0.360, "last_10": "6-4", "trend": "W2",
                       "away_record": "18-15"},
        "home_stats": {"ortg": 118.0, "drtg": 106.0, "net_rtg": 12.0, "pace": 98.0,
                       "efg_pct": 0.560, "tov_pct": 0.120, "three_rate": 0.400,
                       "three_pct": 0.390, "last_10": "8-2", "trend": "W5",
                       "home_record": "28-5"},
        "away_rest": {"days_rest": 1, "is_b2b": False, "games_last_7": 3,
                      "travel_miles": 500},
        "home_rest": {"days_rest": 2, "is_b2b": False, "games_last_7": 2,
                      "travel_miles": 0},
        "matchup": {"h2h_record": "1-1", "last_meeting": "LAL 110, BOS 108",
                     "pace_matchup": {"projected_pace": 99.0,
                                      "projected_possessions": 99,
                                      "mismatch": "Similar pace"}},
        "arena": "TD Garden", "game_time": "7:30 PM ET",
        "odds": {
            "moneyline": {"home": -200, "away": 170},
            "spread": {"home": -5.5, "home_odds": -110, "away": 5.5, "away_odds": -110},
            "total": {"line": 220.5, "over_odds": -110, "under_odds": -110},
            "h1_spread": {"home": -3.0, "home_odds": -110},
            "h1_total": {"line": 110.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"ml_home": 0.65, "ml_away": 0.35},
        },
        "away_injuries": [{"player": "AD", "status": "Questionable"}],
        "home_injuries": [],
    }
    brief = build_briefing(game_data)
    assert "NBA GAME PREDICTION ANALYSIS" in brief
    assert "LAL" in brief and "BOS" in brief
    assert "TEAM PROFILES" in brief
    assert "PACE MATCHUP" in brief
    assert "INJURIES" in brief
    assert "PREDICTION TASK" in brief
    assert "MLB" not in brief
    assert "PITCHING" not in brief
    assert "BULLPEN" not in brief
    assert "Run Line" not in brief


def test_briefing_includes_team_totals_section():
    # Use existing fixture pattern but add team_totals to odds
    from briefing import build_briefing
    game_data = {
        "away_team": "LAL", "home_team": "BOS",
        "away_record": "30-40", "home_record": "47-23",
        "away_stats": {}, "home_stats": {},
        "away_rest": {}, "home_rest": {},
        "matchup": {"pace_matchup": {}},
        "arena": "TD Garden", "game_time": "7:30 PM",
        "odds": {
            "moneyline": {}, "spread": {}, "total": {},
            "h1_spread": {}, "h1_total": {},
            "implied_probs": {},
            "team_totals": {
                "home": {"line": 112.5, "over_odds": -110, "under_odds": -110},
                "away": {"line": 106.5, "over_odds": -110, "under_odds": -110},
            },
        },
        "away_injuries": [], "home_injuries": [],
    }
    brief = build_briefing(game_data)
    assert "TEAM TOTALS" in brief
