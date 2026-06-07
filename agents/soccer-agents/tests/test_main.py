from unittest.mock import patch
from click.testing import CliRunner
from main import cli

def test_cli_group():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Soccer" in result.output

def test_daily_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["daily", "--help"])
    assert result.exit_code == 0
    assert "--league" in result.output

def test_match_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["match", "--help"])
    assert result.exit_code == 0


class _FakeOdds:
    def __init__(self, away, home, commence_time):
        self.away = away
        self.home = home
        self.commence_time = commence_time


def test_daily_processes_soonest_first_and_alerts_per_match():
    """The soccer pipeline analyzes matches soonest-kickoff first and fires a
    per-match alert as each finishes — not one batched alert at the end."""
    runner = CliRunner()
    # LATE listed first by the odds feed, but EARLY kicks off sooner.
    odds = [
        _FakeOdds("AAA", "LATE", "2026-06-07T21:00:00Z"),
        _FakeOdds("BBB", "EARLY", "2026-06-07T18:00:00Z"),
    ]

    processed_order = []

    def fake_screen(o, lg, game_date):
        return (f"{o.away}@{o.home}", "brief", {"odds": {}}, 0.08)

    def fake_sim(mk, brief, md, game_date, lg):
        processed_order.append(mk)
        return (mk, 1, 0.01)  # one bet logged

    alert_calls = []

    def fake_notify(game_date=None, **kw):
        alert_calls.append(game_date)
        return {"bets_total": 1, "bets_filtered": 1, "bets_new": 1, "sent": 1,
                "discord_enabled": True, "dry_run": False}

    with patch("main.PARALLEL_GAMES", 1), \
         patch("main.get_soccer_odds", return_value=odds), \
         patch("main._screen_match", side_effect=fake_screen), \
         patch("main._simulate_match", side_effect=fake_sim), \
         patch("notify.send_notifications", side_effect=fake_notify):
        result = runner.invoke(
            cli, ["daily", "--date", "2026-06-07", "--league", "MLS"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    # Soonest-first: EARLY simulated before LATE despite feed order.
    assert processed_order == ["BBB@EARLY", "AAA@LATE"]
    # Each flagged match triggered its own alert as it finished (two per-match
    # calls), plus the trailing end-of-pipeline safety-net sweep.
    assert len(alert_calls) == 3
    assert "2 bets logged" in result.output
