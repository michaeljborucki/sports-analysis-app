import os
import tempfile
import pandas as pd
from tracker import log_bet, load_bets, update_result, get_summary


def test_log_and_load_bet(tmp_path):
    csv = str(tmp_path / "bets.csv")
    bet = {
        "date": "2026-04-01",
        "game": "BOS@NYY",
        "bet_type": "moneyline",
        "side": "home",
        "odds": -150,
        "sim_prob": 0.62,
        "edge": 0.055,
        "kelly_pct": 0.02,
    }
    log_bet(bet, csv_path=csv)
    df = load_bets(csv_path=csv)
    assert len(df) == 1
    assert df.iloc[0]["game"] == "BOS@NYY"


def test_update_result(tmp_path):
    csv = str(tmp_path / "bets.csv")
    bet = {
        "date": "2026-04-01",
        "game": "BOS@NYY",
        "bet_type": "moneyline",
        "side": "home",
        "odds": -150,
        "sim_prob": 0.62,
        "edge": 0.055,
        "kelly_pct": 0.02,
    }
    log_bet(bet, csv_path=csv)
    update_result(0, "W", csv_path=csv)
    df = load_bets(csv_path=csv)
    assert df.iloc[0]["result"] == "W"


def test_get_summary_empty(tmp_path):
    csv = str(tmp_path / "bets.csv")
    summary = get_summary(csv_path=csv)
    assert summary["total_bets"] == 0
