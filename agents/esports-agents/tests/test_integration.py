"""End-to-end integration test for the esports pipeline."""
from unittest.mock import patch, MagicMock
import json


def test_daily_pipeline_runs_without_error():
    """Verify the pipeline completes without exceptions when APIs are mocked."""
    from agents.daily_runner import run_pipeline
    from scrapers.odds import OddsData

    # Mock schedule
    mock_matches = [
        {"team_a": "NaVi", "team_b": "FaZe", "tournament": "IEM",
         "format": "bo3", "tier": 1, "date": "2026-03-20", "lan": True},
    ]

    # Mock odds
    mock_odds = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": -175, "team_b": 145},
        map_handicap={"team_a_line": -1.5, "team_a_odds": 150,
                      "team_b_line": 1.5, "team_b_odds": -180},
        total_maps={"line": 2.5, "over_odds": -130, "under_odds": 110},
    )
    mock_odds.compute_implied_probs()

    with patch("games.cs2.scrapers.fetch_upcoming_matches", return_value=mock_matches), \
         patch("agents.daily_runner.get_esports_odds", return_value=[mock_odds]), \
         patch("agents.daily_runner.fetch_patch_context", return_value={
             "patch_version": "1.39", "days_since_patch": 5,
             "key_changes": [], "impact_rating": "minor", "raw_url": "",
         }), \
         patch("agents.daily_runner.run_plan_b", return_value=None), \
         patch("agents.daily_runner.log_bet"):

        # Should not raise
        run_pipeline(date="2026-03-20", game_keys=["cs2"])


def test_odds_data_round_trip():
    """Verify OddsData can be serialized and used with edge detection."""
    from scrapers.odds import OddsData
    from edge import analyze_all_edges
    from games.cs2 import config as cs2_config

    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": -175, "team_b": 145},
        map_handicap={"team_a_line": -1.5, "team_a_odds": 150,
                      "team_b_line": 1.5, "team_b_odds": -180},
        total_maps={"line": 2.5, "over_odds": -130, "under_odds": 110},
    )
    od.compute_implied_probs()

    # Simulate ensemble output
    sim = {
        "moneyline": {"team_a_win_prob": 0.75, "team_b_win_prob": 0.25, "confidence": "high"},
        "map_handicap": {"favorite_cover_prob": 0.55, "confidence": "medium"},
        "total_maps": {"over_prob": 0.60, "under_prob": 0.40, "confidence": "medium"},
    }

    bets = analyze_all_edges(sim, od, format="bo3", game_config=cs2_config)
    assert isinstance(bets, list)
    # With 75% prob vs ~63% implied, should find moneyline edge
    ml_bets = [b for b in bets if b["bet_type"] == "moneyline"]
    assert len(ml_bets) == 1
    assert ml_bets[0]["side"] == "team_a"


def test_game_registry_complete():
    """Verify both games have all required interface components."""
    from games import get_game

    for game_key in ["cs2", "lol"]:
        game = get_game(game_key)
        # Config
        assert hasattr(game.config, "BET_SLOTS")
        assert hasattr(game.config, "EDGE_THRESHOLDS")
        assert hasattr(game.config, "PROB_FIELDS")
        # Scrapers
        assert hasattr(game.scrapers, "fetch_upcoming_matches")
        assert hasattr(game.scrapers, "fetch_team_profile")
        # Briefing
        assert hasattr(game.briefing, "build_briefing")
        # Prompt
        assert hasattr(game.prompt, "SYSTEM_PROMPT")
        assert "JSON" in game.prompt.SYSTEM_PROMPT
