from datetime import date, datetime, timezone

from server.systems.evaluator import deduplicate_wagers, evaluate_systems
from server.systems.models import EvaluationGame


NOW = datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)


def game(**context):
    return EvaluationGame(
        event_id="game-1",
        sport="ncaaf",
        home_team="Home",
        away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW,
        context={"is_fbs_game": True, **context},
    )


def test_evaluator_emits_base_and_subset_without_duplicate_wager():
    result = evaluate_systems(
        [game(week=1, away_spread=-14.0, home_spread=14.0)],
        evaluated_at=NOW,
        requested_date=date(2026, 8, 29),
    )
    ids = {signal.system_id for signal in result.signals}
    assert "FOOTBALL_2_CFB_ROAD_FAVORITE_FADE" in ids
    assert "FOOTBALL_2B_CFB_LARGE_ROAD_FAVORITE_FADE" in ids
    grouped = deduplicate_wagers(result.signals)
    road_fade = next(w for w in grouped if w.selection == "Home +14")
    assert road_fade.supporting_system_ids == [
        "FOOTBALL_2_CFB_ROAD_FAVORITE_FADE",
        "FOOTBALL_2B_CFB_LARGE_ROAD_FAVORITE_FADE",
    ]


def test_evaluator_respects_strict_weather_boundaries_and_groups_wind_unders():
    result = evaluate_systems(
        [game(weather_applicable=True, temperature_f=85.0, sustained_wind_mph=18.0, total=48.5)],
        evaluated_at=NOW,
        requested_date=date(2026, 8, 29),
    )
    ids = {signal.system_id for signal in result.signals}
    assert "FOOTBALL_4_CFB_HOT_LOW_WIND_OVER" not in ids
    assert "FOOTBALL_9_CFB_WIND_15_PLUS_UNDER" in ids
    assert "FOOTBALL_10_CFB_WIND_18_PLUS_UNDER" in ids
    wind_wager = next(w for w in deduplicate_wagers(result.signals) if w.selection == "Under 48.5")
    assert len(wind_wager.supporting_system_ids) == 2


