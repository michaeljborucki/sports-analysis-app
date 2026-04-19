from pathlib import Path

from server.picks.bet_card_parser import parse_bet_card


FIXTURE = Path(__file__).parent / "fixtures" / "bet_card_example.txt"


def test_parse_bet_card_returns_date():
    card = parse_bet_card(FIXTURE.read_text())
    assert card["date"] == "2026-04-01"


def test_parse_bet_card_returns_games():
    card = parse_bet_card(FIXTURE.read_text())
    assert len(card["games"]) >= 1
    assert card["games"][0]["game_label"] == "WSH@PHI"


def test_parse_bet_card_pick_fields():
    card = parse_bet_card(FIXTURE.read_text())
    first_game = card["games"][0]
    first_pick = first_game["picks"][0]
    assert first_pick["bet_type"] == "first_5_rl"
    assert first_pick["side"] == "home -1.5"
    assert first_pick["odds_american"] == 116
    assert abs(first_pick["market_prob"] - 0.439) < 0.005
    assert abs(first_pick["model_prob"] - 0.565) < 0.005
    assert abs(first_pick["edge"] - 0.126) < 0.005
    assert abs(first_pick["kelly_pct"] - 0.0474) < 0.001
