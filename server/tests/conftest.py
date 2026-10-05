import pytest


@pytest.fixture(autouse=True)
def isolate_odds_source(monkeypatch):
    """Keep unit tests on their temporary native caches by default."""
    monkeypatch.setenv("ODDS_SOURCE", "native")
