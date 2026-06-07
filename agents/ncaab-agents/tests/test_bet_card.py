from unittest.mock import patch
import pandas as pd
from agents.bet_card import format_bet_card


@patch("agents.bet_card.load_predictions")
@patch("agents.bet_card.load_bets")
def test_format_empty_card(mock_load_bets, mock_load_preds):
    empty_bets = pd.DataFrame(columns=[
        "date", "game", "bet_type", "side", "odds", "sim_prob",
        "edge", "kelly_pct", "result", "profit",
    ])
    empty_preds = pd.DataFrame(columns=[
        "date", "game", "game_time", "bet_type", "side", "odds",
        "sim_prob", "market_prob", "edge", "kelly_pct", "predicted_score",
        "has_edge",
    ])
    mock_load_bets.return_value = empty_bets
    mock_load_preds.return_value = empty_preds
    card = format_bet_card("2026-04-01")
    assert "No analysis" in card


@patch("agents.bet_card.load_predictions")
@patch("agents.bet_card.load_bets")
def test_format_card_with_predictions(mock_load_bets, mock_load_preds):
    mock_load_preds.return_value = pd.DataFrame([{
        "date": "2026-04-01", "game": "UK@ISU", "game_time": "2026-04-01T16:10Z",
        "bet_type": "moneyline", "side": "home", "odds": -450,
        "sim_prob": 0.782, "market_prob": 0.818, "edge": -0.036,
        "kelly_pct": 0.0, "predicted_score": "62-71", "has_edge": False,
    }, {
        "date": "2026-04-01", "game": "UK@ISU", "game_time": "2026-04-01T16:10Z",
        "bet_type": "total", "side": "under 137.5", "odds": -112,
        "sim_prob": 0.583, "market_prob": 0.528, "edge": 0.055,
        "kelly_pct": 0.0196, "predicted_score": "62-71", "has_edge": True,
    }])
    mock_load_bets.return_value = pd.DataFrame(columns=[
        "date", "game", "bet_type", "side", "odds", "sim_prob",
        "edge", "kelly_pct", "result", "profit",
    ])
    card = format_bet_card("2026-04-01")
    assert "UK@ISU" in card
    assert "moneyline" in card
    assert "total" in card
    assert "2 games analyzed" not in card  # only 1 game
    assert "1 games analyzed" in card or "1 recommended" in card


@patch("agents.bet_card.load_predictions")
@patch("agents.bet_card.load_bets")
def test_format_card_bets_only_fallback(mock_load_bets, mock_load_preds):
    """When predictions CSV is empty, falls back to bets-only view."""
    mock_load_preds.return_value = pd.DataFrame(columns=[
        "date", "game", "game_time", "bet_type", "side", "odds",
        "sim_prob", "market_prob", "edge", "kelly_pct", "predicted_score",
        "has_edge",
    ])
    mock_load_bets.return_value = pd.DataFrame([{
        "date": "2026-04-01", "game": "BOS@NYY", "bet_type": "moneyline",
        "side": "home", "odds": -150, "sim_prob": 0.62, "edge": 0.055,
        "kelly_pct": 0.02, "result": "", "profit": "",
    }])
    card = format_bet_card("2026-04-01")
    assert "BOS@NYY" in card
    assert "moneyline" in card
