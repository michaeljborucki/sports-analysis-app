from unittest.mock import patch, MagicMock
from agents.health_check import (
    check_api_tennis, check_odds_api, check_openrouter, check_player_archive,
)


@patch("agents.health_check.API_TENNIS_KEY", "test-key")
@patch("agents.health_check.requests.get")
def test_check_api_tennis_ok(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    ok, msg = check_api_tennis()
    assert ok
    assert "OK" in msg


@patch("agents.health_check.API_TENNIS_KEY", "")
def test_check_api_tennis_no_key():
    ok, msg = check_api_tennis()
    assert not ok
    assert "NO KEY" in msg


@patch("agents.health_check.OPENROUTER_API_KEY", "test-key")
@patch("agents.health_check.requests.get")
def test_check_openrouter_ok(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    ok, msg = check_openrouter()
    assert ok


def test_check_player_archive_ok(tmp_path, monkeypatch):
    """Both 2024 files present → OK."""
    monkeypatch.setattr("agents.health_check.SACKMANN_LOCAL_DIR", str(tmp_path))
    (tmp_path / "atp").mkdir()
    (tmp_path / "wta").mkdir()
    (tmp_path / "atp" / "atp_matches_2024.csv").write_text("x")
    (tmp_path / "wta" / "wta_matches_2024.csv").write_text("x")
    ok, msg = check_player_archive()
    assert ok
    assert "OK" in msg


def test_check_player_archive_missing(tmp_path, monkeypatch):
    """Missing files → FAIL with bootstrap hint."""
    monkeypatch.setattr("agents.health_check.SACKMANN_LOCAL_DIR", str(tmp_path))
    ok, msg = check_player_archive()
    assert not ok
    assert "bootstrap" in msg.lower()
