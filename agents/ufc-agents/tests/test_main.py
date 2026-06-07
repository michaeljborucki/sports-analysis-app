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


def test_cli_has_fight_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "fight" in result.output


def test_cli_has_ufc_branding():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "UFC" in result.output
