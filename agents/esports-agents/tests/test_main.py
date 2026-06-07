from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "daily" in result.output
    assert "report" in result.output
    assert "match" in result.output


def test_cli_daily_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["daily", "--help"])
    assert result.exit_code == 0
    assert "--game" in result.output
    assert "--date" in result.output


def test_report_empty():
    runner = CliRunner()
    with patch("main.get_summary") as mock_summary:
        mock_summary.return_value = {
            "total_bets": 0, "record": "0-0-0", "profit": 0, "roi": 0,
        }
        result = runner.invoke(cli, ["report"])
        assert result.exit_code == 0
        assert "0-0-0" in result.output


def test_cli_match_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["match", "--help"])
    assert result.exit_code == 0
    assert "--game" in result.output
    assert "--format" in result.output
