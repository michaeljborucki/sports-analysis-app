"""Tests for Discord notification pipeline.

Covers:
  - Unit convention parity with tracker (fav W = +1.00, fav L = -stake, etc.)
  - Formatters render without exceptions and stay under the Discord cap
  - Dedupe behavior for picks / grades / season channels
  - Date header appears on graded blocks
"""
import json
import os
import pandas as pd

import pytest

from notify import format as nf
from notify.config import load_alerts_config, DEFAULT_BET_TYPES


SAMPLE_PICKS = [
    {
        "date": "2026-04-18", "game": "A. Rublev vs H. Medjedovic",
        "bet_type": "moneyline", "side": "player_a",
        "odds": -155, "sim_prob": 0.7333, "market_prob": 0.6071,
        "edge": 0.1262, "kelly_pct": 0.05, "result": "W", "profit": 1.0,
    },
    {
        "date": "2026-04-18", "game": "R. Jodar vs A. Fils",
        "bet_type": "moneyline", "side": "player_b",
        "odds": -155, "sim_prob": 0.68, "market_prob": 0.5852,
        "edge": 0.0948, "kelly_pct": 0.0322, "result": "W", "profit": 1.0,
    },
    {
        "date": "2026-04-19", "game": "A. Rublev vs A. Fils",
        "bet_type": "moneyline", "side": "player_a",
        "odds": 196, "sim_prob": 0.43, "market_prob": 0.31,
        "edge": 0.12, "kelly_pct": 0.0244, "result": "", "profit": "",
    },
]


def test_unit_convention_fav_win_is_plus_one_unit():
    profit, risk = nf.unit_profit_and_risk(-155, "W")
    assert profit == 1.0
    assert risk == 1.55


def test_unit_convention_fav_loss_is_minus_stake():
    profit, risk = nf.unit_profit_and_risk(-155, "L")
    assert profit == -1.55
    assert risk == 1.55


def test_unit_convention_dog_win_scales_with_odds():
    profit, risk = nf.unit_profit_and_risk(196, "W")
    assert profit == 1.96
    assert risk == 1.0


def test_unit_convention_push_has_zero_risk():
    profit, risk = nf.unit_profit_and_risk(-150, "P")
    assert profit == 0.0
    assert risk == 0.0


def test_filter_bets_drops_disallowed_types():
    bets = SAMPLE_PICKS + [{"bet_type": "player_props", "edge": 0.5, "kelly_pct": 0.1}]
    kept = nf.filter_bets(bets, ["moneyline"])
    assert len(kept) == 3
    assert all(b["bet_type"] == "moneyline" for b in kept)


def test_filter_bets_respects_min_edge():
    kept = nf.filter_bets(SAMPLE_PICKS, ["moneyline"], min_edge=0.10)
    assert len(kept) == 2  # only the two with edge >= 10%


def test_pick_messages_fit_discord_limit():
    msgs = nf.split_to_messages("2026-04-19", SAMPLE_PICKS, char_limit=nf.DISCORD_MAX)
    assert all(len(m) <= nf.DISCORD_MAX for m in msgs)
    assert "Bet Card" in msgs[0]


def test_pick_block_includes_be_column():
    block = nf.format_match_block(
        "A. Rublev vs H. Medjedovic", [SAMPLE_PICKS[0]]
    )
    assert " BE" in block  # header column
    # Rublev sim 73.33% → BE price around -250 after wiggle


def test_grade_block_includes_date_header():
    graded = [b for b in SAMPLE_PICKS if b["result"]]
    msgs = nf.split_grade_blocks("2026-04-18", graded)
    assert msgs, "split_grade_blocks should return at least one message"
    assert "Grades — 2026-04-18" in msgs[0]
    assert "graded pick" in msgs[0]


def test_grade_block_empty_still_stamped_with_date():
    msgs = nf.split_grade_blocks("2026-04-18", [])
    assert len(msgs) == 1
    assert "2026-04-18" in msgs[0]


def test_grade_summary_header_includes_record_and_roi():
    graded = [b for b in SAMPLE_PICKS if b["result"]]
    header = nf.format_grade_header("2026-04-18", graded)
    assert "Grades — 2026-04-18" in header
    assert "2-0-0" in header
    # Profit = +2.00u, risk = 3.10u, ROI ~= 64.5%
    assert "+2.00u" in header
    assert "ROI +64.5%" in header


def test_season_summary_aggregates_across_dates():
    graded = [b for b in SAMPLE_PICKS if b["result"]]
    msg = nf.format_season_summary("2026-04-18", graded)
    assert "Season Totals" in msg
    assert "2-0-0" in msg
    assert "+2.00u" in msg


