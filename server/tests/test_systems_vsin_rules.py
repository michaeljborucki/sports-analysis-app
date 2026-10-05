"""Rule branches for the systems added from the VSiN September 2026 articles.

Each test drives `evaluate_systems` with a synthetic context so the rule is
exercised without any network fetch, mirroring test_systems_evaluator.py.
"""
from datetime import date, datetime, timezone

from server.systems.evaluator import deduplicate_wagers, evaluate_systems
from server.systems.models import EvaluationGame


NOW = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)


def game(sport="ncaaf", home="Home", away="Away", **context):
    base = {"is_fbs_game": True} if sport == "ncaaf" else {}
    return EvaluationGame(
        event_id="game-1", sport=sport, home_team=home, away_team=away,
        commence_time=KICKOFF, data_timestamp=NOW, context={**base, **context},
    )


def signals_for(system_id, games):
    result = evaluate_systems(games, evaluated_at=NOW, requested_date=date(2026, 9, 10))
    return [s for s in result.signals if s.system_id == system_id]


# --- College football -------------------------------------------------

def test_two_ranked_teams_backs_the_home_side():
    hit = signals_for("FOOTBALL_25_CFB_TWO_RANKED_HOME", [game(
        home_is_ranked=True, away_is_ranked=True, neutral_site=False,
        home_spread=-1.5, away_spread=1.5,
    )])
    assert [s.selection for s in hit] == ["Home -1.5"]


def test_two_ranked_teams_skips_a_neutral_site_game():
    assert signals_for("FOOTBALL_25_CFB_TWO_RANKED_HOME", [game(
        home_is_ranked=True, away_is_ranked=True, neutral_site=True,
        home_spread=-1.5, away_spread=1.5,
    )]) == []


def test_unranked_road_team_within_seven_of_a_ranked_host_plays_under():
    hit = signals_for("FOOTBALL_26_CFB_UNRANKED_ROAD_CLOSE_UNDER", [game(
        home_is_ranked=True, away_is_ranked=False, neutral_site=False,
        away_spread=7.0, total=47.5,
    )])
    assert [s.selection for s in hit] == ["Under 47.5"]


def test_unranked_road_team_outside_seven_does_not_qualify():
    assert signals_for("FOOTBALL_26_CFB_UNRANKED_ROAD_CLOSE_UNDER", [game(
        home_is_ranked=True, away_is_ranked=False, neutral_site=False,
        away_spread=7.5, total=47.5,
    )]) == []


def test_revenge_against_a_porous_defense_backs_the_avenging_side():
    hit = signals_for("FOOTBALL_27_CFB_REVENGE_VS_POROUS_DEFENSE", [game(
        home_revenge=False, away_revenge=True,
        home_ppg_allowed=35.0, away_ppg_allowed=14.0,
        home_spread=-13.5, away_spread=13.5,
    )])
    assert [s.selection for s in hit] == ["Away +13.5"]


def test_revenge_against_a_stingy_defense_does_not_qualify():
    assert signals_for("FOOTBALL_27_CFB_REVENGE_VS_POROUS_DEFENSE", [game(
        home_revenge=False, away_revenge=True,
        home_ppg_allowed=34.9, away_ppg_allowed=14.0,
        home_spread=-13.5, away_spread=13.5,
    )]) == []


def test_dominant_prior_performance_is_backed_next_game():
    hit = signals_for("FOOTBALL_28_CFB_DOMINANT_PERFORMANCE_MOMENTUM", [game(
        home_previous_game_played=True, away_previous_game_played=True,
        home_previous_points=58, home_previous_points_allowed=9,
        away_previous_points=20, away_previous_points_allowed=17,
        home_spread=-21.5, away_spread=21.5,
    )])
    assert [s.selection for s in hit] == ["Home -21.5"]


def test_dominant_score_with_ten_allowed_does_not_qualify():
    assert signals_for("FOOTBALL_28_CFB_DOMINANT_PERFORMANCE_MOMENTUM", [game(
        home_previous_game_played=True, away_previous_game_played=True,
        home_previous_points=58, home_previous_points_allowed=10,
        away_previous_points=20, away_previous_points_allowed=17,
        home_spread=-21.5, away_spread=21.5,
    )]) == []


# --- NFL Week 1 -------------------------------------------------------

def nfl(**context):
    return game(sport="nfl", season_type="regular", week=1, **context)


