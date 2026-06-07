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
        "date": "2026-04-01", "game": "Makhachev vs Oliveira",
        "bet_type": "moneyline", "side": "fighter_a", "odds": -200,
        "sim_prob": 0.72, "edge": 0.07, "kelly_pct": 0.03,
        "result": "", "profit": "",
    }])
    card = format_bet_card("2026-04-01")
    assert "Makhachev vs Oliveira" in card
    assert "moneyline" in card
