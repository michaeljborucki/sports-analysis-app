from __future__ import annotations

from pathlib import Path

from server.odds.books.coral33.mapping import (
    PERIOD_SUFFIX,
    load_coral33_config,
)


CONFIG = Path(__file__).parent.parent / "config" / "coral33.toml"


def test_default_config_loads():
    cfg = load_coral33_config(CONFIG)
    assert "nba" in cfg.sports
    assert "nhl" in cfg.sports
    assert "mlb" in cfg.sports
    assert cfg.sports["nba"].sport_type == "BASKETBALL"
    assert "NBA" in cfg.sports["nba"].subtypes_main
    assert "NBA+ALT+LINE" in cfg.sports["nba"].subtypes_alt


def test_main_period_call_expansion():
    cfg = load_coral33_config(CONFIG)
    calls = cfg.sports["nba"].main_period_calls
    # Cartesian of subtypes_main × periods
    assert ("BASKETBALL", "NBA", "Game") in calls
    assert ("BASKETBALL", "NBA", "1st Quarter") in calls
    # 1 subtype × 7 periods
    assert len(calls) == 7


def test_alt_calls_fixed_to_game_period():
    cfg = load_coral33_config(CONFIG)
    alts = cfg.sports["nba"].alt_calls
    assert alts == [("BASKETBALL", "NBA+ALT+LINE", "Game")]


def test_period_suffixes_cover_expected_names():
    expected = {"Game", "1st Half", "2nd Half",
                "1st Quarter", "2nd Quarter", "3rd Quarter", "4th Quarter",
                "1st Period", "2nd Period", "3rd Period",
                "1st 5 Innings"}
    assert expected.issubset(set(PERIOD_SUFFIX.keys()))
    assert PERIOD_SUFFIX["Game"] == ""
    assert PERIOD_SUFFIX["1st Quarter"] == "_q1"
