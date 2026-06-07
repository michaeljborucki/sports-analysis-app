from config import (
    TOUR_CONFIG, EDGE_THRESHOLDS, KELLY_FRACTION_ATP, KELLY_FRACTION_WTA,
    API_TENNIS_BASE,
    ENSEMBLE_MODELS, ENSEMBLE_CHALLENGER, CONSENSUS_MIN_VOTES,
    MAX_CALLS_PER_GAME, SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT,
    ODDS_API_KEY, OPENROUTER_API_KEY, WEATHER_API_KEY,
    OPENROUTER_BASE_URL, ODDS_API_BASE, WEATHER_API_BASE,
    DATA_DIR, BETS_CSV, MODEL_WEIGHTS_FILE, MODEL_PREDICTIONS_CSV,
)


def test_tour_config_has_atp_and_wta():
    assert "atp" in TOUR_CONFIG
    assert "wta" in TOUR_CONFIG


def test_tour_config_atp_keys():
    atp = TOUR_CONFIG["atp"]
    assert atp["odds_sport_key"] == "tennis_atp"
    assert atp["kelly_fraction"] == 0.25


def test_tour_config_wta_keys():
    wta = TOUR_CONFIG["wta"]
    assert wta["odds_sport_key"] == "tennis_wta"
    assert wta["kelly_fraction"] == 0.125


def test_edge_thresholds_has_three_tennis_slots():
    assert "moneyline" in EDGE_THRESHOLDS
    assert "game_handicap" in EDGE_THRESHOLDS
    assert "total_games" in EDGE_THRESHOLDS
    assert len(EDGE_THRESHOLDS) == 3


def test_no_mlb_config():
    import config
    assert not hasattr(config, "MLB_API_BASE")
    assert not hasattr(config, "TEAM_ABBREVS")
    assert not hasattr(config, "TEAM_NAME_TO_ABBREV")
    assert not hasattr(config, "PARK_FACTORS")
    assert not hasattr(config, "PARK_COORDS")


def test_game_timeout():
    # Must be long enough for ensemble Phase 1 (~150s) + potential Phase 2 expansion
    # (~2-3 min). The cancel_futures fix in ensemble/orchestrator.py makes this
    # a hard, enforceable per-match budget.
    assert GAME_TIMEOUT >= 240


def test_ensemble_models():
    assert len(ENSEMBLE_MODELS) == 6
    assert ENSEMBLE_CHALLENGER in ENSEMBLE_MODELS
