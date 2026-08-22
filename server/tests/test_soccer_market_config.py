from server.odds.market_config import MarketConfig


def test_soccer_alternates_cover_all_regions_and_twelve_hours():
    cfg = MarketConfig.load("markets.soccer.toml")
    tier = cfg.tiers["alternates"]
    assert tier.enabled is True
    assert tier.interval_seconds == 300
    assert tier.regions == ["us", "us2", "us_ex", "uk", "eu"]
    assert tier.markets == ["alternate_spreads"]
    assert tier.games_window_hours == 12
