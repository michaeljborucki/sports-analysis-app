"""Tests for LoL briefing template and system prompt."""
import pytest
from games.lol.briefing import build_briefing
from games.lol.prompt import LOL_SYSTEM_PROMPT, SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_match_data(bo_count: int = 3) -> dict:
    """Return a fully populated LoL match data dict for testing."""
    return {
        "tournament": "LCK Spring 2026",
        "date": "2026-03-20",
        "format": f"bo{bo_count}",
        "bo_count": bo_count,
        "tier": 1,
        "team_a": {
            "name": "T1",
            "region": "LCK",
            "league_standing": "1st",
            "win_rate": 0.82,
            "blue_side_wr": 0.85,
            "red_side_wr": 0.78,
            "avg_game_duration": 31.5,
            "first_blood_rate": 0.55,
            "first_tower_rate": 0.60,
            "first_dragon_rate": 0.62,
            "gold_diff_15": 850.0,
            "roster": ["Faker", "Gumayusi", "Keria", "Zeus", "Oner"],
            "coach": "Polt",
            "days_since_roster_change": 180,
            "recent_form": [
                {"date": "2026-03-19", "opponent": "Gen.G", "result": "W", "tournament": "LCK"},
                {"date": "2026-03-17", "opponent": "DRX", "result": "W", "tournament": "LCK"},
            ],
        },
        "team_b": {
            "name": "Gen.G",
            "region": "LCK",
            "league_standing": "2nd",
            "win_rate": 0.76,
            "blue_side_wr": 0.80,
            "red_side_wr": 0.72,
            "avg_game_duration": 33.0,
            "first_blood_rate": 0.50,
            "first_tower_rate": 0.55,
            "first_dragon_rate": 0.58,
            "gold_diff_15": 400.0,
            "roster": ["Chovy", "Peyz", "Lehends", "Doran", "Canyon"],
            "coach": "Kkoma",
            "days_since_roster_change": 90,
            "recent_form": [
                {"date": "2026-03-18", "opponent": "T1", "result": "L", "tournament": "LCK"},
                {"date": "2026-03-16", "opponent": "KT", "result": "W", "tournament": "LCK"},
            ],
        },
        "odds": {
            "moneyline": {"team_a": -175, "team_b": 145},
            "map_handicap": {
                "team_a_line": -1.5,
                "team_a_odds": 150,
                "team_b_line": 1.5,
                "team_b_odds": -180,
            },
            "total_maps": {"line": 2.5, "over_odds": -130, "under_odds": 110},
            "implied_probs": {"ml_team_a": 0.636, "ml_team_b": 0.364},
        },
        "head_to_head": {"total_matches": 10, "team_a_wins": 6, "team_b_wins": 4, "recent_5": []},
        "patch": {
            "patch_version": "14.6",
            "days_since_patch": 5,
            "key_changes": ["Azir nerfed", "Rek'Sai buffed"],
            "impact_rating": "moderate",
        },
        "context": {"stage": "playoff", "stakes": "semifinals"},
    }


# ---------------------------------------------------------------------------
# Briefing content tests
# ---------------------------------------------------------------------------

def test_briefing_contains_team_names():
    result = build_briefing(_make_mock_match_data())
    assert "T1" in result
    assert "Gen.G" in result


def test_briefing_contains_tournament():
    result = build_briefing(_make_mock_match_data())
    assert "LCK Spring 2026" in result


def test_briefing_contains_betting_lines():
    result = build_briefing(_make_mock_match_data())
    assert "BETTING LINES" in result
    assert "Moneyline" in result


def test_briefing_contains_game_handicap():
    result = build_briefing(_make_mock_match_data())
    assert "Game Handicap" in result or "GAME HANDICAP" in result or "Handicap" in result


def test_briefing_contains_total_games():
    result = build_briefing(_make_mock_match_data())
    assert "Total Games" in result or "TOTAL GAMES" in result


def test_briefing_contains_lol_specific_sections():
    """Briefing must contain LoL-specific stats sections."""
    result = build_briefing(_make_mock_match_data())
    assert "Blue Side WR" in result or "blue_side" in result.lower()
    assert "Red Side WR" in result or "red_side" in result.lower()
    assert "Gold Diff" in result or "GD@15" in result or "gold_diff" in result.lower()


