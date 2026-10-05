from server.sports import SPORTS
from server.api.settings import _build_response
from server.odds.market_config import MarketConfig
from server.user_settings import UserSettings


def test_nfl_resolves_regular_season_and_preseason_feeds():
    assert SPORTS["nfl"].odds_api_sport_keys == (
        "americanfootball_nfl",
        "americanfootball_nfl_preseason",
    )


def test_coral33_nfl_props_are_visible_without_enabling_paid_prop_fetches():
    response = _build_response(UserSettings(), [SPORTS["nfl"]])
    props = next(t for t in response.sports[0].tiers if t.name == "player_props")
    assert {m.key for m in props.markets if m.enabled} == {
        "player_pass_completions", "player_pass_interceptions",
        "player_pass_longest_completion", "player_pass_attempts",
        "player_pass_yds", "player_rush_yds", "player_pass_tds",
        "player_reception_longest", "player_reception_yds",
        "player_receptions", "player_kicking_points",
    }
    cfg = MarketConfig.load(SPORTS["nfl"].markets_config)
    assert "player_props" not in {tier.name for tier in cfg.enabled_tiers()}