def test_week1_divisional_home_underdog_is_backed():
    hit = signals_for("FOOTBALL_29_NFL_WEEK1_DIVISIONAL_HOME_DOG", [nfl(
        is_divisional=True, home_spread=3.0, away_spread=-3.0,
    )])
    assert [s.selection for s in hit] == ["Home +3"]


def test_week1_nonconference_pickem_home_team_is_faded():
    hit = signals_for("FOOTBALL_30_NFL_WEEK1_NONCONF_PICKEM_HOME_FADE", [nfl(
        is_conference_game=False, home_spread=-3.0, away_spread=3.0,
    )])
    assert [s.selection for s in hit] == ["Away +3"]


def test_week1_conference_game_is_not_a_pickem_fade():
    assert signals_for("FOOTBALL_30_NFL_WEEK1_NONCONF_PICKEM_HOME_FADE", [nfl(
        is_conference_game=True, home_spread=-3.0, away_spread=3.0,
    )]) == []


def test_week1_road_team_off_a_four_to_six_win_season_is_backed():
    hit = signals_for("FOOTBALL_31_NFL_WEEK1_ROAD_TEAM_4_TO_6_WINS", [nfl(
        away_prior_season_wins=6, away_spread=8.5,
    )])
    assert [s.selection for s in hit] == ["Away +8.5"]


def test_week1_road_team_off_a_seven_win_season_does_not_qualify():
    assert signals_for("FOOTBALL_31_NFL_WEEK1_ROAD_TEAM_4_TO_6_WINS", [nfl(
        away_prior_season_wins=7, away_spread=8.5,
    )]) == []


def test_week1_underdog_of_six_and_a_half_or_more_is_backed():
    hit = signals_for("FOOTBALL_32_NFL_WEEK1_BIG_UNDERDOG", [nfl(
        home_spread=-8.5, away_spread=8.5,
    )])
    assert [s.selection for s in hit] == ["Away +8.5"]


def test_week1_home_favorite_hosting_a_winning_team_is_backed():
    hit = signals_for("FOOTBALL_33_NFL_WEEK1_HOME_FAVORITE_VS_WINNING_TEAM", [nfl(
        home_spread=-3.0, away_spread=3.0, away_prior_season_win_pct=0.588,
    )])
    assert [s.selection for s in hit] == ["Home -3"]


def test_week1_divisional_road_underdog_inside_a_touchdown_is_backed():
    hit = signals_for("FOOTBALL_34_NFL_WEEK1_DIVISIONAL_ROAD_DOG", [nfl(
        is_divisional=True, away_spread=2.5, home_spread=-2.5,
    )])
    assert [s.selection for s in hit] == ["Away +2.5"]


def test_week1_high_scoring_team_is_faded_when_opponent_was_not():
    hit = signals_for("FOOTBALL_35_NFL_WEEK1_HIGH_SCORING_FADE", [nfl(
        home_prior_season_ppg=27.1, away_prior_season_ppg=19.4,
        home_spread=-7.0, away_spread=7.0,
    )])
    assert [s.selection for s in hit] == ["Away +7"]


def test_two_high_scoring_teams_cancel_the_fade():
    assert signals_for("FOOTBALL_35_NFL_WEEK1_HIGH_SCORING_FADE", [nfl(
        home_prior_season_ppg=27.1, away_prior_season_ppg=28.0,
        home_spread=-7.0, away_spread=7.0,
    )]) == []


def test_week1_stingy_defense_is_backed_against_a_leaky_one():
    hit = signals_for("FOOTBALL_36_NFL_WEEK1_STINGY_DEFENSE", [nfl(
        home_prior_season_ppg_allowed=19.2, away_prior_season_ppg_allowed=24.0,
        home_spread=-5.5, away_spread=5.5,
    )])
    assert [s.selection for s in hit] == ["Home -5.5"]


def test_week1_close_loss_rebound_is_backed():
    hit = signals_for("FOOTBALL_37_NFL_WEEK1_CLOSE_LOSS_REBOUND", [nfl(
        home_prior_season_close_losses=3, away_prior_season_close_losses=8,
        home_spread=-9.5, away_spread=9.5,
    )])
    assert [s.selection for s in hit] == ["Away +9.5"]