def test_total_signal_quotes_coral33_not_the_market_best_price():
    """The page prices what can be placed, so pinnacle's -108 never shows."""
    result = evaluate_systems(
        [game(home_spread=-41.0, away_spread=41.0, total=55.5,
              total_over_price=-108, total_over_book="pinnacle",
              total_over_placement=-115)],
        evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    signal = next(s for s in result.signals if s.system_id == "FOOTBALL_5_CFB_41_PLUS_FAVORITE_OVER")
    assert signal.price_american == -115
    assert signal.book == "coral33"


def test_cfb_systems_do_not_qualify_unconfirmed_fbs_games():
    """An FCS or unmatched event must not create an FBS-system wager."""
    result = evaluate_systems(
        [game(is_fbs_game=None, home_spread=-41.0, away_spread=41.0, total=57.5)],
        evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    assert not any(
        signal.system_id == "FOOTBALL_5_CFB_41_PLUS_FAVORITE_OVER"
        for signal in result.signals
    )
    evaluation = next(
        item for item in result.evaluations
        if item.system_id == "FOOTBALL_5_CFB_41_PLUS_FAVORITE_OVER"
    )
    assert evaluation.status == "unable_to_evaluate"
    assert "is_fbs_game" in evaluation.missing_fields


def test_cfb_systems_treat_confirmed_fcs_game_as_no_match():
    result = evaluate_systems(
        [game(is_fbs_game=False, home_spread=-41.0, away_spread=41.0, total=57.5)],
        evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    assert not any(signal.sport == "ncaaf" for signal in result.signals)
    evaluation = next(
        item for item in result.evaluations
        if item.system_id == "FOOTBALL_5_CFB_41_PLUS_FAVORITE_OVER"
    )
    assert evaluation.status == "no_match"


def test_missing_fields_are_unable_not_no_match_and_incomplete_rules_disabled():
    result = evaluate_systems(
        [game()], evaluated_at=NOW, requested_date=date(2026, 8, 29)
    )
    football_one = next(
        item for item in result.evaluations
        if item.system_id == "FOOTBALL_1_CFB_MASSIVE_HOME_FAVORITE"
    )
    football_eight = next(
        item for item in result.evaluations
        if item.system_id == "FOOTBALL_8_CFB_MAC_BOWL_FADE_TBD"
    )
    assert football_one.status == "unable_to_evaluate"
    assert football_one.missing_fields == ["home_spread", "week"]
    assert football_eight.status == "disabled"


def test_started_games_are_excluded_before_rule_evaluation():
    started = game(week=1, home_spread=-40.0, away_spread=40.0)
    started.commence_time = datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)
    result = evaluate_systems(
        [started], evaluated_at=NOW, requested_date=date(2026, 8, 29)
    )
    assert result.signals == []


def test_nfl_week_system_does_not_apply_to_preseason_week_one():
    nfl_game = game(
        is_fbs_game=None, season_type="preseason", week=1,
        away_spread=4.0, away_made_playoffs_previous_season=False,
    )
    nfl_game.sport = "nfl"
    result = evaluate_systems(
        [nfl_game], evaluated_at=NOW, requested_date=date(2026, 8, 29)
    )
    assert not any(
        signal.system_id == "FOOTBALL_12_NFL_WEEK1_ROAD_DOG_NO_PLAYOFFS"
        for signal in result.signals
    )


def test_week_one_debut_team_qualifies_against_opponent_with_one_game_played():
    result = evaluate_systems(
        [game(
            week=1,
            home_spread=4.5,
            away_spread=-4.5,
            home_games_played=0,
            away_games_played=1,
            home_spread_price=-108,
            home_spread_book="pinnacle",
            home_spread_placement=-112,
        )],
        evaluated_at=NOW,
        requested_date=date(2026, 8, 29),
    )

    signal = next(
        signal for signal in result.signals
        if signal.system_id == "FOOTBALL_14_CFB_WEEK1_REST_EXPERIENCE_ADVANTAGE"
    )
    assert signal.selection == "Home +4.5"
    assert signal.market_line == 4.5
    assert signal.price_american == -112
    assert signal.book == "coral33"


def test_week_one_rest_experience_rule_works_with_away_team_as_debut_team():
    result = evaluate_systems(
        [game(
            week=1,
            home_spread=-3.0,
            away_spread=3.0,
            home_games_played=1,
            away_games_played=0,
        )],
        evaluated_at=NOW,
        requested_date=date(2026, 8, 29),
    )
    signal = next(
        signal for signal in result.signals
        if signal.system_id == "FOOTBALL_14_CFB_WEEK1_REST_EXPERIENCE_ADVANTAGE"
    )
    assert signal.selection == "Away +3"


def test_week_one_rest_experience_rule_rejects_wrong_week_or_game_counts():
    for candidate in (
        game(week=0, home_spread=3, away_spread=-3,
             home_games_played=0, away_games_played=1),
        game(week=2, home_spread=3, away_spread=-3,
             home_games_played=0, away_games_played=1),
        game(week=1, home_spread=3, away_spread=-3,
             home_games_played=0, away_games_played=0),
        game(week=1, home_spread=3, away_spread=-3,
             home_games_played=1, away_games_played=1),
    ):
        result = evaluate_systems(
            [candidate], evaluated_at=NOW,
            requested_date=date(2026, 8, 29),
        )
        assert not any(
            signal.system_id
            == "FOOTBALL_14_CFB_WEEK1_REST_EXPERIENCE_ADVANTAGE"
            for signal in result.signals
        )


def test_week_one_rest_experience_rule_reports_missing_games_played_context():
    result = evaluate_systems(
        [game(week=1, home_spread=3, away_spread=-3)],
        evaluated_at=NOW,
        requested_date=date(2026, 8, 29),
    )
    evaluation = next(
        item for item in result.evaluations
        if item.system_id == "FOOTBALL_14_CFB_WEEK1_REST_EXPERIENCE_ADVANTAGE"
    )
    assert evaluation.status == "unable_to_evaluate"
    assert evaluation.missing_fields == [
        "away_games_played", "home_games_played"
    ]


def test_sweep_wednesday_qualifies_outside_july_and_august():
    evaluated_at = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)
    mlb_game = EvaluationGame(
        event_id="phillies-diamondbacks",
        sport="mlb",
        home_team="Arizona Diamondbacks",
        away_team="Philadelphia Phillies",
        commence_time=datetime(2026, 9, 3, 1, 40, tzinfo=timezone.utc),
        data_timestamp=evaluated_at,
        context={
            "day_of_week": "Wednesday",
            "series_game_number": 3,
            "series_length": 3,
            "home_series_losses": 2,
            "away_series_losses": 0,
            "home_moneyline": 120,
            "away_moneyline": -130,
        },
    )

    result = evaluate_systems(
        [mlb_game],
        evaluated_at=evaluated_at,
        requested_date=date(2026, 9, 2),
    )

    signal = next(
        signal
        for signal in result.signals
        if signal.system_id == "MLB_12_SWEEP_WEDNESDAY"
    )
    assert signal.selection == "Arizona Diamondbacks"


def _nfl_game(**context):
    return EvaluationGame(
        event_id="nfl-1", sport="nfl", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW, context=context,
    )


def _evaluation(result, short_id):
    return next(e for e in result.evaluations if e.short_id == short_id)


def test_one_game_with_missing_context_does_not_blank_the_whole_system():
    """A single unresolved game must not mask a real verdict on the rest.

    Regression: one unmatched ESPN event (odds "Albany" vs ESPN "UAlbany")
    left is_fbs_game/week None, which flipped six otherwise-clean systems to
    "unable to evaluate" even though every other game evaluated fine.
    """
    clean = game(week=1, home_spread=-3.0, away_spread=3.0)
    clean.event_id = "clean"
    blank = EvaluationGame(
        event_id="blank", sport="ncaaf", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW, context={},
    )
    result = evaluate_systems(
        [clean, blank], evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    football_1 = _evaluation(result, "Football 1")
    assert football_1.status == "no_match"
    assert football_1.evaluated_games == 1
    assert football_1.skipped_games == 1
    assert football_1.missing_fields  # the gap is still reported, not hidden


def test_system_is_unevaluable_only_when_no_game_could_be_evaluated():
    blank = EvaluationGame(
        event_id="blank", sport="ncaaf", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW, context={},
    )
    result = evaluate_systems(
        [blank], evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    football_1 = _evaluation(result, "Football 1")
    assert football_1.status == "unable_to_evaluate"
    assert football_1.evaluated_games == 0
    assert football_1.skipped_games == 1


def test_an_empty_slate_reports_no_slate_not_a_data_failure():
    """No NFL games today is a calendar fact, not missing context."""
    result = evaluate_systems(
        [game(week=1, home_spread=-3.0, away_spread=3.0)],
        evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    football_6 = _evaluation(result, "Football 6")
    assert football_6.status == "no_slate"
    assert football_6.missing_fields == []
    assert football_6.skipped_games == 0


def test_no_slate_is_distinct_from_a_slate_we_ruled_out():
    """An all-FCS slate is a confirmed non-answer; an empty one is no slate."""
    fcs = EvaluationGame(
        event_id="fcs", sport="ncaaf", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW, context={"is_fbs_game": False},
    )
    result = evaluate_systems([fcs], evaluated_at=NOW, requested_date=date(2026, 8, 29))
    assert _evaluation(result, "Football 1").status == "no_match"
    assert _evaluation(result, "Football 6").status == "no_slate"


def test_a_qualifying_match_survives_a_sibling_game_with_gaps():
    hit = game(week=1, home_spread=-40.0, away_spread=40.0)
    hit.event_id = "hit"
    blank = EvaluationGame(
        event_id="blank", sport="ncaaf", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW, context={},
    )
    result = evaluate_systems(
        [hit, blank], evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    football_1 = _evaluation(result, "Football 1")
    assert football_1.status == "qualified"
    assert football_1.match_count == 1
    assert football_1.skipped_games == 1


def test_a_selection_coral33_does_not_offer_carries_no_price():
    """No Coral33 line means no price shown — never a substitute from
    another book. The signal itself still stands; only the quote is absent."""
    result = evaluate_systems(
        [game(home_spread=-41.0, away_spread=41.0, total=55.5,
              total_over_price=-108, total_over_book="pinnacle")],
        evaluated_at=NOW, requested_date=date(2026, 8, 29),
    )
    signal = next(s for s in result.signals if s.system_id == "FOOTBALL_5_CFB_41_PLUS_FAVORITE_OVER")
    assert signal.price_american is None
    assert signal.book is None


def test_rules_still_gate_on_the_market_price_not_coral33s():
    """MLB rules read market consensus; Coral33 pricing is display only.

    Coral33 covers a minority of the slate, so gating qualification on it
    would silently drop most MLB signals.
    """
    mlb = EvaluationGame(
        event_id="mlb-1", sport="mlb", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        data_timestamp=NOW,
        context={
            "away_moneyline": -140, "home_moneyline": 120,
            "away_previous_runs_scored": 0,
            # Coral33 is not offering this game at all.
        },
    )
    result = evaluate_systems([mlb], evaluated_at=NOW, requested_date=date(2026, 8, 29))
    signal = next(s for s in result.signals if s.system_id == "MLB_10_ROAD_FAVORITE_AFTER_SHUTOUT_LOSS")
    assert signal.price_american is None
    assert signal.book is None
