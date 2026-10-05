"""Context builders for the VSiN systems added 2026-09-10.

Each builder is a pure function over an ESPN/MLB payload, so these tests
exercise the real parsing with synthetic payloads and no network.
"""
from datetime import datetime, timezone

from server.systems.context import (
    college_points_allowed_context,
    college_previous_game_context,
    college_rankings_context,
    nfl_prior_season_context,
)
from server.systems.models import EvaluationGame


KICK = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)


def game(home="Georgia Bulldogs", away="Western Kentucky Hilltoppers", sport="ncaaf"):
    return EvaluationGame(
        event_id="e1", sport=sport, home_team=home, away_team=away,
        commence_time=KICK, data_timestamp=KICK, context={},
    )


def completed(date_str, home_id, home_pts, away_id, away_pts, home_name="H",
              away_name="A", season_type=2):
    return {
        "date": date_str,
        "season": {"type": season_type},
        "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "score": str(home_pts),
             "team": {"id": str(home_id), "displayName": home_name}},
            {"homeAway": "away", "score": str(away_pts),
             "team": {"id": str(away_id), "displayName": away_name}},
        ]}],
    }


# --- AP poll ----------------------------------------------------------

def test_rankings_context_marks_each_side_ranked_or_not():
    payload = {"rankings": [
        {"name": "AFCA Coaches Poll", "type": "usa", "ranks": [
            {"current": 1, "team": {"id": "333"}}]},
        {"name": "AP Top 25", "type": "ap", "ranks": [
            {"current": 2, "team": {"id": "61"}},
            {"current": 14, "team": {"id": "99"}}]},
    ]}
    additions = {"e1": {"home_espn_team_id": 61, "away_espn_team_id": 98}}
    values = college_rankings_context([game()], additions, payload)
    assert values["e1"] == {
        "home_is_ranked": True, "home_ap_rank": 2,
        "away_is_ranked": False, "away_ap_rank": None,
    }


def test_rankings_context_ignores_the_coaches_poll():
    payload = {"rankings": [
        {"name": "AFCA Coaches Poll", "type": "usa", "ranks": [
            {"current": 1, "team": {"id": "61"}}]},
        {"name": "AP Top 25", "type": "ap", "ranks": []},
    ]}
    additions = {"e1": {"home_espn_team_id": 61, "away_espn_team_id": 98}}
    assert college_rankings_context([game()], additions, payload)["e1"]["home_is_ranked"] is False


def test_rankings_context_reports_unknown_team_ids_as_unranked():
    """A team the scoreboard never matched is absent, not secretly ranked."""
    payload = {"rankings": [{"name": "AP Top 25", "type": "ap", "ranks": [
        {"current": 2, "team": {"id": "61"}}]}]}
    values = college_rankings_context([game()], {"e1": {}}, payload)
    assert values["e1"]["home_is_ranked"] is False


# --- season-to-date points allowed ------------------------------------

def test_points_allowed_context_averages_over_completed_games():
    payload = {"events": [
        completed("2026-08-30T23:00Z", 61, 35, 2000, 21, "Georgia Bulldogs", "Opp One"),
        completed("2026-09-06T23:00Z", 3000, 10, 61, 49, "Opp Two", "Georgia Bulldogs"),
    ]}
    values = college_points_allowed_context([game()], payload)
    assert values["e1"]["home_ppg_allowed"] == 15.5


def test_points_allowed_context_is_none_before_a_team_plays():
    payload = {"events": []}
    values = college_points_allowed_context([game()], payload)
    assert values["e1"]["home_ppg_allowed"] is None


def test_points_allowed_context_ignores_games_after_kickoff():
    payload = {"events": [
        completed("2026-08-30T23:00Z", 61, 35, 2000, 21, "Georgia Bulldogs", "Opp One"),
        completed("2026-09-20T23:00Z", 61, 7, 3000, 60, "Georgia Bulldogs", "Opp Two"),
    ]}
    assert college_points_allowed_context([game()], payload)["e1"]["home_ppg_allowed"] == 21.0


# --- previous-game points allowed -------------------------------------

def test_previous_game_context_now_reports_points_allowed():
    payload = {"events": [
        completed("2026-09-06T23:00Z", 61, 58, 2000, 9, "Georgia Bulldogs", "Opp One"),
    ]}
    values = college_previous_game_context([game()], payload)
    assert values["e1"]["home_previous_points"] == 58
    assert values["e1"]["home_previous_points_allowed"] == 9
    assert values["e1"]["away_previous_points_allowed"] is None


# --- NFL prior seasons ------------------------------------------------

def nfl_game():
    return EvaluationGame(
        event_id="n1", sport="nfl", home_team="Detroit Lions",
        away_team="New Orleans Saints", commence_time=KICK,
        data_timestamp=KICK, context={},
    )


