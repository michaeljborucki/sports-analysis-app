import json
import os
from unittest.mock import patch

import pandas as pd
import pytest

from notify import config, format as nf, dispatch


# ---------- config tests ----------

def test_load_config_creates_default(tmp_path):
    path = tmp_path / "alerts_config.json"
    cfg = config.load_alerts_config(str(path))
    assert path.exists()
    assert "discord" in cfg
    assert cfg["bet_types"] == config.DEFAULT_BET_TYPES


def test_default_alerts_include_nrfi():
    """NRFI re-added to alerts on 2026-05-04 (was excluded 2026-04-23, restored
    after operator review)."""
    assert "nrfi" in config.DEFAULT_BET_TYPES


def test_default_alerts_cover_full_mainline_set():
    """Discord should alert on every mainline bet type that's enabled in the
    pipeline. If anything is missing, it's a config drift bug."""
    from agents.bet_card import MAINLINE_BET_TYPES
    assert MAINLINE_BET_TYPES.issubset(set(config.DEFAULT_BET_TYPES)), \
        f"missing from alerts: {MAINLINE_BET_TYPES - set(config.DEFAULT_BET_TYPES)}"


# ---------------------------------------------------------------------------
# Per-channel filter split (2026-04-29):
#   - picks dispatch: filtered by cfg["bet_types"]
#   - grades / summary / season records: include EVERY bet type
# ---------------------------------------------------------------------------

def test_grade_notify_includes_all_bet_types(mock_env, tmp_path, monkeypatch):
    """Grades + summary channels should NOT filter by cfg.bet_types — user
    wants the daily record to show every market we tracked, even though only
    main-line picks are individually alerted on."""
    from notify import grades as grades_mod
    from datetime import date as _date

    csv = tmp_path / "bets.csv"
    rows = [
        {"date": "2026-04-14", "game": "ARI@BAL", "bet_type": "moneyline",
         "side": "home", "odds": -150, "sim_prob": 0.6, "edge": 0.05,
         "kelly_pct": 0.02, "result": "W", "profit": 0.67,
         "close_odds": -160, "close_prob": 0.62, "clv_cents": 10, "clv_pct": 0.02},
        {"date": "2026-04-14", "game": "ARI@BAL", "bet_type": "batter_hits",
         "side": "Aaron Judge over 1.5", "odds": -110, "sim_prob": 0.55,
         "edge": 0.05, "kelly_pct": 0.02, "result": "W", "profit": 0.91,
         "close_odds": -120, "close_prob": 0.55, "clv_cents": 10, "clv_pct": 0.02},
        {"date": "2026-04-14", "game": "ARI@BAL", "bet_type": "team_total_home",
         "side": "home under 4.5", "odds": -110, "sim_prob": 0.6, "edge": 0.05,
         "kelly_pct": 0.02, "result": "L", "profit": -1.0,
         "close_odds": -110, "close_prob": 0.52, "clv_cents": 0, "clv_pct": 0.0},
    ]
    pd.DataFrame(rows).to_csv(csv, index=False)
    import tracker
    monkeypatch.setattr(tracker, "BETS_CSV", str(csv))

    cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
    cfg["discord_grades"] = {"enabled": True, "webhook_url": "https://x"}
    cfg["discord_summary"] = {"enabled": True, "webhook_url": "https://x"}
    cfg["bet_types"] = ["moneyline"]  # picks filter — narrow on purpose
    cfg_path = mock_env / "alerts.json"
    cfg_path.write_text(json.dumps(cfg))

    # Pin date so the "in past" gate passes
    class FakeDate(_date):
        @classmethod
        def today(cls):
            return _date(2026, 4, 15)
    monkeypatch.setattr("notify.grades.dt_date", FakeDate)

    with patch("notify.grades.send_discord", return_value=1):
        result = grades_mod.send_grade_notifications(
            game_date="2026-04-14", config_path=str(cfg_path))

    # All three bets must have been included, NOT just moneyline
    assert result["bets_filtered"] == 3, (
        f"grade notify filtered down to {result['bets_filtered']} of 3 — should "
        "include every bet type, not just cfg['bet_types']"
    )


