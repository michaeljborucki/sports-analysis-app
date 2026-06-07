from config import (
    ODDSPAPI_API_KEY,
    ODDSPAPI_BASE,
    ODDS_API_BASE,
    KELLY_FRACTION,
    SUPPORTED_GAMES,
    MAX_TIER,
    GAME_TIMEOUT,
)


def test_oddspapi_base_url():
    assert ODDSPAPI_BASE.startswith("https://")


def test_odds_api_base_url():
    assert ODDS_API_BASE.startswith("https://")


def test_supported_games_non_empty():
    assert isinstance(SUPPORTED_GAMES, list)
    assert len(SUPPORTED_GAMES) >= 1
    assert "cs2" in SUPPORTED_GAMES


def test_max_tier_positive_int():
    assert isinstance(MAX_TIER, int)
    assert MAX_TIER >= 1


def test_game_timeout():
    assert isinstance(GAME_TIMEOUT, int)
    assert GAME_TIMEOUT == 180


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 0.25
