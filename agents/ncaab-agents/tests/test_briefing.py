from briefing import build_briefing


def test_build_briefing_produces_string():
    game_data = {
        "away_team": "North Carolina",
        "home_team": "Duke",
        "away_stats": {
            "team": "North Carolina", "conference": "ACC",
            "trank": 12, "adj_oe": 115.5, "adj_de": 95.2, "adj_em": 20.3,
            "adj_tempo": 70.1, "sos": 0.80, "luck": 0.01,
            "record": "22-7", "conf_record": "13-5",
            "home_record": "14-2", "away_record": "6-4", "last_10": "7-3",
            "trend": "Won 3 straight",
            "efg_off": 52.1, "tov_off": 17.5, "oreb_off": 30.2, "ftr_off": 33.1,
            "efg_def": 46.5, "tov_def": 19.8, "oreb_def": 26.1, "ftr_def": 29.5,
            "three_rate": 37.5, "three_pct": 35.2,
            "adj_oe_rank": 15, "adj_de_rank": 20,
        },
        "home_stats": {
            "team": "Duke", "conference": "ACC",
            "trank": 5, "adj_oe": 118.2, "adj_de": 89.7, "adj_em": 28.5,
            "adj_tempo": 68.5, "sos": 0.85, "luck": 0.02,
            "record": "25-4", "conf_record": "15-3",
            "home_record": "16-0", "away_record": "7-3", "last_10": "9-1",
            "trend": "Won 5 straight",
            "efg_off": 54.2, "tov_off": 16.8, "oreb_off": 32.1, "ftr_off": 35.5,
            "efg_def": 44.1, "tov_def": 21.3, "oreb_def": 25.2, "ftr_def": 28.1,
            "three_rate": 38.5, "three_pct": 36.2,
            "adj_oe_rank": 8, "adj_de_rank": 3,
        },
        "away_roster": {
            "team": "North Carolina", "returning_minutes_pct": 65.0,
            "top_scorers": [{"name": "RJ Davis", "ppg": 18.5}],
            "transfers_in": [], "coach": "Hubert Davis",
            "coach_tenure": 4, "new_coach": False,
        },
        "home_roster": {
            "team": "Duke", "returning_minutes_pct": 55.0,
            "top_scorers": [{"name": "Cooper Flagg", "ppg": 20.1}],
            "transfers_in": [{"name": "Transfer X", "from": "Oregon", "ppg": 12.0}],
            "coach": "Jon Scheyer", "coach_tenure": 3, "new_coach": False,
        },
        "matchup": {
            "projected_tempo": 69.3, "projected_poss": 69.3,
            "efficiency_gap": 8.2, "projected_total": 145.5,
            "conference_game": True, "rivalry": True,
            "tournament_context": "Regular season",
            "quad_classification": "Quad 1",
            "home_court_advantage": 3.5,
            "mismatch_desc": "Similar pace (1.6 poss gap)",
            "travel_context": "N/A",
        },
        "odds": {
            "moneyline": {"home": -200, "away": 170},
            "spread": {"home": -6.5, "home_odds": -110, "away": 6.5, "away_odds": -110},
            "total": {"line": 142.5, "over_odds": -110, "under_odds": -110},
            "h1_moneyline": {"home": -160, "away": 140},
            "h1_total": {"line": 68.5, "over_odds": -115, "under_odds": -105},
            "h1_spread": {"home": -3.5, "home_odds": -110, "away": 3.5, "away_odds": -110},
            "implied_probs": {"ml_home": 0.67, "ml_away": 0.33},
        },
        "away_injuries": [],
        "home_injuries": [],
        "venue": "Cameron Indoor Stadium",
        "game_time": "7:00 PM ET",
    }
    briefing = build_briefing(game_data)
    assert isinstance(briefing, str)
    assert "North Carolina" in briefing
    assert "Duke" in briefing
    assert "EFFICIENCY PROFILES" in briefing
    assert "TEMPO MATCHUP" in briefing
    assert "ROSTER CONTEXT" in briefing
    assert "PREDICTION TASK" in briefing
    assert "Cameron Indoor Stadium" in briefing
