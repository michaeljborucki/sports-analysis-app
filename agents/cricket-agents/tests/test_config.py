from config import (
    EDGE_THRESHOLDS, LEAGUES, VENUE_COORDS,
    CRICKET_API_BASE, ODDS_API_BASE, KELLY_FRACTION,
    BET_SLOTS, TEAM_NAME_TO_ABBREV,
)


def test_edge_thresholds_exist_for_all_bet_types():
    for bet_type in BET_SLOTS:
        assert bet_type in EDGE_THRESHOLDS
        assert 0 < EDGE_THRESHOLDS[bet_type] < 1


def test_leagues_defined():
    assert len(LEAGUES) > 0
    for league_key, league_cfg in LEAGUES.items():
        assert "name" in league_cfg
        assert "teams" in league_cfg
        assert "odds_key" in league_cfg


def test_team_name_to_abbrev():
    assert len(TEAM_NAME_TO_ABBREV) > 0
    assert "Mumbai Indians" in TEAM_NAME_TO_ABBREV
    assert TEAM_NAME_TO_ABBREV["Mumbai Indians"] == "MI"


def test_venue_coords_defined():
    assert len(VENUE_COORDS) > 0
    for venue, coords in VENUE_COORDS.items():
        assert len(coords) == 2
        lat, lon = coords
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180


def test_kelly_fraction():
    assert 0 < KELLY_FRACTION <= 0.25


def test_bet_slots():
    assert isinstance(BET_SLOTS, list)
    assert "moneyline" in BET_SLOTS
    assert len(BET_SLOTS) == 16


def test_cricket_api_base():
    assert CRICKET_API_BASE.startswith("https://")