def test_season_notify_includes_all_bet_types(mock_env, tmp_path, monkeypatch):
    """Season totals must aggregate over every market, not just main lines."""
    from notify import season as season_mod
    from datetime import date as _date

    csv = tmp_path / "bets.csv"
    rows = [
        {"date": "2026-04-10", "game": "X@Y", "bet_type": "moneyline",
         "side": "home", "odds": -150, "sim_prob": 0.6, "edge": 0.05,
         "kelly_pct": 0.02, "result": "W", "profit": 0.67,
         "close_odds": -160, "close_prob": 0.62, "clv_cents": 10, "clv_pct": 0.02},
        {"date": "2026-04-10", "game": "X@Y", "bet_type": "batter_total_bases",
         "side": "Player over 1.5", "odds": -110, "sim_prob": 0.55,
         "edge": 0.05, "kelly_pct": 0.02, "result": "L", "profit": -1.0,
         "close_odds": -110, "close_prob": 0.55, "clv_cents": 0, "clv_pct": 0.0},
    ]
    pd.DataFrame(rows).to_csv(csv, index=False)
    import tracker
    monkeypatch.setattr(tracker, "BETS_CSV", str(csv))

    cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
    cfg["discord_season"] = {"enabled": True, "webhook_url": "https://x"}
    cfg["bet_types"] = ["moneyline"]  # narrow picks filter
    cfg_path = mock_env / "alerts.json"
    cfg_path.write_text(json.dumps(cfg))

    class FakeDate(_date):
        @classmethod
        def today(cls):
            return _date(2026, 4, 15)
    monkeypatch.setattr("notify.season.dt_date", FakeDate)

    with patch("notify.season.send_discord", return_value=1):
        result = season_mod.send_season_notification(
            through_date="2026-04-10", config_path=str(cfg_path))

    # Both bets included
    assert result["bets_filtered"] == 2, (
        f"season notify filtered down to {result['bets_filtered']} of 2 — should "
        "include every bet type, not just cfg['bet_types']"
    )


def test_env_var_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.com/wh/123")
    path = tmp_path / "alerts_config.json"
    config.write_default_config(str(path))
    cfg = config.load_alerts_config(str(path))
    assert cfg["discord"]["webhook_url"] == "https://example.com/wh/123"


def test_env_var_unset_resolves_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    path = tmp_path / "alerts_config.json"
    config.write_default_config(str(path))
    cfg = config.load_alerts_config(str(path))
    assert cfg["discord"]["webhook_url"] == ""


def test_discord_enabled_requires_url():
    assert not config.discord_enabled({"discord": {"enabled": True, "webhook_url": ""}})
    assert not config.discord_enabled({"discord": {"enabled": False, "webhook_url": "x"}})
    assert config.discord_enabled({"discord": {"enabled": True, "webhook_url": "https://x"}})


# ---------- format tests ----------

def _bet(game="ARI@BAL", bet_type="moneyline", side="home", odds=-150,
         sim_prob=0.6, edge=0.05, kelly=0.02):
    return {
        "date": "2026-04-14", "game": game, "bet_type": bet_type, "side": side,
        "odds": odds, "sim_prob": sim_prob, "edge": edge, "kelly_pct": kelly,
    }


def test_filter_bets_drops_non_allowed():
    bets = [_bet(bet_type="moneyline"), _bet(bet_type="batter_hits", side="X over 1.5")]
    filtered = nf.filter_bets(bets, ["moneyline"])
    assert len(filtered) == 1
    assert filtered[0]["bet_type"] == "moneyline"


