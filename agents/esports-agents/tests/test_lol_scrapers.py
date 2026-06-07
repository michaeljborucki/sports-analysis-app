"""Tests for LoL scraper functions — required field shapes and module importability."""
import pytest
from games.lol.scrapers import (
    fetch_team_profile,
    fetch_upcoming_matches,
    fetch_head_to_head,
    fetch_match_result,
)


TEAM_PROFILE_REQUIRED_KEYS = [
    "name",
    "region",
    "league_standing",
    "win_rate",
    "blue_side_wr",
    "red_side_wr",
    "avg_game_duration",
    "first_blood_rate",
    "first_tower_rate",
    "first_dragon_rate",
    "gold_diff_15",
    "roster",
    "coach",
    "days_since_roster_change",
    "recent_form",
]

HEAD_TO_HEAD_REQUIRED_KEYS = [
    "total_matches",
    "team_a_wins",
    "team_b_wins",
    "recent_5",
]

MATCH_RESULT_REQUIRED_KEYS = [
    "winner",
    "score",
    "maps_played",
    "game_details",
]


def test_scrapers_module_importable():
    """Verify the scrapers module can be imported and exposes the expected API."""
    from games.lol import scrapers
    assert hasattr(scrapers, "fetch_team_profile")
    assert hasattr(scrapers, "fetch_upcoming_matches")
    assert hasattr(scrapers, "fetch_head_to_head")
    assert hasattr(scrapers, "fetch_match_result")


def test_fetch_team_profile_returns_required_fields():
    """fetch_team_profile must return a dict with all required keys."""
    profile = fetch_team_profile("T1", "LCK")
    assert isinstance(profile, dict), "Expected dict return type"
    for key in TEAM_PROFILE_REQUIRED_KEYS:
        assert key in profile, f"Missing key in team profile: {key}"


def test_fetch_team_profile_name_preserved():
    """The team name should be preserved in the returned profile."""
    profile = fetch_team_profile("Cloud9", "LCS")
    assert profile["name"] == "Cloud9"


def test_fetch_team_profile_region_preserved():
    """The region should be preserved when provided."""
    profile = fetch_team_profile("G2 Esports", "LEC")
    assert profile["region"] == "LEC"


def test_fetch_team_profile_numeric_fields():
    """Numeric stat fields should be floats (not None or string)."""
    profile = fetch_team_profile("Fnatic", "LEC")
    numeric_fields = [
        "win_rate", "blue_side_wr", "red_side_wr",
        "avg_game_duration", "first_blood_rate",
        "first_tower_rate", "first_dragon_rate", "gold_diff_15",
    ]
    for field in numeric_fields:
        assert isinstance(profile[field], (int, float)), (
            f"Field '{field}' should be numeric, got {type(profile[field])}"
        )


def test_fetch_team_profile_list_fields():
    """List fields should be lists (possibly empty)."""
    profile = fetch_team_profile("Team Liquid", "LCS")
    assert isinstance(profile["roster"], list)
    assert isinstance(profile["recent_form"], list)


def test_fetch_upcoming_matches_returns_list():
    """fetch_upcoming_matches must return a list."""
    matches = fetch_upcoming_matches()
    assert isinstance(matches, list)


def test_fetch_upcoming_matches_items_have_required_keys():
    """Each item in upcoming matches must have the standard match keys."""
    matches = fetch_upcoming_matches()
    required = ["team_a", "team_b", "tournament", "format", "date"]
    for match in matches:
        for key in required:
            assert key in match, f"Upcoming match missing key: {key}"


def test_fetch_head_to_head_returns_required_fields():
    """fetch_head_to_head must return a dict with all required keys."""
    h2h = fetch_head_to_head("T1", "Gen.G")
    assert isinstance(h2h, dict)
    for key in HEAD_TO_HEAD_REQUIRED_KEYS:
        assert key in h2h, f"H2H missing key: {key}"


def test_fetch_head_to_head_numeric_counts():
    """Win counts must be non-negative integers."""
    h2h = fetch_head_to_head("T1", "Gen.G")
    assert isinstance(h2h["total_matches"], int)
    assert isinstance(h2h["team_a_wins"], int)
    assert isinstance(h2h["team_b_wins"], int)
    assert h2h["total_matches"] >= 0
    assert h2h["team_a_wins"] >= 0
    assert h2h["team_b_wins"] >= 0


def test_fetch_head_to_head_recent5_is_list():
    """recent_5 field must be a list."""
    h2h = fetch_head_to_head("T1", "Gen.G")
    assert isinstance(h2h["recent_5"], list)


def test_fetch_match_result_returns_required_fields():
    """fetch_match_result must return a dict with all required keys."""
    result = fetch_match_result("T1", "Gen.G", "2026-03-20")
    assert isinstance(result, dict)
    for key in MATCH_RESULT_REQUIRED_KEYS:
        assert key in result, f"Match result missing key: {key}"


def test_fetch_match_result_maps_played_is_int():
    """maps_played must be an integer."""
    result = fetch_match_result("T1", "Gen.G", "2026-03-20")
    assert isinstance(result["maps_played"], int)


def test_fetch_match_result_game_details_is_list():
    """game_details must be a list."""
    result = fetch_match_result("T1", "Gen.G", "2026-03-20")
    assert isinstance(result["game_details"], list)


def test_mock_team_profile_structure():
    """Directly test the required shape using a hand-built mock (no network needed)."""
    mock_profile = {
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
    }
    for key in TEAM_PROFILE_REQUIRED_KEYS:
        assert key in mock_profile, f"Mock profile missing key: {key}"
    assert mock_profile["win_rate"] == 0.82
    assert mock_profile["gold_diff_15"] == 850.0
    assert len(mock_profile["recent_form"]) == 2


def test_mock_match_result_structure():
    """Test the required shape of a match result using a hand-built mock."""
    mock_result = {
        "winner": "T1",
        "score": "2-1",
        "maps_played": 3,
        "game_details": [
            {"gameid": "LCKSP1-G1", "winner": "T1"},
            {"gameid": "LCKSP1-G2", "winner": "Gen.G"},
            {"gameid": "LCKSP1-G3", "winner": "T1"},
        ],
    }
    assert mock_result["maps_played"] == 3
    assert mock_result["winner"] == "T1"
    assert len(mock_result["game_details"]) == 3
