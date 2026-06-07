from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "daily" in result.output
    assert "report" in result.output


def test_report_empty():
    runner = CliRunner()
    with patch("main.get_summary") as mock_summary:
        mock_summary.return_value = {
            "total_bets": 0, "record": "0-0-0", "profit": 0, "roi": 0,
        }
        result = runner.invoke(cli, ["report"])
        assert result.exit_code == 0
        assert "0-0-0" in result.output


def _sched_game(away, home, fp):
    return {"away_team": away, "home_team": home, "away_pitcher": "P",
            "home_pitcher": "P", "game_pk": None, "game_date": fp}


def test_daily_processes_soonest_first_and_alerts_per_game():
    """End-to-end wiring: the daily pipeline runs games soonest-first and fires a
    per-game alert (scoped to game_key) the moment each flagged game finishes —
    not one batched alert at the end."""
    runner = CliRunner()
    # 'late' first in the schedule but starts later; 'early' must be processed first.
    games = [
        _sched_game("AAA", "LATE", "2026-06-07T23:05:00Z"),
        _sched_game("BBB", "EARLY", "2026-06-07T17:05:00Z"),
    ]

    processed_order = []

    def fake_process(game, odds_by_teams, injuries_by_team, game_date):
        gk = f"{game['away_team']}@{game['home_team']}"
        processed_order.append(gk)
        return {"game_key": gk, "status": "flagged", "max_edge": 0.07,
                "bets": [{"bet_type": "moneyline", "side": "home",
                          "odds": -120, "edge": 0.07}],
                "result": {"ensemble_meta": {"cost_usd": 0.01}}}

    alert_calls = []

    def fake_notify(game_date=None, game_key=None, **kw):
        alert_calls.append(game_key)
        return {"bets_total": 1, "bets_filtered": 1, "bets_new": 1, "sent": 1,
                "discord_enabled": True, "dry_run": False}

    with patch("main.rotate_old_cache", return_value=0), \
         patch("main.PARALLEL_GAMES", 1), \
         patch("main.get_probable_starters", return_value=games), \
         patch("main.get_mlb_odds", return_value=[]), \
         patch("main.get_confirmed_lineups", return_value={}), \
         patch("main.get_injuries", return_value=[]), \
         patch("agents.analyzed_games.load_analyzed", return_value={}), \
         patch("main._process_game", side_effect=fake_process), \
         patch("notify.send_notifications", side_effect=fake_notify):
        result = runner.invoke(
            cli, ["daily", "--date", "2026-06-07", "--no-lineup-filter"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    # Soonest-first: with one worker the FIFO queue processes EARLY before LATE,
    # even though LATE appeared first in the schedule.
    assert processed_order == ["BBB@EARLY", "AAA@LATE"]
    # Each flagged game triggered its own scoped per-game alert (the early game's
    # alert fires before the late game is even processed) — not one batch at end.
    # The trailing None is the end-of-pipeline safety-net sweep (game_key=None).
    assert alert_calls == ["BBB@EARLY", "AAA@LATE", None]
    assert "2 bets logged" in result.output
