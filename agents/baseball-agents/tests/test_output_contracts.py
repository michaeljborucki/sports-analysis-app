"""Output-string contract tests.

The cron prompts pattern-match against specific phrases printed by close-capture
and auto-analyzer. If the script changes those strings, the cron's decision
tree silently breaks (auto-shutoff stops working, or burst-cron never spawns).

These tests pin the exact phrases. If a phrase changes here, the corresponding
cron prompt must change too.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pandas as pd

from click.testing import CliRunner

from agents import auto_analyzer as aa


# ---------------------------------------------------------------------------
# auto-analyzer phrases
# ---------------------------------------------------------------------------

class TestAutoAnalyzerPhrases:
    def test_no_games_due_phrase(self):
        """Cron prompt branch #3 expects this phrase to recognize a no-op fire."""
        # Future-unanalyzed games exist, but none are within 2h
        future_game = {
            "away_team": "BAL", "home_team": "KC",
            "game_date": "2026-04-21T03:00:00Z",
            "game_pk": 1, "away_pitcher": "X", "home_pitcher": "Y",
        }
        with patch("agents.auto_analyzer.get_probable_starters", return_value=[future_game]), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}), \
             patch("agents.auto_analyzer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
            mock_dt.fromisoformat = datetime.fromisoformat
            runner = CliRunner()
            result = runner.invoke(aa.main, ["--dry-run"])
        # Pin: must contain this exact substring (cron prompts grep for it)
        assert "no games due within 2h window. Standing by." in result.output

    def test_monitoring_complete_phrase(self):
        """Cron prompt branch #1 calls CronDelete on this phrase."""
        # No games at all → shutoff condition met
        with patch("agents.auto_analyzer.get_probable_starters", return_value=[]), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            runner = CliRunner()
            result = runner.invoke(aa.main, ["--dry-run"])
        assert "auto-analyzer: monitoring complete for today" in result.output

    def test_due_games_phrase(self):
        """Cron prompt branch #2 detects a launch by this prefix."""
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        due_game = {
            "away_team": "BAL", "home_team": "KC",
            "game_date": "2026-04-21T00:30:00Z",  # T+90 min
            "game_pk": 1, "away_pitcher": "X", "home_pitcher": "Y",
        }
        with patch("agents.auto_analyzer.get_probable_starters", return_value=[due_game]), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}), \
             patch("agents.auto_analyzer.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            runner = CliRunner()
            result = runner.invoke(aa.main, ["--dry-run"])
        # Branch #2: "auto-analyzer: N games due:"
        assert "auto-analyzer:" in result.output
        assert "games due" in result.output


# ---------------------------------------------------------------------------
# close-capture phrases (tested via direct return-value inspection)
# ---------------------------------------------------------------------------

from scrapers import closing_lines as cl


class TestCloseCapturePhrases:
    def test_monitoring_complete_signal_returned(self, tmp_path, monkeypatch):
        """capture_closing_lines returns monitoring_complete_for_today=True
        when no future games today. Cron prompt branch #1 keys off the CLI
        translation of this signal."""
        from zoneinfo import ZoneInfo
        csv_path = tmp_path / "closing_lines.csv"
        monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))

        # Pre-check 1 uses datetime.now() in America/New_York to derive
        # today's date — we can't mock datetime.now without more surgery,
        # so align the test data with the actual current Eastern date.
        now_utc = datetime.now(timezone.utc)
        today_et = now_utc.astimezone(ZoneInfo("America/New_York")).date()
        past_fp_utc = now_utc - timedelta(hours=3)
        past_game = {
            "away_team": "BAL", "home_team": "KC",
            "game_date": past_fp_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "game_pk": 1, "away_pitcher": "X", "home_pitcher": "Y",
        }
        # Mock bets.csv to pass pre-check 1
        import pandas as pd
        bets_df = pd.DataFrame([{"date": today_et.isoformat()}])
        bets_csv = tmp_path / "bets.csv"
        bets_df.to_csv(bets_csv, index=False)

        with patch("scrapers.closing_lines.DATA_DIR", str(tmp_path)), \
             patch("scrapers.pitchers.get_probable_starters",
                   return_value=[past_game]):
            summary = cl.capture_closing_lines(now_utc=now_utc)

        assert summary.get("monitoring_complete_for_today") is True


def test_close_capture_cli_complete_phrase():
    """The exact CLI output the cron prompt greps for."""
    # This is the literal click.echo string in main.py close_capture
    expected_phrase = "CLV monitoring complete for today — all games have started."
    # Read main.py to ensure the phrase is present (defense vs accidental rename)
    with open("/Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py") as f:
        content = f.read()
    assert expected_phrase in content, \
        f"Expected phrase missing from main.py — did someone rename the shutoff signal?"


def test_close_capture_summary_format():
    """The slow watcher's branch #2 detects 'CLV capture: N game(s)' where
    N > 0. Pin this format (constructed in main.py close_capture)."""
    with open("/Users/mikeborucki/personal_workspace/agents/baseball-agents/main.py") as f:
        content = f.read()
    # The format string must use "CLV capture: " prefix
    assert "CLV capture:" in content
    assert "game(s)" in content
