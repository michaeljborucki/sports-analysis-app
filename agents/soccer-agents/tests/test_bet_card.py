from datetime import datetime, timezone
from unittest.mock import patch
import pandas as pd
from agents.bet_card import format_bet_card


@patch("agents.bet_card.load_bets")
def test_format_empty_card(mock_load):
    mock_load.return_value = pd.DataFrame(columns=[
        "date", "game", "bet_type", "side", "odds", "sim_prob",
        "edge", "kelly_pct", "result", "profit",
    ])
    card = format_bet_card("2026-04-01")
    assert "No picks" in card


@patch("agents.bet_card.load_bets")
def test_format_card_with_bets(mock_load):
    mock_load.return_value = pd.DataFrame([{
        "date": "2026-04-01", "game": "LA Galaxy@Inter Miami CF", "bet_type": "asian_handicap",
        "side": "home -0.5", "odds": -110, "sim_prob": 0.58, "edge": 0.055,
        "kelly_pct": 0.02, "result": "", "profit": "",
    }])
    card = format_bet_card("2026-04-01")
    assert "LA Galaxy@Inter Miami CF" in card
    assert "asian_handicap" in card


@patch("agents.bet_card._kickoffs_by_game")
@patch("agents.bet_card.load_bets")
def test_upcoming_filters_started_games(mock_load, mock_kickoffs):
    mock_load.return_value = pd.DataFrame([
        {"date": "2026-04-01", "game": "Started@A", "league": "MLS",
         "bet_type": "asian_handicap", "side": "home -0.5", "odds": -110,
         "sim_prob": 0.58, "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": ""},
        {"date": "2026-04-01", "game": "Upcoming@B", "league": "MLS",
         "bet_type": "total", "side": "over 2.5", "odds": -110,
         "sim_prob": 0.58, "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": ""},
    ])
    mock_kickoffs.return_value = {
        "Started@A": datetime(2026, 4, 1, 18, 0, tzinfo=timezone.utc),
        "Upcoming@B": datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc),
    }
    card = format_bet_card("2026-04-01", upcoming_only=True)
    assert "Upcoming@B" in card
    assert "Started@A" not in card


@patch("agents.bet_card._kickoffs_by_game")
@patch("agents.bet_card.load_bets")
def test_upcoming_keeps_unknown_kickoffs(mock_load, mock_kickoffs):
    mock_load.return_value = pd.DataFrame([{
        "date": "2026-04-01", "game": "Missing@X", "league": "MLS",
        "bet_type": "btts", "side": "yes", "odds": -110, "sim_prob": 0.6,
        "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": "",
    }])
    mock_kickoffs.return_value = {}
    card = format_bet_card("2026-04-01", upcoming_only=True)
    assert "Missing@X" in card
