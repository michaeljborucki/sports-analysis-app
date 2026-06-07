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
