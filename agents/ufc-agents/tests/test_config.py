import config


def test_edge_thresholds_keys():
    assert set(config.EDGE_THRESHOLDS.keys()) == {"moneyline", "total_rounds", "method"}


def test_edge_thresholds_values():
    assert config.EDGE_THRESHOLDS["moneyline"] == 0.06
    assert config.EDGE_THRESHOLDS["total_rounds"] == 0.06
    assert config.EDGE_THRESHOLDS["method"] == 0.08


def test_kelly_fraction():
    assert config.KELLY_FRACTION == 0.125


def test_bet_slots():
    assert config.BET_SLOTS == ["moneyline", "total_rounds", "method"]


def test_odds_sport_key():
    assert config.ODDS_SPORT_KEY == "mma_mixed_martial_arts"


def test_weight_classes_exist():
    assert len(config.WEIGHT_CLASSES) > 0
    assert "Lightweight" in config.WEIGHT_CLASSES
    assert "Heavyweight" in config.WEIGHT_CLASSES


def test_ensemble_config():
    assert len(config.ENSEMBLE_MODELS) == 6
    assert config.ENSEMBLE_CHALLENGER == "claude"
    assert config.CONSENSUS_MIN_VOTES == 3
    assert config.MAX_CALLS_PER_GAME == 50


def test_game_timeout():
    assert config.GAME_TIMEOUT == 180


def test_no_mlb_artifacts():
    assert not hasattr(config, "TEAM_ABBREVS")
    assert not hasattr(config, "TEAM_NAME_TO_ABBREV")
    assert not hasattr(config, "PARK_FACTORS")
    assert not hasattr(config, "PARK_COORDS")
    assert not hasattr(config, "MLB_API_BASE")
