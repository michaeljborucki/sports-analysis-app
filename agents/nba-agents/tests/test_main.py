import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from click.testing import CliRunner
from main import cli, run_daily_pipeline


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "NBA" in result.output
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


def test_daily_no_games():
    runner = CliRunner()
    with patch("main.run_daily_pipeline") as mock_pipeline:
        mock_pipeline.return_value = 0
        # We need to patch asyncio.run since the daily command calls it
        with patch("main.asyncio") as mock_asyncio:
            mock_asyncio.run.return_value = 0
            result = runner.invoke(cli, ["daily", "--date", "2026-03-22"])
            assert result.exit_code == 0
            assert "Done. 0 bets logged" in result.output


def test_run_daily_pipeline_is_async():
    assert asyncio.iscoroutinefunction(run_daily_pipeline)
