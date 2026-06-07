"""Tests for CS2 briefing template and system prompt."""
from games.cs2.briefing import build_briefing
from games.cs2.prompt import CS2_SYSTEM_PROMPT


def test_briefing_contains_team_names():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "Natus Vincere" in result
    assert "FaZe Clan" in result


def test_briefing_contains_betting_lines():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "BETTING LINES" in result
    assert "Moneyline" in result


def test_briefing_contains_map_pool():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "Map Pool" in result or "MAP" in result


def test_briefing_contains_prediction_task():
    match_data = _make_mock_match_data()
    result = build_briefing(match_data)
    assert "PREDICTION TASK" in result
    assert "MATCH WINNER" in result
    assert "MAP HANDICAP" in result
    assert "TOTAL MAPS" in result


def test_system_prompt_has_six_analysts():
    assert "FRAGGING ANALYST" in CS2_SYSTEM_PROMPT
    assert "TACTICAL ANALYST" in CS2_SYSTEM_PROMPT
    assert "MAP POOL ANALYST" in CS2_SYSTEM_PROMPT
    assert "FORM" in CS2_SYSTEM_PROMPT
    assert "MARKET ANALYST" in CS2_SYSTEM_PROMPT
    assert "CONTRARIAN" in CS2_SYSTEM_PROMPT


def test_system_prompt_requests_json():
    assert "JSON" in CS2_SYSTEM_PROMPT
    assert "team_a_win_prob" in CS2_SYSTEM_PROMPT
    assert "map_handicap" in CS2_SYSTEM_PROMPT
    assert "total_maps" in CS2_SYSTEM_PROMPT


def _make_mock_match_data():
    return {
        "tournament": "IEM Katowice 2026",
        "date": "2026-03-20",
        "format": "bo3",
        "bo_count": 3,
        "tier": 1,
        "team_a": {
            "name": "Natus Vincere",
            "hltv_ranking": 1,
            "win_rate_3m": 0.75,
            "win_rate_6m": 0.70,
            "lan_record": "15-3",
            "online_record": "20-8",
            "roster": ["s1mple", "electroNic", "b1t", "Perfecto", "npl"],
            "coach": "B1ad3",
            "days_since_roster_change": 45,
            "map_pool": {
                "mirage": {"win_rate": 0.80, "games": 15},
                "inferno": {"win_rate": 0.65, "games": 12},
                "nuke": {"win_rate": 0.70, "games": 8},
            },
            "recent_form": [
                {"date": "2026-03-18", "opponent": "FaZe", "score": "2-0", "tournament": "IEM"},
            ],
        },
        "team_b": {
            "name": "FaZe Clan",
            "hltv_ranking": 3,
            "win_rate_3m": 0.68,
            "win_rate_6m": 0.65,
            "lan_record": "12-5",
            "online_record": "18-10",
            "roster": ["rain", "frozen", "ropz", "broky", "karrigan"],
            "coach": "RobbaN",
            "days_since_roster_change": 90,
            "map_pool": {
                "inferno": {"win_rate": 0.70, "games": 10},
                "nuke": {"win_rate": 0.60, "games": 8},
            },
            "recent_form": [
                {"date": "2026-03-17", "opponent": "G2", "score": "2-1", "tournament": "IEM"},
            ],
        },
        "odds": {
            "moneyline": {"team_a": -175, "team_b": 145},
            "map_handicap": {"team_a_line": -1.5, "team_a_odds": 150, "team_b_line": 1.5, "team_b_odds": -180},
            "total_maps": {"line": 2.5, "over_odds": -130, "under_odds": 110},
            "implied_probs": {"ml_team_a": 0.636, "ml_team_b": 0.364},
        },
        "head_to_head": {"team_a_wins": 3, "team_b_wins": 2, "recent_5": []},
        "patch": {"patch_version": "1.39", "days_since_patch": 5, "key_changes": ["AK-47 recoil adjusted"], "impact_rating": "minor"},
        "context": {"online_lan": "lan", "stage": "playoff", "stakes": "semifinal"},
    }
