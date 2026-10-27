import pytest


@pytest.fixture(autouse=True)
def isolate_odds_source(monkeypatch):
    """Keep unit tests on their temporary native caches by default."""
    monkeypatch.setenv("ODDS_SOURCE", "native")


@pytest.fixture(autouse=True)
def coral33_fixture_zone(monkeypatch):
    """Coral33 fixtures were captured while it rendered America/Denver; the
    live default is the user's LOCAL_TZ (Eastern since 2026-10-24). Pin the
    parse zone so fixture times keep meaning what they meant."""
    from zoneinfo import ZoneInfo
    from server.odds.books.coral33 import normalizer, wager_log
    monkeypatch.setattr(normalizer, "_CORAL_TZ_NAME", "America/Denver")
    monkeypatch.setattr(normalizer, "_CORAL_TZ", ZoneInfo("America/Denver"))
    monkeypatch.setattr(wager_log, "_CORAL_TZ", ZoneInfo("America/Denver"))
