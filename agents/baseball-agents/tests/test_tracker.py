import os
import tempfile
import threading
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


def test_log_bet_persists_game_time(tmp_path):
    """game_time column should round-trip through the CSV."""
    csv = str(tmp_path / "bets.csv")
    bet = {
        "date": "2026-04-23",
        "game": "SD@COL",
        "bet_type": "moneyline",
        "side": "home",
        "odds": -120,
        "sim_prob": 0.58,
        "edge": 0.04,
        "kelly_pct": 0.015,
        "game_time": "2026-04-23T20:40:00Z",
    }
    log_bet(bet, csv_path=csv)
    df = load_bets(csv_path=csv)
    assert "game_time" in df.columns
    assert df.iloc[0]["game_time"] == "2026-04-23T20:40:00Z"


def test_log_bet_missing_game_time_is_empty(tmp_path):
    """Bets without game_time should store an empty string, not error."""
    csv = str(tmp_path / "bets.csv")
    bet = {
        "date": "2026-04-23",
        "game": "SD@COL",
        "bet_type": "moneyline",
        "side": "home",
        "odds": -120,
        "sim_prob": 0.58,
        "edge": 0.04,
        "kelly_pct": 0.015,
    }
    log_bet(bet, csv_path=csv)
    df = load_bets(csv_path=csv)
    assert "game_time" in df.columns
    # Empty/missing cell reads back as NaN or "" — both acceptable for display
    val = df.iloc[0]["game_time"]
    assert val == "" or (isinstance(val, float) and str(val) == "nan") or pd.isna(val)


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


def test_concurrent_log_bet(tmp_path):
    """Verify no bets are lost when logging concurrently."""
    csv_path = str(tmp_path / "concurrent_bets.csv")
    bets = [
        {"date": "2026-03-22", "game": f"TEAM{i}@OPP{i}", "bet_type": "moneyline",
         "side": f"TEAM{i}", "odds": -110, "sim_prob": 0.55,
         "edge": 0.05, "kelly_pct": 0.02}
        for i in range(20)
    ]

    threads = [threading.Thread(target=log_bet, args=(b,), kwargs={"csv_path": csv_path}) for b in bets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    df = pd.read_csv(csv_path)
    assert len(df) == 20, f"Expected 20 bets, got {len(df)}"