def test_briefing_contains_first_objectives():
    """Briefing must contain first objective rates."""
    result = build_briefing(_make_mock_match_data())
    assert "First Blood" in result
    assert "First Tower" in result or "First Dragon" in result


def test_briefing_contains_performance_metrics():
    """Briefing must contain a performance metrics section."""
    result = build_briefing(_make_mock_match_data())
    assert "Performance Metrics" in result or "Win Rate" in result


def test_briefing_contains_recent_form():
    result = build_briefing(_make_mock_match_data())
    assert "Recent Form" in result or "recent_form" in result.lower()


def test_briefing_contains_roster():
    result = build_briefing(_make_mock_match_data())
    assert "Faker" in result
    assert "Chovy" in result


def test_briefing_contains_patch_context():
    result = build_briefing(_make_mock_match_data())
    assert "14.6" in result
    assert "Patch" in result or "patch" in result


def test_briefing_contains_head_to_head():
    result = build_briefing(_make_mock_match_data())
    assert "Head-to-Head" in result or "H2H" in result


def test_briefing_contains_prediction_task():
    result = build_briefing(_make_mock_match_data())
    assert "PREDICTION TASK" in result
    assert "MATCH WINNER" in result


def test_briefing_contains_region():
    result = build_briefing(_make_mock_match_data())
    assert "LCK" in result


def test_briefing_returns_string():
    result = build_briefing(_make_mock_match_data())
    assert isinstance(result, str)
    assert len(result) > 100


def test_briefing_with_empty_match_data():
    """build_briefing must not raise on empty/missing data."""
    result = build_briefing({})
    assert isinstance(result, str)
    assert len(result) > 0


def test_briefing_with_missing_odds():
    data = _make_mock_match_data()
    data["odds"] = {}
    result = build_briefing(data)
    assert isinstance(result, str)
    assert "T1" in result


def test_briefing_with_missing_roster():
    data = _make_mock_match_data()
    data["team_a"]["roster"] = []
    result = build_briefing(data)
    assert "Roster data unavailable" in result


def test_briefing_bo5_format():
    result = build_briefing(_make_mock_match_data(bo_count=5))
    assert "BO5" in result or "bo5" in result.lower()


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------

def test_system_prompt_alias_matches():
    """SYSTEM_PROMPT must be the same object as LOL_SYSTEM_PROMPT."""
    assert SYSTEM_PROMPT is LOL_SYSTEM_PROMPT


def test_system_prompt_has_six_analysts():
    assert "LANING ANALYST" in LOL_SYSTEM_PROMPT
    assert "MACRO ANALYST" in LOL_SYSTEM_PROMPT
    assert "DRAFT ANALYST" in LOL_SYSTEM_PROMPT
    assert "FORM" in LOL_SYSTEM_PROMPT
    assert "MARKET ANALYST" in LOL_SYSTEM_PROMPT
    assert "CONTRARIAN" in LOL_SYSTEM_PROMPT


def test_system_prompt_requests_json():
    assert "JSON" in LOL_SYSTEM_PROMPT
    assert "team_a_win_prob" in LOL_SYSTEM_PROMPT
    assert "map_handicap" in LOL_SYSTEM_PROMPT
    assert "total_maps" in LOL_SYSTEM_PROMPT


def test_system_prompt_mentions_lol_concepts():
    """Prompt must mention LoL-specific concepts, not CS2 concepts."""
    assert "dragon" in LOL_SYSTEM_PROMPT.lower() or "baron" in LOL_SYSTEM_PROMPT.lower()
    assert "draft" in LOL_SYSTEM_PROMPT.lower() or "champion" in LOL_SYSTEM_PROMPT.lower()
    # Should NOT contain CS2-specific terms
    assert "HLTV" not in LOL_SYSTEM_PROMPT
    assert "AWP" not in LOL_SYSTEM_PROMPT


def test_system_prompt_explains_maps_terminology():
    """Prompt should clarify that 'maps' = individual games on Summoner's Rift."""
    assert "Summoner" in LOL_SYSTEM_PROMPT or "maps" in LOL_SYSTEM_PROMPT


def test_system_prompt_no_markdown():
    """Prompt must explicitly forbid markdown in responses."""
    assert "No markdown" in LOL_SYSTEM_PROMPT or "no markdown" in LOL_SYSTEM_PROMPT.lower()
