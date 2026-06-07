from briefing import build_briefing


MOCK_GAME_DATA = {
    "league": "IPL",
    "match_number": 25,
    "date": "2026-03-25",
    "team_a": "MI",
    "team_b": "CSK",
    "team_a_full": "Mumbai Indians",
    "team_b_full": "Chennai Super Kings",
    "venue": "Wankhede Stadium",
    "day_night": "Night",
    "odds": {
        "moneyline": {"team_a": -130, "team_b": 110},
        "total_runs": {"line": 340.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"team_a": 0.565, "team_b": 0.435},
    },
    "venue_conditions": {
        "pitch_type": "batting",
        "boundary_size": "small",
        "avg_first_innings_score": 185,
        "avg_second_innings_score": 172,
        "bat_first_win_pct": "52%",
        "chase_win_pct": "48%",
        "dew_factor": "high",
        "weather": "clear, 28°C",
    },
    "toss": {
        "bat_first_win_pct": "52%",
        "chase_win_pct": "48%",
        "dew_impact": "significant in second innings",
        "recent_trend": "teams winning toss choosing to field",
    },
    "toss_result": "MI won toss, elected to bat",
    "team_a_profile": {
        "wins": 8,
        "losses": 4,
        "nrr": "+0.45",
        "batting_avg": 42.5,
        "team_strike_rate": 148.2,
        "powerplay_avg": 52,
        "death_avg": 58,
        "bowling_avg": 28.1,
        "economy": 8.2,
        "recent_record": "W W L W W",
    },
    "team_b_profile": {
        "wins": 7,
        "losses": 5,
        "nrr": "+0.12",
        "batting_avg": 39.8,
        "team_strike_rate": 143.5,
        "powerplay_avg": 48,
        "death_avg": 55,
        "bowling_avg": 29.4,
        "economy": 8.5,
        "recent_record": "L W W L W",
    },
    "team_a_players": [
        {"name": "Rohit Sharma", "role": "Bat", "batting_avg": 35.2, "strike_rate": 152.1, "recent_form": "45,12,78"},
        {"name": "Jasprit Bumrah", "role": "Bowl", "wickets": 18, "economy": 6.8, "recent_form": "3/22,1/18"},
    ],
    "team_b_players": [
        {"name": "MS Dhoni", "role": "WK-Bat", "batting_avg": 38.5, "strike_rate": 165.0, "recent_form": "22,44,10"},
        {"name": "Ravindra Jadeja", "role": "All", "batting_avg": 28.1, "strike_rate": 130.0, "wickets": 12, "economy": 7.2},
    ],
    "head_to_head": {
        "overall": "MI 20 - CSK 17",
        "at_venue": "MI 8 - CSK 5",
        "last_3": ["MI won by 5 wickets", "CSK won by 20 runs", "MI won by 4 wickets"],
    },
    "match_context": {
        "stage": "League Stage",
        "playoff_implications": "Top 4 race — both teams need wins",
        "pressure": "high",
    },
}


def test_build_briefing_produces_string():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert isinstance(briefing, str)
    assert len(briefing) > 100


def test_build_briefing_header():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "T20 CRICKET MATCH PREDICTION ANALYSIS" in briefing


def test_build_briefing_team_names():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "Mumbai Indians" in briefing
    assert "Chennai Super Kings" in briefing
    assert "MI" in briefing
    assert "CSK" in briefing


def test_build_briefing_venue_section():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "VENUE & CONDITIONS" in briefing
    assert "Wankhede Stadium" in briefing


def test_build_briefing_toss_section():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "TOSS IMPACT" in briefing


def test_build_briefing_betting_lines():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "Match Winner" in briefing
    assert "Total Runs" in briefing
    assert "340.5" in briefing


def test_build_briefing_sections():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "TEAM PROFILES" in briefing
    assert "HEAD-TO-HEAD" in briefing
    assert "MATCH CONTEXT" in briefing
    assert "PREDICTION TASK" in briefing


def test_build_briefing_player_names():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "Rohit Sharma" in briefing
    assert "Jasprit Bumrah" in briefing
    assert "MS Dhoni" in briefing


def test_build_briefing_no_mlb_references():
    briefing = build_briefing(MOCK_GAME_DATA)
    assert "MLB" not in briefing
    assert "pitcher" not in briefing.lower()
    assert "bullpen" not in briefing.lower()
    assert "run_line" not in briefing
    assert "first_5" not in briefing


def test_build_briefing_minimal_data():
    """build_briefing should not crash with minimal game_data."""
    minimal = {
        "team_a": "MI",
        "team_b": "CSK",
    }
    briefing = build_briefing(minimal)
    assert isinstance(briefing, str)
    assert "T20 CRICKET MATCH PREDICTION ANALYSIS" in briefing
    assert "MI" in briefing
    assert "CSK" in briefing
