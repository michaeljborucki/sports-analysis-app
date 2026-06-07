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
        "date": "2026-04-01", "game": "Navi vs FaZe", "game_title": "cs2",
        "bet_type": "moneyline", "side": "team_a", "odds": -150,
        "sim_prob": 0.62, "edge": 0.055, "kelly_pct": 0.02,
        "result": "", "profit": "",
    }])
    card = format_bet_card("2026-04-01")
    assert "Navi vs FaZe" in card
    assert "CS2" in card
    assert "Match Winner" in card


@patch("agents.bet_card.load_bets")
def test_format_card_map_handicap(mock_load):
    mock_load.return_value = pd.DataFrame([{
        "date": "2026-04-01", "game": "T1 vs Gen.G", "game_title": "lol",
        "bet_type": "map_handicap", "side": "favorite", "odds": -120,
        "sim_prob": 0.58, "edge": 0.04, "kelly_pct": 0.015,
        "result": "", "profit": "",
    }])
    card = format_bet_card("2026-04-01")
    assert "T1 vs Gen.G" in card
    assert "LOL" in card
    assert "Map Handicap" in card
