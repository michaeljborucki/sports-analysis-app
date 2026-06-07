"""Tests for the briefing dispatcher (briefing.py)."""
from unittest.mock import patch, MagicMock
import pytest
from briefing import build_briefing


# ---------------------------------------------------------------------------
# Minimal CS2 match data for a real dispatch
# ---------------------------------------------------------------------------

CS2_MATCH_DATA = {
    "tournament": "ESL Pro League",
    "date": "2026-03-20",
    "format": "bo3",
    "bo_count": 3,
    "tier": 1,
    "team_a": {
        "name": "Natus Vincere",
        "hltv_ranking": 1,
        "win_rate_3m": 0.65,
        "win_rate_6m": 0.60,
        "lan_record": "10-4",
        "online_record": "8-3",
        "days_since_roster_change": 30,
        "roster": ["s1mple", "electronic", "b1t", "Perfecto", "npl"],
        "coach": "B1ad3",
        "map_pool": {
            "mirage": {"win_rate": 0.70, "games": 20},
            "inferno": {"win_rate": 0.60, "games": 15},
        },
        "recent_form": [
            {"date": "2026-03-15", "opponent": "Team Vitality", "score": "2-1", "tournament": "IEM"},
        ],
    },
    "team_b": {
        "name": "Team Vitality",
        "hltv_ranking": 3,
        "win_rate_3m": 0.58,
        "win_rate_6m": 0.55,
        "lan_record": "8-5",
        "online_record": "7-4",
        "days_since_roster_change": 60,
        "roster": ["ZywOo", "apEX", "Magisk", "dupreeh", "Spinx"],
        "coach": "shox",
        "map_pool": {
            "mirage": {"win_rate": 0.55, "games": 18},
            "nuke": {"win_rate": 0.65, "games": 14},
        },
        "recent_form": [
            {"date": "2026-03-14", "opponent": "FaZe Clan", "score": "2-0", "tournament": "IEM"},
        ],
    },
    "odds": {
        "moneyline": {"team_a": -150, "team_b": 120},
        "map_handicap": {
            "team_a_line": -1.5,
            "team_a_odds": 180,
            "team_b_line": 1.5,
            "team_b_odds": -220,
        },
        "total_maps": {"line": 2.5, "over_odds": -130, "under_odds": 105},
        "implied_probs": {"ml_team_a": 0.60, "ml_team_b": 0.40},
    },
    "head_to_head": {"team_a_wins": 5, "team_b_wins": 3},
    "patch": {
        "patch_version": "1.38.1",
        "days_since_patch": 14,
        "impact_rating": "moderate",
        "key_changes": ["AK-47 recoil tweak", "Mirage CT adjustments"],
    },
    "context": {
        "stage": "Group Stage",
        "stakes": "high",
        "online_lan": "lan",
    },
}


def test_build_briefing_dispatches_to_cs2():
    """build_briefing with game_key='cs2' returns a valid CS2 briefing string."""
    result = build_briefing(CS2_MATCH_DATA, game_key="cs2")
    assert isinstance(result, str)
    assert len(result) > 100
    assert "Natus Vincere" in result
    assert "Team Vitality" in result
    assert "CS2" in result


def test_build_briefing_cs2_contains_key_sections():
    """CS2 briefing includes all required analysis sections."""
    result = build_briefing(CS2_MATCH_DATA, game_key="cs2")
    assert "BETTING LINES" in result
    assert "TEAM PROFILES" in result
    assert "MAP VETO ANALYSIS" in result
    assert "PREDICTION TASK" in result


def test_build_briefing_unknown_game_raises():
    """build_briefing raises KeyError for an unregistered game key."""
    with pytest.raises(KeyError):
        build_briefing(CS2_MATCH_DATA, game_key="unknown_game_xyz")


def test_build_briefing_dispatches_to_correct_module():
    """build_briefing calls the game module's briefing.build_briefing."""
    mock_game = MagicMock()
    mock_game.briefing.build_briefing.return_value = "MOCK_BRIEFING"

    with patch("briefing.get_game", return_value=mock_game) as mock_get_game:
        result = build_briefing({"some": "data"}, game_key="cs2")

    mock_get_game.assert_called_once_with("cs2")
    mock_game.briefing.build_briefing.assert_called_once_with({"some": "data"})
    assert result == "MOCK_BRIEFING"
