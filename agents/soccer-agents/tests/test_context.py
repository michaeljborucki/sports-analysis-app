from scrapers.context import get_match_context

def test_get_match_context_returns_expected_fields():
    ctx = get_match_context("Inter Miami CF", "LA Galaxy", league="MLS")
    assert "home_motivation" in ctx
    assert "away_motivation" in ctx
    assert "derby" in ctx
    assert "fixture_congestion" in ctx

def test_get_match_context_defaults():
    ctx = get_match_context("Team A", "Team B", league="MLS")
    assert isinstance(ctx["derby"], bool)
    assert isinstance(ctx["home_motivation"], str)
