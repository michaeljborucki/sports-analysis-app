"""Regression tests pinning bet-card text and JSON payload formats.

The text card ships to Discord. The JSON payload is consumed by downstream
tooling (and the framework calls this a per-day artifact). Format drift either
breaks Discord layouts or shifts downstream parsers — both are silent failures.

If one of these fails, read the diff, then either update the golden fixture
(intentional change) or fix the code (unintentional regression).
"""
import json
import os

import pandas as pd

from agents.bet_card import _render_card, _build_payload


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
GOLDEN_TEXT_PATH = os.path.join(FIXTURES_DIR, "golden_bet_card.txt")
GOLDEN_JSON_PATH = os.path.join(FIXTURES_DIR, "golden_bet_card_payload.json")


def _canonical_bets_df() -> pd.DataFrame:
    """Two matches, three bets: one W, one pending, one L.

    Exercises: player name resolution in ``side``, mixed settled/pending rows,
    handicap line preservation, and record-line aggregation.
    """
    return pd.DataFrame([
        {"date": "2026-04-20", "start_time": "2026-04-20T14:00:00Z",
         "game": "Carlos Alcaraz vs Jannik Sinner", "bet_type": "moneyline",
         "side": "player_a", "odds": -130, "sim_prob": 0.62, "sim_prob_raw": 0.62,
         "market_prob": 0.565, "edge": 0.055, "kelly_pct": 0.0096,
         "result": "W", "profit": 1.0},
        {"date": "2026-04-20", "start_time": "2026-04-20T14:00:00Z",
         "game": "Carlos Alcaraz vs Jannik Sinner", "bet_type": "total_games",
         "side": "over 22.5", "odds": -110, "sim_prob": 0.60, "sim_prob_raw": 0.60,
         "market_prob": 0.50, "edge": 0.10, "kelly_pct": 0.015,
         "result": "", "profit": ""},
        {"date": "2026-04-20", "start_time": "",
         "game": "Iga Swiatek vs Coco Gauff", "bet_type": "game_handicap",
         "side": "player_b 2.5", "odds": -110, "sim_prob": 0.55, "sim_prob_raw": 0.55,
         "market_prob": 0.50, "edge": 0.05, "kelly_pct": 0.007,
         "result": "L", "profit": -1.1},
    ])


def test_bet_card_text_matches_golden():
    actual = _render_card(_canonical_bets_df(), "2026-04-20")
    with open(GOLDEN_TEXT_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "bet-card text drift — review diff and update "
        "tests/fixtures/golden_bet_card.txt only if intentional."
    )


def test_bet_card_empty_day_text():
    """Empty-day text is a separate code path and also ships to Discord."""
    empty_df = pd.DataFrame(columns=[
        "date", "game", "bet_type", "side", "odds",
        "edge", "kelly_pct", "result", "profit",
    ])
    out = _render_card(empty_df, "2026-04-20")
    assert out == (
        "\n=== MiroFish Tennis Bet Card — 2026-04-20 ===\n\n"
        "No picks for this window.\n"
    )


def test_bet_card_json_payload_matches_golden():
    """JSON payload structure is a downstream contract — pin it.
    ``generated_at`` is a wall-clock timestamp so we strip it before comparing.
    """
    payload = _build_payload(_canonical_bets_df(), "2026-04-20")
    payload.pop("generated_at")

    with open(GOLDEN_JSON_PATH) as f:
        expected = json.load(f)
    expected.pop("generated_at", None)

    assert payload == expected, (
        "bet-card JSON payload drift — review diff and update "
        "tests/fixtures/golden_bet_card_payload.json only if intentional."
    )


def test_bet_card_json_resolves_player_names_in_side():
    """Side tokens 'player_a' / 'player_b' must be replaced with actual names."""
    payload = _build_payload(_canonical_bets_df(), "2026-04-20")
    picks = payload["picks"]
    # First pick is moneyline player_a on Alcaraz vs Sinner → "Carlos Alcaraz"
    assert picks[0]["side"] == "Carlos Alcaraz"
    assert picks[0]["side_raw"] == "player_a"
    # Third pick is game_handicap player_b 2.5 on Swiatek vs Gauff → "Coco Gauff 2.5"
    assert picks[2]["side"] == "Coco Gauff 2.5"
    assert picks[2]["side_raw"] == "player_b 2.5"


def test_bet_card_json_record_aggregation():
    payload = _build_payload(_canonical_bets_df(), "2026-04-20")
    r = payload["record"]
    assert r == {
        "wins": 1, "losses": 1, "pushes": 0,
        "settled": 2, "pending": 1,
        "profit_units": -0.1,  # 1.0 + (-1.1)
    }
