"""Tests for scrapers/toss.py — TDD: write first, verify fail, then implement."""
from scrapers.toss import get_toss_analysis, TossAnalysis


def test_known_venue_wankhede():
    result = get_toss_analysis("Wankhede Stadium")
    assert isinstance(result, TossAnalysis)
    assert result.venue == "Wankhede Stadium"
    assert 0.0 <= result.bat_first_pct <= 1.0
    assert 0.0 <= result.chase_pct <= 1.0
    assert abs(result.bat_first_pct + result.chase_pct - 1.0) < 0.001
    assert 0.0 <= result.bat_first_win_rate <= 1.0
    assert 0.0 <= result.chase_win_rate <= 1.0
    assert result.typical_toss_choice in ("bat", "field")
    assert isinstance(result.dew_assessment, str)
    assert result.sample_size > 0


def test_known_venue_mcg():
    result = get_toss_analysis("Melbourne Cricket Ground")
    assert isinstance(result, TossAnalysis)
    assert result.venue == "Melbourne Cricket Ground"
    assert result.sample_size > 0


def test_known_venue_eden_gardens():
    result = get_toss_analysis("Eden Gardens")
    assert isinstance(result, TossAnalysis)
    assert result.venue == "Eden Gardens"
    assert result.typical_toss_choice in ("bat", "field")


def test_known_venue_chinnaswamy():
    result = get_toss_analysis("M. Chinnaswamy Stadium")
    assert isinstance(result, TossAnalysis)
    assert result.venue == "M. Chinnaswamy Stadium"


def test_known_venue_adelaide_oval():
    result = get_toss_analysis("Adelaide Oval")
    assert isinstance(result, TossAnalysis)
    assert result.venue == "Adelaide Oval"


def test_unknown_venue_returns_defaults():
    result = get_toss_analysis("Some Random Stadium XYZ")
    assert isinstance(result, TossAnalysis)
    assert result.venue == "Some Random Stadium XYZ"
    assert abs(result.bat_first_pct - 0.5) < 0.001
    assert abs(result.chase_pct - 0.5) < 0.001
    assert abs(result.bat_first_win_rate - 0.5) < 0.001
    assert abs(result.chase_win_rate - 0.5) < 0.001
    assert result.sample_size == 0


def test_fuzzy_match_partial_name():
    # "Wankhede" alone should fuzzy-match to "Wankhede Stadium"
    result = get_toss_analysis("Wankhede")
    assert isinstance(result, TossAnalysis)
    # fuzzy matched — sample_size should be > 0 (not defaults)
    assert result.sample_size > 0


def test_empty_venue_returns_defaults():
    result = get_toss_analysis("")
    assert isinstance(result, TossAnalysis)
    assert abs(result.bat_first_pct - 0.5) < 0.001
    assert result.sample_size == 0
