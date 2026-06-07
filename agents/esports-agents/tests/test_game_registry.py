import pytest
from games import get_game, GAMES


# ---------------------------------------------------------------------------
# Registry presence
# ---------------------------------------------------------------------------

def test_registry_has_cs2():
    assert "cs2" in GAMES


def test_registry_has_lol():
    assert "lol" in GAMES


# ---------------------------------------------------------------------------
# CS2 assertions
# ---------------------------------------------------------------------------

def test_get_game_returns_module_with_config():
    game = get_game("cs2")
    assert hasattr(game, "config")
    assert hasattr(game.config, "BET_SLOTS")
    assert hasattr(game.config, "PROB_FIELDS")
    assert hasattr(game.config, "SLOT_SECTION")
    assert hasattr(game.config, "PRIMARY_PROB_FIELD")
    assert hasattr(game.config, "EDGE_THRESHOLDS")
    assert hasattr(game.config, "ACTIVE_DUTY_MAPS")


def test_cs2_bet_slots():
    game = get_game("cs2")
    assert game.config.BET_SLOTS == ["moneyline", "map_handicap", "total_maps"]


def test_cs2_edge_thresholds_format_aware():
    game = get_game("cs2")
    assert "bo1" in game.config.EDGE_THRESHOLDS
    assert "bo3" in game.config.EDGE_THRESHOLDS
    assert "bo5" in game.config.EDGE_THRESHOLDS
    assert game.config.EDGE_THRESHOLDS["bo1"]["moneyline"] == 0.07
    assert "map_handicap" not in game.config.EDGE_THRESHOLDS["bo1"]


# ---------------------------------------------------------------------------
# LoL assertions
# ---------------------------------------------------------------------------

def test_lol_module_has_full_interface():
    """LoL module must expose config, scrapers, briefing, and prompt."""
    game = get_game("lol")
    assert hasattr(game, "config")
    assert hasattr(game, "scrapers")
    assert hasattr(game, "briefing")
    assert hasattr(game, "prompt")


def test_lol_config_has_required_attributes():
    game = get_game("lol")
    assert hasattr(game.config, "BET_SLOTS")
    assert hasattr(game.config, "PROB_FIELDS")
    assert hasattr(game.config, "SLOT_SECTION")
    assert hasattr(game.config, "PRIMARY_PROB_FIELD")
    assert hasattr(game.config, "EDGE_THRESHOLDS")
    assert hasattr(game.config, "ACTIVE_DUTY_MAPS")
    assert hasattr(game.config, "ANALYST_ROLES")


def test_lol_bet_slots():
    game = get_game("lol")
    assert game.config.BET_SLOTS == ["moneyline", "map_handicap", "total_maps"]


def test_lol_edge_thresholds_format_aware():
    game = get_game("lol")
    assert "bo1" in game.config.EDGE_THRESHOLDS
    assert "bo3" in game.config.EDGE_THRESHOLDS
    assert "bo5" in game.config.EDGE_THRESHOLDS
    assert game.config.EDGE_THRESHOLDS["bo1"]["moneyline"] == 0.07
    assert "map_handicap" not in game.config.EDGE_THRESHOLDS["bo1"]
    assert "map_handicap" in game.config.EDGE_THRESHOLDS["bo3"]


def test_lol_active_duty_maps_contains_summoners_rift():
    game = get_game("lol")
    assert "summoners_rift" in game.config.ACTIVE_DUTY_MAPS


def test_lol_analyst_roles():
    game = get_game("lol")
    expected_roles = {"laning", "macro", "draft", "form", "market", "contrarian"}
    assert expected_roles == set(game.config.ANALYST_ROLES)


def test_lol_scrapers_have_required_functions():
    game = get_game("lol")
    assert callable(game.scrapers.fetch_team_profile)
    assert callable(game.scrapers.fetch_upcoming_matches)
    assert callable(game.scrapers.fetch_head_to_head)
    assert callable(game.scrapers.fetch_match_result)


def test_lol_briefing_has_build_briefing():
    game = get_game("lol")
    assert callable(game.briefing.build_briefing)


def test_lol_prompt_has_system_prompt():
    game = get_game("lol")
    assert hasattr(game.prompt, "SYSTEM_PROMPT")
    assert isinstance(game.prompt.SYSTEM_PROMPT, str)
    assert len(game.prompt.SYSTEM_PROMPT) > 100


def test_lol_prob_fields_structure():
    game = get_game("lol")
    pf = game.config.PROB_FIELDS
    assert "moneyline" in pf
    assert "map_handicap" in pf
    assert "total_maps" in pf
    assert "team_a_win_prob" in pf["moneyline"]
    assert "team_b_win_prob" in pf["moneyline"]
    assert "favorite_cover_prob" in pf["map_handicap"]
    assert "over_prob" in pf["total_maps"]
    assert "under_prob" in pf["total_maps"]


def test_lol_primary_prob_field():
    game = get_game("lol")
    ppf = game.config.PRIMARY_PROB_FIELD
    assert ppf["moneyline"] == "team_a_win_prob"
    assert ppf["map_handicap"] == "favorite_cover_prob"
    assert ppf["total_maps"] == "over_prob"


# ---------------------------------------------------------------------------
# Unknown game
# ---------------------------------------------------------------------------

def test_get_game_unknown_raises():
    with pytest.raises(KeyError):
        get_game("unknown_game")