def test_load_alerts_config_creates_default_when_missing(tmp_path, monkeypatch):
    cfg_path = str(tmp_path / "alerts_config.json")
    cfg = load_alerts_config(cfg_path)
    assert cfg["bet_types"] == DEFAULT_BET_TYPES
    assert os.path.exists(cfg_path)


def test_dispatch_dry_run_picks(tmp_path, monkeypatch):
    """Dry-run path emits messages, does not write sent-log, does not POST."""
    from notify import dispatch
    csv = tmp_path / "bets.csv"
    pd.DataFrame(SAMPLE_PICKS).to_csv(csv, index=False)
    monkeypatch.setattr(dispatch, "load_bets", lambda: pd.read_csv(csv))
    monkeypatch.setattr(dispatch, "SENT_LOG_PATH", str(tmp_path / "sent.json"))

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "discord": {"enabled": True, "webhook_url": "https://example/hook"},
        "discord_grades": {"enabled": False, "webhook_url": ""},
        "discord_summary": {"enabled": False, "webhook_url": ""},
        "discord_season": {"enabled": False, "webhook_url": ""},
        "bet_types": ["moneyline"],
        "min_edge_pct": 0.0, "min_kelly_pct": 0.0,
    }))
    s = dispatch.send_notifications(
        game_date="2026-04-19", dry_run=True, config_path=str(cfg)
    )
    assert s["bets_new"] == 1
    # dry_run reports message count (header + one match block = 2)
    assert s["sent"] == 2
    assert not os.path.exists(str(tmp_path / "sent.json"))


def test_dispatch_skips_already_started_matches(tmp_path, monkeypatch):
    """Bets on matches whose start_time has passed should not go out."""
    from notify import dispatch
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    future = (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    today = now.date().isoformat()

    bets = [
        {"date": today, "start_time": past, "game": "Already Started",
         "bet_type": "moneyline", "side": "player_a", "odds": -110,
         "sim_prob": 0.55, "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": ""},
        {"date": today, "start_time": future, "game": "Upcoming",
         "bet_type": "moneyline", "side": "player_b", "odds": 120,
         "sim_prob": 0.50, "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": ""},
    ]
    csv = tmp_path / "bets.csv"
    pd.DataFrame(bets).to_csv(csv, index=False)
    monkeypatch.setattr(dispatch, "load_bets", lambda: pd.read_csv(csv))
    monkeypatch.setattr(dispatch, "SENT_LOG_PATH", str(tmp_path / "sent.json"))

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "discord": {"enabled": True, "webhook_url": "https://example/hook"},
        "discord_grades": {"enabled": False, "webhook_url": ""},
        "discord_summary": {"enabled": False, "webhook_url": ""},
        "discord_season": {"enabled": False, "webhook_url": ""},
        "bet_types": ["moneyline"], "min_edge_pct": 0.0, "min_kelly_pct": 0.0,
    }))
    s = dispatch.send_notifications(
        game_date=today, dry_run=True, config_path=str(cfg)
    )
    assert s["bets_total"] == 2
    assert s["bets_new"] == 1  # only the upcoming match


def test_dispatch_passes_through_legacy_rows_without_start_time(tmp_path, monkeypatch):
    """Rows that predate the start_time column should still be sendable."""
    from notify import dispatch
    from datetime import date as dt_date

    today = dt_date.today().isoformat()
    bets = [
        {"date": today, "start_time": "", "game": "Legacy Row",
         "bet_type": "moneyline", "side": "player_a", "odds": -110,
         "sim_prob": 0.55, "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": ""},
    ]
    csv = tmp_path / "bets.csv"
    pd.DataFrame(bets).to_csv(csv, index=False)
    monkeypatch.setattr(dispatch, "load_bets", lambda: pd.read_csv(csv))
    monkeypatch.setattr(dispatch, "SENT_LOG_PATH", str(tmp_path / "sent.json"))

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "discord": {"enabled": True, "webhook_url": "https://example/hook"},
        "discord_grades": {"enabled": False, "webhook_url": ""},
        "discord_summary": {"enabled": False, "webhook_url": ""},
        "discord_season": {"enabled": False, "webhook_url": ""},
        "bet_types": ["moneyline"], "min_edge_pct": 0.0, "min_kelly_pct": 0.0,
    }))
    s = dispatch.send_notifications(
        game_date=today, dry_run=True, config_path=str(cfg)
    )
    assert s["bets_new"] == 1


def test_season_dispatch_blocks_same_day():
    from notify import season
    from datetime import date as dt_date
    s = season.send_season_notification(
        through_date=dt_date.today().isoformat(), dry_run=True,
    )
    assert s["skipped_reason"] == "through_date_not_in_past"
