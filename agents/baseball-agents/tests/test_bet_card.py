from unittest.mock import patch
import json
import pandas as pd
from agents.bet_card import format_bet_card, format_mainline_bet_card, _mainline_bet_card_dict


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
        "date": "2026-04-01", "game": "BOS@NYY", "bet_type": "moneyline",
        "side": "home", "odds": -150, "sim_prob": 0.62, "edge": 0.055,
        "kelly_pct": 0.02, "result": "", "profit": "",
    }])
    card = format_bet_card("2026-04-01")
    assert "BOS@NYY" in card
    assert "moneyline" in card


@patch("agents.bet_card.load_bets")
def test_format_card_handles_degenerate_sim_prob(mock_load):
    """sim_prob at the (0,1) boundary must not crash the whole card.

    The MC prop simulator can produce sim_prob=1.0 when every sampled
    scenario clears the line (e.g. pitcher_outs over a low line). The
    upstream fix is Laplace smoothing in the simulator, but the card
    renderer must never let one bad row wipe out every other pick.
    """
    mock_load.return_value = pd.DataFrame([
        {
            "date": "2026-04-16", "game": "BOS@NYY", "bet_type": "moneyline",
            "side": "home", "odds": -150, "sim_prob": 0.62, "edge": 0.055,
            "kelly_pct": 0.02, "market_prob": 0.60, "result": "", "profit": "",
        },
        {
            "date": "2026-04-16", "game": "TOR@MIL", "bet_type": "pitcher_outs",
            "side": "Brandon Sproat over 14.5", "odds": -110, "sim_prob": 1.0,
            "edge": 0.43, "kelly_pct": 0.10, "market_prob": 0.52,
            "result": "", "profit": "",
        },
    ])
    card = format_bet_card("2026-04-16")
    assert "BOS@NYY" in card, "earlier rows must still render"
    assert "TOR@MIL" in card, "degenerate row must still appear"
    assert "Brandon Sproat" in card


@patch("agents.bet_card.load_bets")
def test_mainline_card_shows_game_time(mock_load):
    """Mainline text card must include '— <time> ET' next to each game header."""
    mock_load.return_value = pd.DataFrame([{
        "date": "2026-04-23", "game": "SD@COL", "game_time": "2026-04-23T23:40:00Z",
        "bet_type": "moneyline", "side": "home", "odds": -150, "sim_prob": 0.62,
        "edge": 0.055, "kelly_pct": 0.02, "market_prob": 0.60,
        "result": "", "profit": "",
    }])
    card = format_mainline_bet_card("2026-04-23")
    assert "SD@COL" in card
    assert "7:40 PM ET" in card


@patch("agents.bet_card.load_bets")
def test_mainline_card_omits_time_when_missing(mock_load):
    """Old rows without game_time render the plain game header."""
    mock_load.return_value = pd.DataFrame([{
        "date": "2026-04-23", "game": "SD@COL",
        "bet_type": "moneyline", "side": "home", "odds": -150, "sim_prob": 0.62,
        "edge": 0.055, "kelly_pct": 0.02, "market_prob": 0.60,
        "result": "", "profit": "",
    }])
    card = format_mainline_bet_card("2026-04-23")
    assert "SD@COL" in card
    # Game header should be plain "SD@COL", not "SD@COL — <time>"
    assert "SD@COL —" not in card


@patch("agents.bet_card.load_bets")
def test_mainline_json_includes_game_time_et(mock_load):
    """JSON bet card must include game_time_et per game."""
    mock_load.return_value = pd.DataFrame([{
        "date": "2026-04-23", "game": "SD@COL", "game_time": "2026-04-23T23:40:00Z",
        "bet_type": "moneyline", "side": "home", "odds": -150, "sim_prob": 0.62,
        "edge": 0.055, "kelly_pct": 0.02, "market_prob": 0.60,
        "result": "", "profit": "",
    }])
    data = _mainline_bet_card_dict("2026-04-23")
    assert data["games"][0]["game_time_et"] == "7:40 PM ET"
    # Round-trips as valid JSON
    assert json.loads(json.dumps(data))["games"][0]["game_time_et"] == "7:40 PM ET"
