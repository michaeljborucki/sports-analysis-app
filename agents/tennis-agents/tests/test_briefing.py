from briefing import build_briefing


def _sample_match_data():
    return {
        "tournament": "Wimbledon", "round": "QF", "surface": "grass",
        "indoor_outdoor": "outdoor", "best_of": 5,
        "player_a": {"name": "Djokovic", "ranking": 1, "elo": 2200, "surface_elo": 2150,
                      "season_record": "45-5", "surface_record": "12-1",
                      "serve_stats": {"first_serve_pct": "68%", "first_serve_win_pct": "78%",
                                      "second_serve_win_pct": "56%", "ace_rate": "8.2", "df_rate": "2.1"},
                      "return_stats": {"return_pts_won_pct": "42%", "bp_conversion_pct": "45%"},
                      "hand": "R", "backhand": "2H", "height": "188cm", "age": "38",
                      "days_since_last_match": 3, "recent_form": []},
        "player_b": {"name": "Alcaraz", "ranking": 2, "elo": 2180, "surface_elo": 2100,
                      "season_record": "40-8", "surface_record": "10-3",
                      "serve_stats": {"first_serve_pct": "65%", "first_serve_win_pct": "75%",
                                      "second_serve_win_pct": "52%", "ace_rate": "6.5", "df_rate": "3.0"},
                      "return_stats": {"return_pts_won_pct": "40%", "bp_conversion_pct": "42%"},
                      "hand": "R", "backhand": "2H", "height": "183cm", "age": "23",
                      "days_since_last_match": 2, "recent_form": []},
        "head_to_head": {"overall": "3-4", "surface": "1-2", "last_3": []},
        "odds": {
            "moneyline": {"player_a": -130, "player_b": 110},
            "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110,
                              "player_b_point": 3.5, "player_b_odds": -110},
            "total_games": {"line": 38.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"player_a": 0.565, "player_b": 0.435},
        },
        "conditions": {"surface": "grass", "indoor_outdoor": "outdoor",
                       "temperature": "72°F", "wind": "8mph", "altitude": "sea level", "session": "day"},
        "injuries": {"player_a": "None reported", "player_b": "None reported"},
    }


def test_build_briefing_contains_key_sections():
    briefing = build_briefing(_sample_match_data())
    assert "TENNIS MATCH PREDICTION" in briefing
    assert "Djokovic" in briefing
    assert "Alcaraz" in briefing
    assert "grass" in briefing.lower()
    assert "BETTING LINES" in briefing
    assert "HEAD-TO-HEAD" in briefing
    assert "PREDICTION TASK" in briefing


def test_build_briefing_no_mlb():
    briefing = build_briefing(_sample_match_data())
    assert "MLB" not in briefing
    assert "pitcher" not in briefing.lower()
    assert "bullpen" not in briefing.lower()
    assert "innings" not in briefing.lower()


def test_build_briefing_has_serve_stats():
    briefing = build_briefing(_sample_match_data())
    assert "Serve" in briefing or "serve" in briefing
    assert "Return" in briefing or "return" in briefing
