from config import (
    EDGE_THRESHOLDS, TEAM_ABBREVS, TEAM_NAME_TO_ABBREV, KELLY_FRACTION, ODDS_API_BASE, nba_season,
    ODDS_EVENT_MARKETS, PROP_ENSEMBLE_MODELS, MAX_CONCURRENT_GAMES, MAX_CONCURRENT_API_CALLS,
)

ALL_19_SLOTS = {
    "moneyline", "spread", "total",
    "first_half_ml", "first_half_total", "first_half_spread",
    "q1_ml", "q1_spread", "q1_total",
    "q2_total", "q3_total", "q4_total",
    "team_total_home", "team_total_away",
    "player_points", "player_rebounds", "player_assists",
    "player_threes", "player_pra",
}


def test_edge_thresholds_has_all_bet_types():
    expected = ALL_19_SLOTS
    assert set(EDGE_THRESHOLDS.keys()) == expected


def test_edge_thresholds_has_all_19_slots():
    assert set(EDGE_THRESHOLDS.keys()) == ALL_19_SLOTS


def test_odds_event_markets_string():
    for key in ("h2h_h1", "player_points", "team_totals", "totals_q1"):
        assert key in ODDS_EVENT_MARKETS, f"{key!r} missing from ODDS_EVENT_MARKETS"


def test_prop_ensemble_models():
    assert len(PROP_ENSEMBLE_MODELS) == 3


def test_concurrency_settings():
    assert MAX_CONCURRENT_GAMES > 0
    assert MAX_CONCURRENT_API_CALLS > 0


def test_all_thresholds_positive():
    for k, v in EDGE_THRESHOLDS.items():
        assert v > 0, f"{k} threshold must be positive"


def test_team_abbrevs_count():
    assert len(TEAM_ABBREVS) == 30


def test_team_name_mapping_covers_all_abbrevs():
    mapped = set(TEAM_NAME_TO_ABBREV.values())
    for abbrev in TEAM_ABBREVS:
        assert abbrev in mapped, f"{abbrev} missing from TEAM_NAME_TO_ABBREV"


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 1.0


def test_odds_api_base():
    assert "the-odds-api.com" in ODDS_API_BASE


def test_nba_season_march():
    assert nba_season("2026-03-22") == "2025-26"


def test_nba_season_october():
    assert nba_season("2025-10-15") == "2025-26"


def test_nba_season_january():
    assert nba_season("2026-01-01") == "2025-26"
