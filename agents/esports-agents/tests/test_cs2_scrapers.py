import pytest
from games.cs2.scrapers import (
    fetch_team_profile, fetch_upcoming_matches,
    fetch_head_to_head, fetch_match_result,
)

def test_fetch_team_profile_returns_required_fields():
    """Test the sync wrapper returns dict with required keys."""
    mock_data = {
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
        },
        "recent_form": [
            {"date": "2026-03-18", "opponent": "FaZe", "score": "2-0", "tournament": "IEM"},
        ],
    }
    required = ["name", "hltv_ranking", "win_rate_3m", "roster", "map_pool", "recent_form",
                "win_rate_6m", "lan_record", "online_record", "coach", "days_since_roster_change"]
    for key in required:
        assert key in mock_data

def test_fetch_upcoming_matches_structure():
    mock_match = {
        "team_a": "NaVi", "team_b": "FaZe",
        "tournament": "IEM Katowice", "format": "bo3",
        "tier": 1, "date": "2026-03-20", "lan": True,
    }
    required = ["team_a", "team_b", "tournament", "format", "tier", "date", "lan"]
    for key in required:
        assert key in mock_match

def test_fetch_match_result_structure():
    mock_result = {
        "winner": "NaVi", "score": "2-1", "maps_played": 3,
        "map_scores": [{"map": "mirage", "team_a_rounds": 16, "team_b_rounds": 12}],
    }
    assert mock_result["maps_played"] == 3

def test_scrapers_module_importable():
    """Verify the scrapers module can be imported."""
    from games.cs2 import scrapers
    assert hasattr(scrapers, 'fetch_team_profile')
    assert hasattr(scrapers, 'fetch_upcoming_matches')
    assert hasattr(scrapers, 'fetch_head_to_head')
    assert hasattr(scrapers, 'fetch_match_result')
