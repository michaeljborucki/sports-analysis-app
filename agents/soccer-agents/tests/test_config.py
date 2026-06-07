import config


def test_supported_leagues_exist():
    assert "MLS" in config.SUPPORTED_LEAGUES
    assert "Eredivisie" in config.SUPPORTED_LEAGUES
    assert "Serie A" in config.SUPPORTED_LEAGUES


def test_active_leagues_are_subset_of_supported():
    for league in config.ACTIVE_LEAGUES:
        assert league in config.SUPPORTED_LEAGUES


def test_edge_thresholds_cover_soccer_bet_types():
    assert "asian_handicap" in config.EDGE_THRESHOLDS
    assert "total" in config.EDGE_THRESHOLDS
    assert "btts" in config.EDGE_THRESHOLDS
    assert "moneyline" not in config.EDGE_THRESHOLDS
    assert "run_line" not in config.EDGE_THRESHOLDS
    assert "first_5_ml" not in config.EDGE_THRESHOLDS
    assert "first_5_total" not in config.EDGE_THRESHOLDS


def test_kelly_fraction_eighth_kelly():
    assert config.KELLY_FRACTION == 0.125


def test_home_advantage_by_league():
    assert "MLS" in config.HOME_ADVANTAGE_BY_LEAGUE
    assert all(0 < v < 0.30 for v in config.HOME_ADVANTAGE_BY_LEAGUE.values())


def test_no_mlb_remnants():
    assert not hasattr(config, "TEAM_ABBREVS")
    assert not hasattr(config, "TEAM_NAME_TO_ABBREV")
    assert not hasattr(config, "PARK_FACTORS")
    assert not hasattr(config, "PARK_COORDS")
    assert not hasattr(config, "MLB_API_BASE")


def test_bet_slots():
    assert config.BET_SLOTS == ["asian_handicap", "total", "btts"]


def test_game_timeout():
    assert config.GAME_TIMEOUT == 180


def test_ensemble_models():
    assert len(config.ENSEMBLE_MODELS) == 6