def test_nfl_prior_season_context_derives_record_scoring_and_close_losses():
    prior = {"events": [
        completed("2025-09-10T23:00Z", 8, 30, 18, 24),   # DET win by 6
        completed("2025-09-17T23:00Z", 18, 20, 8, 14),   # DET loss by 6 (close)
        completed("2025-09-24T23:00Z", 8, 10, 18, 40),   # DET loss by 30
    ]}
    earlier = {"events": [
        completed("2024-09-10T23:00Z", 8, 30, 18, 24),
        completed("2024-09-17T23:00Z", 8, 30, 18, 24),
        completed("2024-09-24T23:00Z", 8, 30, 18, 24),
    ]}
    additions = {"n1": {"home_espn_team_id": 8, "away_espn_team_id": 18}}
    values = nfl_prior_season_context([nfl_game()], additions, prior, earlier)["n1"]
    assert values["home_prior_season_wins"] == 1
    assert values["home_prior_season_win_pct"] == 1 / 3
    assert values["home_prior_season_ppg"] == 18.0
    assert values["home_prior_season_ppg_allowed"] == 28.0
    assert values["home_prior_season_close_losses"] == 1
    # Three wins the season before, one now: a two-win collapse.
    assert values["home_prior_season_win_change"] == -2


def test_nfl_prior_season_context_excludes_the_postseason():
    """ESPN's seasontype filter is ignored on a date range, so the parser
    has to drop playoff games itself -- otherwise a deep run inflates a
    team's win total past the 17 the systems are defined against."""
    prior = {"events": [
        completed("2025-09-10T23:00Z", 8, 30, 18, 24),
        completed("2026-01-11T23:00Z", 8, 31, 18, 17, season_type=3),
    ]}
    additions = {"n1": {"home_espn_team_id": 8, "away_espn_team_id": 18}}
    values = nfl_prior_season_context(
        [nfl_game()], additions, prior, {"events": []}
    )["n1"]
    assert values["home_prior_season_wins"] == 1


def test_nfl_prior_season_context_is_none_for_an_unmatched_team():
    additions = {"n1": {"home_espn_team_id": None, "away_espn_team_id": None}}
    values = nfl_prior_season_context(
        [nfl_game()], additions, {"events": []}, {"events": []}
    )["n1"]
    assert values["home_prior_season_wins"] is None
    assert values["away_prior_season_ppg"] is None


# --- NFL conference ---------------------------------------------------

def test_nfl_scoreboard_context_flags_a_non_conference_game():
    from server.systems.context import nfl_scoreboard_context

    payload = {"events": [{
        "id": "401",
        "date": "2026-09-12T23:00Z",
        "season": {"type": 2},
        "week": {"number": 1},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "8", "displayName": "Detroit Lions"}},
            {"homeAway": "away", "team": {"id": "18", "displayName": "New Orleans Saints"}},
        ]}],
    }]}
    values = nfl_scoreboard_context(
        [nfl_game()], payload,
        division_by_team_id={8: "10", 18: "12"},
        prior_playoff_team_ids=set(),
        conference_by_team_id={8: "8", 18: "7"},
    )["n1"]
    assert values["is_conference_game"] is False
    assert values["is_divisional"] is False


def test_nfl_scoreboard_context_reports_unknown_conference_as_none():
    from server.systems.context import nfl_scoreboard_context

    payload = {"events": [{
        "id": "401",
        "date": "2026-09-12T23:00Z",
        "season": {"type": 2},
        "week": {"number": 1},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "8", "displayName": "Detroit Lions"}},
            {"homeAway": "away", "team": {"id": "18", "displayName": "New Orleans Saints"}},
        ]}],
    }]}
    values = nfl_scoreboard_context(
        [nfl_game()], payload,
        division_by_team_id={8: "10", 18: "12"},
        prior_playoff_team_ids=set(),
        conference_by_team_id={8: "8"},
    )["n1"]
    assert values["is_conference_game"] is None


# --- MLB road trips ---------------------------------------------------

def mlb_game():
    return EvaluationGame(
        event_id="m1", sport="mlb", home_team="Atlanta Braves",
        away_team="Tampa Bay Rays", commence_time=KICK,
        data_timestamp=KICK, context={},
    )


def scheduled(date_str, home, away):
    return {"officialDate": date_str, "teams": {
        "home": {"team": {"name": home}}, "away": {"team": {"name": away}}}}


def test_road_trip_ends_when_the_next_game_is_at_home():
    from datetime import date as date_type
    from server.systems.context import mlb_road_trip_context

    schedule = [
        scheduled("2026-09-12", "Atlanta Braves", "Tampa Bay Rays"),
        scheduled("2026-09-13", "Tampa Bay Rays", "Boston Red Sox"),
    ]
    values = mlb_road_trip_context([mlb_game()], schedule, date_type(2026, 9, 12))["m1"]
    assert values["away_ends_road_trip"] is True
    # The host is not on a road trip at all.
    assert values["home_ends_road_trip"] is False


def test_road_trip_continues_when_the_next_game_is_also_away():
    from datetime import date as date_type
    from server.systems.context import mlb_road_trip_context

    schedule = [
        scheduled("2026-09-12", "Atlanta Braves", "Tampa Bay Rays"),
        scheduled("2026-09-13", "Miami Marlins", "Tampa Bay Rays"),
    ]
    values = mlb_road_trip_context([mlb_game()], schedule, date_type(2026, 9, 12))["m1"]
    assert values["away_ends_road_trip"] is False


def test_road_trip_is_unknown_when_the_schedule_window_has_no_next_game():
    from datetime import date as date_type
    from server.systems.context import mlb_road_trip_context

    schedule = [scheduled("2026-09-12", "Atlanta Braves", "Tampa Bay Rays")]
    values = mlb_road_trip_context([mlb_game()], schedule, date_type(2026, 9, 12))["m1"]
    assert values["away_ends_road_trip"] is None