def test_filter_bets_min_edge():
    bets = [_bet(edge=0.04), _bet(edge=0.06)]
    filtered = nf.filter_bets(bets, ["moneyline"], min_edge=0.05)
    assert len(filtered) == 1
    assert filtered[0]["edge"] == 0.06


def test_filter_bets_min_kelly():
    bets = [_bet(kelly=0.005), _bet(kelly=0.03)]
    filtered = nf.filter_bets(bets, ["moneyline"], min_kelly=0.01)
    assert len(filtered) == 1


def test_format_bet_line_includes_breakeven():
    line = nf._format_bet_line(_bet(sim_prob=0.55))
    assert "-115" in line  # breakeven for 0.55 (-122) with 5+ wiggle, floored to nearest 5


# ---------- ET time formatter ----------

def test_format_et_time_summer_edt():
    # 2026-07-15 20:40Z → 4:40 PM EDT (UTC-4 in summer)
    assert nf._format_et_time("2026-07-15T20:40:00Z") == "4:40 PM ET"


def test_format_et_time_winter_est():
    # 2026-01-15 20:40Z → 3:40 PM EST (UTC-5 in winter)
    assert nf._format_et_time("2026-01-15T20:40:00Z") == "3:40 PM ET"


def test_format_et_time_evening_game():
    # 2026-04-23 23:40Z → 7:40 PM EDT (DST has started by April 23)
    assert nf._format_et_time("2026-04-23T23:40:00Z") == "7:40 PM ET"


def test_format_et_time_empty_returns_empty():
    assert nf._format_et_time("") == ""
    assert nf._format_et_time(None) == ""


def test_format_et_time_malformed_returns_empty():
    assert nf._format_et_time("not a date") == ""
    assert nf._format_et_time("nan") == ""


def test_format_game_block_has_header_row():
    block = nf.format_game_block("NYM@CHC", [_bet()])
    assert "TYPE" in block and "SIDE" in block and "ODDS" in block
    assert "MODEL" in block and "EDGE" in block and "BE" in block
    assert "KELLY" not in block  # Kelly column dropped


def test_format_game_block_shows_time_when_present():
    bet = _bet(game="SD@COL")
    bet["game_time"] = "2026-04-23T23:40:00Z"  # 7:40 PM ET
    block = nf.format_game_block("SD@COL", [bet])
    assert "SD@COL" in block
    assert "7:40 PM ET" in block


def test_format_game_block_omits_time_when_missing():
    bet = _bet(game="SD@COL")  # no game_time key
    block = nf.format_game_block("SD@COL", [bet])
    assert "SD@COL" in block
    assert "ET" not in block  # no time suffix


def test_format_game_block_omits_time_when_empty():
    bet = _bet(game="SD@COL")
    bet["game_time"] = ""
    block = nf.format_game_block("SD@COL", [bet])
    assert "ET" not in block


def test_split_to_messages_packs_within_limit():
    bets = [_bet(game=f"GAME{i}@HOME", bet_type="moneyline") for i in range(20)]
    msgs = nf.split_to_messages("2026-04-14", bets, char_limit=500)
    assert len(msgs) > 1
    # Skip header (msg[0]), check all game blocks respect limit
    for m in msgs[1:]:
        assert len(m) <= 500


def test_split_to_messages_no_picks():
    msgs = nf.split_to_messages("2026-04-14", [], char_limit=2000)
    assert len(msgs) == 1
    assert "No picks" in msgs[0]


def test_split_oversized_single_game_subsplits():
    bets = [_bet(game="HUGE@GAME", bet_type="moneyline", side=f"home_{i}") for i in range(30)]
    msgs = nf.split_to_messages("2026-04-14", bets, char_limit=400)
    assert len(msgs) > 2  # header + multiple sub-blocks
    for m in msgs[1:]:
        assert len(m) <= 400


def test_format_uses_discord_markdown():
    bets = [_bet()]
    msgs = nf.split_to_messages("2026-04-14", bets)
    assert any("**" in m for m in msgs)  # bold header
    assert any("```" in m for m in msgs)  # code block


