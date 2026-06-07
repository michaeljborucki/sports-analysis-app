import os
import tempfile
import pandas as pd
from tracker import log_bet, load_bets, update_result, get_summary, _profit_units, _stake_units


def test_profit_favorite_win_is_one_unit():
    assert _profit_units(-155, "W") == 1.0
    assert _profit_units(-110, "W") == 1.0


def test_profit_favorite_loss_is_stake():
    assert _profit_units(-155, "L") == -1.55
    assert _profit_units(-200, "L") == -2.0


def test_profit_underdog_win_is_odds_ratio():
    assert _profit_units(150, "W") == 1.5
    assert _profit_units(200, "W") == 2.0


def test_profit_underdog_loss_is_one_unit():
    assert _profit_units(150, "L") == -1.0
    assert _profit_units(300, "L") == -1.0


def test_profit_push_is_zero():
    assert _profit_units(-155, "P") == 0.0
    assert _profit_units(150, "P") == 0.0


def test_stake_favorite_scales_with_odds():
    assert _stake_units(-155) == 1.55
    assert _stake_units(-110) == 1.1


def test_stake_underdog_is_one_unit():
    assert _stake_units(150) == 1.0
    assert _stake_units(300) == 1.0


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


def test_new_bets_csv_has_clv_columns(tmp_path):
    csv = str(tmp_path / "bets.csv")
    log_bet({
        "date": "2026-04-20", "game": "A vs B", "bet_type": "moneyline",
        "side": "player_a", "odds": 110, "sim_prob": 0.5, "edge": 0.05, "kelly_pct": 0.01,
    }, csv_path=csv)
    df = pd.read_csv(csv)
    for col in ("close_odds", "close_prob", "clv_cents", "clv_pct"):
        assert col in df.columns, f"missing {col}"


def test_legacy_csv_gets_clv_columns_on_load(tmp_path):
    """A bets.csv predating CLV should auto-gain the new columns on load/log."""
    csv = str(tmp_path / "bets.csv")
    legacy = pd.DataFrame([{
        "date": "2026-04-01", "start_time": "", "game": "X vs Y",
        "bet_type": "moneyline", "side": "player_a",
        "odds": -120, "sim_prob": 0.6, "market_prob": 0.5,
        "edge": 0.1, "kelly_pct": 0.02, "result": "W", "profit": 1.0,
    }])
    legacy.to_csv(csv, index=False)

    df = load_bets(csv_path=csv)
    for col in ("close_odds", "close_prob", "clv_cents", "clv_pct"):
        assert col in df.columns, f"missing {col}"


def test_lookup_clv_from_closing_line(tmp_path, monkeypatch):
    from scrapers import closing_lines as cl
    from tracker import lookup_clv

    cl_csv = tmp_path / "closing_lines.csv"
    pd.DataFrame([{
        "date": "2026-04-20", "game": "A. Rublev vs A. Fils", "tour": "atp",
        "market": "moneyline", "side": "player_a", "line": "",
        "close_odds": 180, "close_prob_devig": 0.35,
        "captured_at": "2026-04-20T13:50:00Z",
    }]).to_csv(cl_csv, index=False)
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(cl_csv))

    bet = {
        "date": "2026-04-20", "game": "A. Rublev vs A. Fils",
        "bet_type": "moneyline", "side": "player_a", "odds": 196,
    }
    result = lookup_clv(bet)
    # Bet 196, close 180 → positive CLV
    assert result["close_odds"] == 180
    assert result["clv_cents"] == 16
    assert result["clv_pct"] > 0
    assert abs(result["close_prob"] - 0.35) < 1e-6


def test_lookup_clv_returns_none_when_no_close(tmp_path, monkeypatch):
    from scrapers import closing_lines as cl
    from tracker import lookup_clv

    cl_csv = tmp_path / "closing_lines.csv"
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(cl_csv))

    bet = {
        "date": "2026-04-20", "game": "Unknown vs Unknown",
        "bet_type": "moneyline", "side": "player_a", "odds": 120,
    }
    assert lookup_clv(bet) is None


def test_update_result_populates_clv(tmp_path, monkeypatch):
    """update_result should fill CLV columns if a closing line exists."""
    from scrapers import closing_lines as cl

    cl_csv = tmp_path / "closing_lines.csv"
    pd.DataFrame([{
        "date": "2026-04-20", "game": "A vs B", "tour": "atp",
        "market": "moneyline", "side": "player_a", "line": "",
        "close_odds": 100, "close_prob_devig": 0.50,
        "captured_at": "2026-04-20T13:00:00Z",
    }]).to_csv(cl_csv, index=False)
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(cl_csv))

    bets_csv = str(tmp_path / "bets.csv")
    log_bet({
        "date": "2026-04-20", "game": "A vs B", "bet_type": "moneyline",
        "side": "player_a", "odds": 120, "sim_prob": 0.52, "edge": 0.04, "kelly_pct": 0.01,
    }, csv_path=bets_csv)
    update_result(0, "W", csv_path=bets_csv)

    df = load_bets(csv_path=bets_csv)
    row = df.iloc[0]
    assert row["result"] == "W"
    assert int(row["close_odds"]) == 100
    assert int(row["clv_cents"]) == 20  # bet +120 vs close +100 → +20 cents
    assert float(row["clv_pct"]) > 0
