"""Tests for CLV closing-line capture and lookup."""
import os
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

from scrapers.odds import OddsData


def _sample_odds() -> OddsData:
    return OddsData(
        player_a="N. Djokovic",
        player_b="C. Alcaraz",
        commence_time="2026-06-30T14:00:00Z",
        moneyline={"player_a": -150, "player_b": 130},
        game_handicap={
            "player_a_point": -3.5, "player_a_odds": -110,
            "player_b_point": 3.5, "player_b_odds": -110,
        },
        total_games={"line": 22.5, "over_odds": -115, "under_odds": -105},
    )


def test_extract_closing_rows_produces_all_three_markets():
    from scrapers.closing_lines import extract_closing_rows

    rows = extract_closing_rows(_sample_odds())
    markets = {r["market"] for r in rows}
    assert markets == {"moneyline", "game_handicap", "total_games"}
    # 2 rows per market (player_a/player_b, or over/under)
    assert len(rows) == 6


def test_extract_closing_rows_devigs_moneyline_pair():
    from scrapers.closing_lines import extract_closing_rows

    rows = extract_closing_rows(_sample_odds())
    ml = [r for r in rows if r["market"] == "moneyline"]
    assert len(ml) == 2
    pa = next(r for r in ml if r["side"] == "player_a")
    pb = next(r for r in ml if r["side"] == "player_b")
    # Devigged probs sum to 1.0
    assert abs(pa["close_prob_devig"] + pb["close_prob_devig"] - 1.0) < 1e-4
    assert pa["close_odds"] == -150
    assert pb["close_odds"] == 130


def test_extract_closing_rows_handicap_carries_lines():
    from scrapers.closing_lines import extract_closing_rows

    rows = extract_closing_rows(_sample_odds())
    gh = [r for r in rows if r["market"] == "game_handicap"]
    pa = next(r for r in gh if r["side"] == "player_a")
    pb = next(r for r in gh if r["side"] == "player_b")
    assert pa["line"] == -3.5
    assert pb["line"] == 3.5


def test_extract_closing_rows_totals_carries_line():
    from scrapers.closing_lines import extract_closing_rows

    rows = extract_closing_rows(_sample_odds())
    tg = [r for r in rows if r["market"] == "total_games"]
    over = next(r for r in tg if r["side"] == "over")
    under = next(r for r in tg if r["side"] == "under")
    assert over["line"] == 22.5
    assert under["line"] == 22.5


def test_extract_closing_rows_skips_missing_markets():
    from scrapers.closing_lines import extract_closing_rows

    o = OddsData(
        player_a="A", player_b="B", commence_time="",
        moneyline={"player_a": -120, "player_b": 100},
    )
    rows = extract_closing_rows(o)
    assert {r["market"] for r in rows} == {"moneyline"}


def test_find_closing_line_returns_latest(tmp_path, monkeypatch):
    from scrapers import closing_lines as cl

    csv_path = tmp_path / "closing_lines.csv"
    df = pd.DataFrame([
        {"date": "2026-04-20", "game": "A vs B", "market": "moneyline",
         "side": "player_a", "line": "", "close_odds": -140,
         "close_prob_devig": 0.58, "captured_at": "2026-04-20T14:00:00Z", "player_name": ""},
        {"date": "2026-04-20", "game": "A vs B", "market": "moneyline",
         "side": "player_a", "line": "", "close_odds": -150,
         "close_prob_devig": 0.60, "captured_at": "2026-04-20T14:50:00Z", "player_name": ""},
    ])
    df.to_csv(csv_path, index=False)
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))

    hit = cl.find_closing_line("2026-04-20", "A vs B", "moneyline", "player_a")
    assert hit is not None
    assert hit["close_odds"] == -150  # latest wins


def test_find_closing_line_returns_none_when_missing(tmp_path, monkeypatch):
    from scrapers import closing_lines as cl

    csv_path = tmp_path / "closing_lines.csv"
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))
    assert cl.find_closing_line("2026-04-20", "A vs B", "moneyline", "player_a") is None


def test_find_closing_line_matches_handicap_with_line(tmp_path, monkeypatch):
    from scrapers import closing_lines as cl

    csv_path = tmp_path / "closing_lines.csv"
    df = pd.DataFrame([
        {"date": "2026-04-20", "game": "A vs B", "market": "game_handicap",
         "side": "player_a", "line": "-3.5", "close_odds": -110,
         "close_prob_devig": 0.51, "captured_at": "2026-04-20T14:00:00Z", "player_name": ""},
        {"date": "2026-04-20", "game": "A vs B", "market": "game_handicap",
         "side": "player_a", "line": "-4.5", "close_odds": 115,
         "close_prob_devig": 0.45, "captured_at": "2026-04-20T14:00:00Z", "player_name": ""},
    ])
    df.to_csv(csv_path, index=False)
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))

    hit = cl.find_closing_line("2026-04-20", "A vs B", "game_handicap", "player_a", line=-3.5)
    assert hit["close_odds"] == -110
    hit2 = cl.find_closing_line("2026-04-20", "A vs B", "game_handicap", "player_a", line=-4.5)
    assert hit2["close_odds"] == 115