# ---------- dispatch tests ----------

@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    """Redirect data paths to tmp_path."""
    monkeypatch.setattr(dispatch, "SENT_LOG_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(config, "ALERTS_CONFIG_PATH", str(tmp_path / "alerts.json"))
    return tmp_path


def _write_bets_csv(tmp_path, monkeypatch, rows):
    csv = tmp_path / "bets.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    import tracker
    monkeypatch.setattr(tracker, "BETS_CSV", str(csv))
    return csv


def _enabled_cfg():
    cfg = json.loads(json.dumps(config.DEFAULT_CONFIG))
    cfg["discord"] = {"enabled": True, "webhook_url": "https://example.com/x"}
    return cfg


def test_dispatch_discord_disabled_is_noop(mock_env, tmp_path, monkeypatch):
    _write_bets_csv(tmp_path, monkeypatch, [_bet()])
    cfg_path = mock_env / "alerts.json"
    config.write_default_config(str(cfg_path))
    summary = dispatch.send_notifications(game_date="2026-04-14")
    assert summary["bets_filtered"] == 1
    assert summary["discord_enabled"] is False
    assert summary["sent"] == 0


def test_dispatch_sends_and_marks_sent(mock_env, tmp_path, monkeypatch):
    _write_bets_csv(tmp_path, monkeypatch, [_bet(), _bet(side="away", odds=130)])
    cfg_path = mock_env / "alerts.json"
    cfg_path.write_text(json.dumps(_enabled_cfg()))

    with patch("notify.dispatch.send_discord", return_value=2) as m:
        summary = dispatch.send_notifications(game_date="2026-04-14")
    m.assert_called_once()
    assert summary["sent"] == 2
    assert os.path.exists(dispatch.SENT_LOG_PATH)

    # Second run should find nothing new
    with patch("notify.dispatch.send_discord") as m2:
        summary2 = dispatch.send_notifications(game_date="2026-04-14")
    m2.assert_not_called()
    assert summary2["bets_new"] == 0


def test_dispatch_force_resends(mock_env, tmp_path, monkeypatch):
    _write_bets_csv(tmp_path, monkeypatch, [_bet()])
    cfg_path = mock_env / "alerts.json"
    cfg_path.write_text(json.dumps(_enabled_cfg()))

    with patch("notify.dispatch.send_discord", return_value=1):
        dispatch.send_notifications(game_date="2026-04-14")

    with patch("notify.dispatch.send_discord", return_value=1) as m2:
        summary = dispatch.send_notifications(game_date="2026-04-14", force=True)
    assert summary["bets_new"] == 1
    m2.assert_called_once()


def test_dispatch_dry_run_does_not_send(mock_env, tmp_path, monkeypatch, capsys):
    _write_bets_csv(tmp_path, monkeypatch, [_bet()])
    cfg_path = mock_env / "alerts.json"
    cfg_path.write_text(json.dumps(_enabled_cfg()))

    with patch("notify.dispatch.send_discord") as m:
        summary = dispatch.send_notifications(game_date="2026-04-14", dry_run=True)
    m.assert_not_called()
    captured = capsys.readouterr()
    assert "ARI@BAL" in captured.out
    assert summary["dry_run"] is True


def test_dispatch_filters_player_props(mock_env, tmp_path, monkeypatch):
    _write_bets_csv(tmp_path, monkeypatch, [
        _bet(),
        _bet(bet_type="batter_hits", side="Aaron Judge over 1.5"),
    ])
    cfg_path = mock_env / "alerts.json"
    cfg_path.write_text(json.dumps(_enabled_cfg()))

    with patch("notify.dispatch.send_discord", return_value=1):
        summary = dispatch.send_notifications(game_date="2026-04-14")
    assert summary["bets_total"] == 2
    assert summary["bets_filtered"] == 1
