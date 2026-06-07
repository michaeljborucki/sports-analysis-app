from click.testing import CliRunner
from main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Tennis" in result.output


def test_daily_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["daily", "--help"])
    assert result.exit_code == 0
    assert "--tour" in result.output


def test_match_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["match", "--help"])
    assert result.exit_code == 0
    assert "PLAYER_A" in result.output


def test_report_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0


def test_health_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["health", "--help"])
    assert result.exit_code == 0