def test_week1_win_collapse_rebound_is_backed_and_pairs_with_the_under():
    games = [nfl(
        home_prior_season_win_change=-6, away_prior_season_win_change=0,
        home_spread=-7.0, away_spread=7.0, total=49.5,
    )]
    assert [s.selection for s in signals_for(
        "FOOTBALL_38_NFL_WEEK1_WIN_COLLAPSE_REBOUND", games
    )] == ["Home -7"]
    assert [s.selection for s in signals_for(
        "FOOTBALL_39_NFL_WEEK1_WIN_COLLAPSE_UNDER", games
    )] == ["Under 49.5"]


def test_two_collapsing_teams_cancel_the_rebound():
    assert signals_for("FOOTBALL_38_NFL_WEEK1_WIN_COLLAPSE_REBOUND", [nfl(
        home_prior_season_win_change=-6, away_prior_season_win_change=-5,
        home_spread=-7.0, away_spread=7.0, total=49.5,
    )]) == []


def test_week1_systems_do_not_fire_in_week_two():
    quiet = game(sport="nfl", season_type="regular", week=2,
                 is_divisional=True, home_spread=3.0, away_spread=-3.0)
    assert signals_for("FOOTBALL_29_NFL_WEEK1_DIVISIONAL_HOME_DOG", [quiet]) == []


# --- MLB --------------------------------------------------------------

def mlb(**context):
    return game(sport="mlb", home="Braves", away="Rays", **context)


def test_late_season_contender_small_favorite_is_backed():
    hit = signals_for("MLB_13_LATE_SEASON_CONTENDER_SMALL_FAVORITE", [mlb(
        month=9, home_win_pct=0.600, away_win_pct=0.585,
        home_moneyline=-127, away_moneyline=107,
    )])
    assert [s.selection for s in hit] == ["Braves"]


def test_small_favorite_below_the_win_pct_floor_does_not_qualify():
    assert signals_for("MLB_13_LATE_SEASON_CONTENDER_SMALL_FAVORITE", [mlb(
        month=9, home_win_pct=0.600, away_win_pct=0.579,
        home_moneyline=-127, away_moneyline=107,
    )]) == []


def test_short_favorite_outside_the_price_band_does_not_qualify():
    assert signals_for("MLB_13_LATE_SEASON_CONTENDER_SMALL_FAVORITE", [mlb(
        month=9, home_win_pct=0.600, away_win_pct=0.585,
        home_moneyline=-190, away_moneyline=160,
    )]) == []


def test_series_finale_losing_streak_is_backed():
    hit = signals_for("MLB_14_SERIES_FINALE_LOSING_STREAK", [mlb(
        series_game_number=3, series_length=3,
        home_losing_streak=0, away_losing_streak=3,
        home_moneyline=-127, away_moneyline=105,
    )])
    assert [s.selection for s in hit] == ["Rays"]


def test_mid_series_losing_streak_does_not_qualify():
    assert signals_for("MLB_14_SERIES_FINALE_LOSING_STREAK", [mlb(
        series_game_number=2, series_length=3,
        home_losing_streak=0, away_losing_streak=3,
        home_moneyline=-127, away_moneyline=105,
    )]) == []


def test_series_finale_road_dog_ending_a_road_trip_is_backed():
    hit = signals_for("MLB_15_SERIES_FINALE_ROAD_DOG_ENDING_TRIP", [mlb(
        series_game_number=3, series_length=3,
        away_moneyline=105, away_ends_road_trip=True,
    )])
    assert [s.selection for s in hit] == ["Rays"]


def test_series_finale_road_dog_staying_on_the_road_does_not_qualify():
    assert signals_for("MLB_15_SERIES_FINALE_ROAD_DOG_ENDING_TRIP", [mlb(
        series_game_number=3, series_length=3,
        away_moneyline=105, away_ends_road_trip=False,
    )]) == []


def test_overlapping_week1_systems_collapse_into_one_wager():
    """Three systems naming the same side must read as one bet, not three."""
    result = evaluate_systems([nfl(
        is_divisional=True, away_spread=8.5, home_spread=-8.5,
        away_prior_season_wins=5, away_prior_season_win_pct=0.294,
        home_prior_season_ppg=27.5, away_prior_season_ppg=18.0,
    )], evaluated_at=NOW, requested_date=date(2026, 9, 10))
    wagers = [w for w in deduplicate_wagers(result.signals) if w.selection == "Away +8.5"]
    assert len(wagers) == 1
    assert len(wagers[0].supporting_system_ids) >= 3
