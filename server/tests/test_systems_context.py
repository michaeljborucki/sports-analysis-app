from datetime import date, datetime, timedelta, timezone

import pytest

from server.odds.cache import OddsCache, init_schema_on_path
from server.systems.context import (
    build_evaluation_games,
    college_games_played_context,
    college_team_directory_context,
    football_scoreboard_context,
    football_schedule_enricher,
    resolve_mlb_team_record,
    nfl_scoreboard_context,
    scoreboard_date_key,
    select_geocode_result,
    weather_forecast_available,
    select_kickoff_weather,
    was_swept_in_previous_home_series,
)
from server.systems.models import EvaluationGame
from server.systems.context_cache import SystemContextCache


@pytest.mark.asyncio
async def test_context_builds_future_same_day_game_and_current_main_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    rows = []
    for market, outcome, point, price in (
        ("h2h", "Arizona Diamondbacks", 0, -125),
        ("h2h", "Colorado Rockies", 0, 110),
        ("spreads", "Arizona Diamondbacks", -1.5, 105),
        ("spreads", "Colorado Rockies", 1.5, -115),
        ("totals", "Over", 8.5, -105),
        ("totals", "Under", 8.5, -105),
    ):
        rows.append({
            "event_id": "e1", "sport_key": "mlb",
            "home_team": "Colorado Rockies", "away_team": "Arizona Diamondbacks",
            "commence_time": "2026-08-30T00:10:00+00:00",
            "bookmaker_key": "pinnacle", "market_key": market,
            "outcome_name": outcome, "outcome_point": point,
            "price_american": price, "fetched_at": "2026-08-29T16:00:00+00:00",
        })
    cache.upsert(rows)

    async def enrich(games, requested_date):
        return {"e1": {"home_win_pct": .4}}, []

    games, warnings = await build_evaluation_games(
        cache, date(2026, 8, 29), "America/Denver",
        datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc), enrich=enrich,
    )
    assert warnings == []
    assert len(games) == 1
    assert games[0].context["away_moneyline"] == -125
    assert games[0].context["home_spread"] == 1.5
    assert games[0].context["away_spread_price"] == 105
    assert games[0].context["total"] == 8.5
    assert games[0].context["total_over_price"] == -105
    assert games[0].context["home_win_pct"] == .4


@pytest.mark.asyncio
async def test_context_builds_and_enriches_all_games_after_date_in_one_batch(tmp_path, monkeypatch):
    """Upcoming must include every later slate without one network pass per date."""
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)
    for event_id, commence_time in (
        ("day-after", "2026-08-31T14:00:00+00:00"),
        ("next-week", "2026-09-06T20:00:00+00:00"),
    ):
        cache.upsert([{
            "event_id": event_id, "sport_key": "nfl",
            "home_team": f"{event_id} home", "away_team": f"{event_id} away",
            "commence_time": commence_time, "bookmaker_key": "pinnacle",
            "market_key": "h2h", "outcome_name": f"{event_id} home",
            "outcome_point": 0, "price_american": -110,
            "fetched_at": "2026-08-29T16:00:00+00:00",
        }])
    enriched_dates = []

    async def enrich(games, requested_date):
        enriched_dates.append(requested_date)
        return {game.event_id: {"enriched_for": requested_date.isoformat()} for game in games}, []

    games, warnings = await build_evaluation_games(
        cache, date(2026, 8, 31), "America/Denver",
        datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
        enrich=enrich, include_after=True,
    )

    assert warnings == []
    assert [game.event_id for game in games] == ["day-after", "next-week"]
    assert enriched_dates == [date(2026, 8, 31)]
    assert games[1].context["enriched_for"] == "2026-08-31"


def test_scoreboard_date_key_batches_a_multi_week_slate_into_one_range():
    games = [
        EvaluationGame(
            event_id="first", sport="nfl", home_team="A", away_team="B",
            commence_time=datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc),
            data_timestamp=datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
        ),
        EvaluationGame(
            event_id="last", sport="nfl", home_team="C", away_team="D",
            commence_time=datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc),
            data_timestamp=datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
        ),
    ]
    assert scoreboard_date_key(games, date(2026, 8, 31)) == "20260903-20260913"


def test_weather_context_skips_games_beyond_the_forecast_window():
    assert weather_forecast_available(date(2026, 9, 15), date(2026, 8, 31)) is True
    assert weather_forecast_available(date(2026, 9, 17), date(2026, 8, 31)) is False


@pytest.mark.asyncio
async def test_context_provider_failure_is_warning_not_endpoint_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)

    async def broken(games, requested_date):
        raise RuntimeError("stats unavailable")

    games, warnings = await build_evaluation_games(
        cache, date(2026, 8, 29), "America/Denver",
        datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc), enrich=broken,
    )
    assert games == []
    assert warnings == ["Context provider unavailable: stats unavailable"]


@pytest.mark.asyncio
async def test_context_provider_failure_with_blank_message_names_exception(tmp_path, monkeypatch):
    """A timeout must not render the operator-facing warning as an empty message."""
    monkeypatch.setenv("ODDS_SOURCE", "native")
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    cache = OddsCache(path)

    async def timed_out(games, requested_date):
        raise TimeoutError()

    _, warnings = await build_evaluation_games(
        cache, date(2026, 8, 29), "America/Denver",
        datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc), enrich=timed_out,
    )
    assert warnings == ["Context provider unavailable: TimeoutError"]


@pytest.mark.asyncio
async def test_context_reads_only_the_three_system_sports():
    class CacheSpy:
        def __init__(self):
            self.sports = []

        def all_current_markets(self, sport_key, market_keys):
            assert sport_key is not None
            assert market_keys == ("h2h", "spreads", "totals")
            self.sports.append(sport_key)
            return []

    cache = CacheSpy()

    async def no_context(games, requested_date):
        return {}, []

    await build_evaluation_games(
        cache, date(2026, 8, 29), "America/Denver",
        datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc), enrich=no_context,
    )
    assert cache.sports == ["mlb", "ncaaf", "nfl"]


def test_football_scoreboard_confirms_fbs_week_and_conference_classes():
    """A matched ESPN FBS event supplies the metadata opening-week rules require."""
    game = EvaluationGame(
        event_id="odds-1", sport="ncaaf", home_team="USC Trojans",
        away_team="San Jose State Spartans",
        commence_time=datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
    )
    payload = {
        "week": {"number": 1},
        "events": [{"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"displayName": "USC Trojans", "conferenceId": "5"}},
            {"homeAway": "away", "team": {"displayName": "San José State Spartans", "conferenceId": "17"}},
        ]}]}],
    }
    result = football_scoreboard_context([game], payload)
    assert result["odds-1"] == {
        "is_fbs_game": True,
        "week": 1,
        "home_conference_class": "p4",
        "away_conference_class": "g5",
    }


def test_college_games_played_counts_only_completed_games_before_kickoff():
    game = EvaluationGame(
        event_id="week-1", sport="ncaaf", home_team="Ohio State Buckeyes",
        away_team="Texas Longhorns",
        commence_time=datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc),
    )
    history = {"events": [
        {
            "date": "2026-08-29T16:00:00Z",
            "status": {"type": {"completed": True}},
            "competitions": [{"competitors": [
                {"team": {"displayName": "Texas Longhorns"}},
                {"team": {"displayName": "Rice Owls"}},
            ]}],
        },
        {
            "date": "2026-09-04T16:00:00Z",
            "status": {"type": {"completed": False}},
            "competitions": [{"competitors": [
                {"team": {"displayName": "Ohio State Buckeyes"}},
                {"team": {"displayName": "Akron Zips"}},
            ]}],
        },
        {
            "date": "2026-09-06T16:00:00Z",
            "status": {"type": {"completed": True}},
            "competitions": [{"competitors": [
                {"team": {"displayName": "Ohio State Buckeyes"}},
                {"team": {"displayName": "Toledo Rockets"}},
            ]}],
        },
    ]}

    assert college_games_played_context([game], history) == {
        "week-1": {"home_games_played": 0, "away_games_played": 1}
    }


@pytest.mark.asyncio
async def test_football_enricher_adds_cached_college_games_played_context(tmp_path):
    requested = date(2026, 9, 3)
    game = EvaluationGame(
        event_id="week-1", sport="ncaaf", home_team="Ohio State Buckeyes",
        away_team="Texas Longhorns",
        commence_time=datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc),
    )
    upcoming = {"week": {"number": 1}, "events": [{
        "id": "espn-week-1", "week": {"number": 1},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {
                "displayName": "Ohio State Buckeyes", "conferenceId": "5"}},
            {"homeAway": "away", "team": {
                "displayName": "Texas Longhorns", "conferenceId": "8"}},
        ]}],
    }]}
    history = {"events": [{
        "date": "2026-08-29T16:00:00Z",
        "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"team": {"displayName": "Texas Longhorns"}},
            {"team": {"displayName": "Rice Owls"}},
        ]}],
    }]}
    context_cache = SystemContextCache(tmp_path / "context.db")

    async def upcoming_loader():
        return upcoming

    async def history_loader():
        return history

    await context_cache.get_or_refresh(
        "espn", "ncaaf:scoreboard:20260905", requested,
        timedelta(minutes=15), upcoming_loader,
    )
    await context_cache.get_or_refresh(
        "espn", "ncaaf:season-results:2026:20260905", requested,
        timedelta(minutes=15), history_loader,
    )

    additions, warnings = await football_schedule_enricher(
        [game], requested, context_cache=context_cache,
    )

    assert warnings == []
    assert additions["week-1"]["home_games_played"] == 0
    assert additions["week-1"]["away_games_played"] == 1


def test_mlb_standings_join_uses_team_id_not_short_display_name():
    """Odds' full team name must resolve a standings row named only 'Yankees'."""
    record = resolve_mlb_team_record(
        "New York Yankees",
        {"newyorkyankees": 147},
        {147: {"win_pct": .583, "division_id": 201}},
    )
    assert record == {"win_pct": .583, "division_id": 201}


def test_previous_completed_home_series_sweep_is_derived_from_history():
    history = [
        {"opponent": "dodgers", "was_home": True, "won": False, "series_game_number": 1, "series_length": 3},
        {"opponent": "dodgers", "was_home": True, "won": False, "series_game_number": 2, "series_length": 3},
        {"opponent": "dodgers", "was_home": True, "won": False, "series_game_number": 3, "series_length": 3},
    ]
    assert was_swept_in_previous_home_series(history) is True
    history[-1]["won"] = True
    assert was_swept_in_previous_home_series(history) is False


def test_nfl_scoreboard_derives_regular_week_division_and_prior_playoffs():
    game = EvaluationGame(
        event_id="nfl-odds", sport="nfl", home_team="New York Giants",
        away_team="Dallas Cowboys",
        commence_time=datetime(2026, 9, 13, 20, 25, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 9, 13, 16, 0, tzinfo=timezone.utc),
    )
    payload = {"events": [{
        "id": "espn-1", "season": {"type": 2}, "week": {"number": 1},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "19", "displayName": "New York Giants"}},
            {"homeAway": "away", "team": {"id": "6", "displayName": "Dallas Cowboys"}},
        ]}],
    }]}
    result = nfl_scoreboard_context([game], payload, {19: "nfc-east", 6: "nfc-east"}, {6})
    assert result["nfl-odds"]["season_type"] == "regular"
    assert result["nfl-odds"]["week"] == 1
    assert result["nfl-odds"]["is_divisional"] is True
    assert result["nfl-odds"]["away_made_playoffs_previous_season"] is True


def test_weather_selects_hour_nearest_kickoff_and_uses_sustained_wind():
    hourly = {
        "time": ["2026-08-29T22:00", "2026-08-29T23:00", "2026-08-30T00:00"],
        "temperature_2m": [84.0, 87.0, 82.0],
        "wind_speed_10m": [4.0, 6.5, 8.0],
        "wind_gusts_10m": [10.0, 19.0, 25.0],
    }
    result = select_kickoff_weather(
        hourly, datetime(2026, 8, 29, 23, 20, tzinfo=timezone.utc)
    )
    assert result == {"temperature_f": 87.0, "sustained_wind_mph": 6.5}


def test_college_team_directory_marks_two_fcs_teams_not_fbs():
    game = EvaluationGame(
        event_id="fcs", sport="ncaaf", home_team="South Dakota State Jackrabbits",
        away_team="Stetson Hatters",
        commence_time=datetime(2026, 8, 29, 23, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
    )
    directory = {"South Dakota State Jackrabbits": 2571, "Stetson Hatters": 56}
    details = {
        2571: {"conference_id": 21, "parent_group_id": 81},
        56: {"conference_id": 28, "parent_group_id": 81},
    }
    assert college_team_directory_context([game], directory, details, week=1) == {
        "fcs": {"is_fbs_game": False, "week": 1,
                "home_conference_class": None, "away_conference_class": None}
    }


def test_college_team_directory_handles_known_provider_name_variants():
    game = EvaluationGame(
        event_id="alias", sport="ncaaf", home_team="McNeese State Cowboys",
        away_team="Citadel Bulldogs",
        commence_time=datetime(2026, 8, 29, 23, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc),
    )
    result = college_team_directory_context(
        [game], {"McNeese Cowboys": 2377, "The Citadel Bulldogs": 2643},
        {2377: {"conference_id": 31, "parent_group_id": 81},
         2643: {"conference_id": 20, "parent_group_id": 81}}, week=1,
    )
    assert result["alias"]["is_fbs_game"] is False


def test_scoreboard_matches_a_feed_name_that_omits_the_u_prefix():
    """Odds says "Albany"; ESPN says "UAlbany Great Danes" — must still match.

    A miss here blanks is_fbs_game/week/venue for the game, which used to
    flip six systems to "unable to evaluate" on an otherwise clean slate.
    """
    game = EvaluationGame(
        event_id="odds-albany", sport="ncaaf", home_team="Buffalo Bulls",
        away_team="Albany",
        commence_time=datetime(2026, 9, 3, 23, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc),
    )
    payload = {
        "week": {"number": 1},
        "events": [{"competitions": [{
            "venue": {"id": "3965", "indoor": False,
                      "address": {"city": "Buffalo", "state": "NY"}},
            "competitors": [
                {"homeAway": "home", "team": {
                    "id": "2084", "displayName": "Buffalo Bulls",
                    "location": "Buffalo", "conferenceId": "15"}},
                {"homeAway": "away", "team": {
                    "id": "399", "displayName": "UAlbany Great Danes",
                    "location": "UAlbany", "conferenceId": "48"}},
            ]}]}],
    }
    result = football_scoreboard_context([game], payload)
    assert result["odds-albany"]["week"] == 1
    assert result["odds-albany"]["is_fbs_game"] is False
    assert result["odds-albany"]["venue"]["address"]["city"] == "Buffalo"


def _hit(name, admin1, lat, lon, population=0):
    return {"name": name, "admin1": admin1, "latitude": lat,
            "longitude": lon, "population": population}


def test_geocode_joins_on_the_full_state_name_not_the_two_letter_code():
    """ESPN sends "MO"; Open-Meteo answers "Missouri".

    Comparing those directly never matched, so Missouri's stadium silently
    took Columbia, SOUTH CAROLINA's weather into live wind/temperature rules.
    """
    results = [
        _hit("Columbia", "South Carolina", 34.00071, -81.03481, 137300),
        _hit("Columbia", "Missouri", 38.95171, -92.33407, 108500),
    ]
    assert select_geocode_result(results, "Columbia", "MO") == {
        "latitude": 38.95171, "longitude": -92.33407,
    }


def test_geocode_refuses_rather_than_returning_the_wrong_city():
    results = [_hit("Newark", "New Jersey", 40.73566, -74.17237, 311000)]
    assert select_geocode_result(results, "Newark", "DE") == {}


def test_geocode_prefers_an_exact_city_name_within_the_right_state():
    results = [
        _hit("Cartersville", "Georgia", 34.16533, -84.80231, 23000),
        _hit("Kennesaw", "Georgia", 34.02343, -84.61549, 34000),
    ]
    assert select_geocode_result(results, "Kennesaw", "GA")["latitude"] == 34.02343


def test_geocode_without_a_state_falls_back_to_the_most_prominent_match():
    results = [_hit("Toronto", None, 43.70011, -79.4163, 2600000)]
    assert select_geocode_result(results, "Toronto", None)["latitude"] == 43.70011


def test_forecast_window_is_anchored_on_today_not_the_requested_slate_date():
    """`upcoming` shifts the requested date forward; the provider's does not."""
    today = date(2026, 9, 3)
    assert weather_forecast_available(date(2026, 9, 18), today) is True
    assert weather_forecast_available(date(2026, 9, 19), today) is False


def test_scoreboard_date_key_uses_espns_eastern_date_not_utc():
    """An 8pm ET kickoff is already tomorrow in UTC; ESPN files it today.

    Reading the UTC date asks ESPN for the wrong day once the afternoon
    games drop off the slate, which loses every venue and blanks the
    weather systems.
    """
    night_game = EvaluationGame(
        event_id="night", sport="ncaaf",
        home_team="Georgia Tech", away_team="Colorado",
        commence_time=datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc),
        data_timestamp=datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc),
    )
    assert scoreboard_date_key([night_game], date(2026, 9, 3)) == "20260903"


def test_kickoff_weather_skips_null_hours_from_the_provider():
    """Open-Meteo returns nulls at the edge of its forecast range.

    float(None) used to raise straight out of the enricher, which blanked
    the context for EVERY football game, not just the one bad forecast.
    """
    hourly = {
        "time": ["2026-09-18T22:00", "2026-09-18T23:00", "2026-09-19T00:00"],
        "temperature_2m": [None, 78.4, None],
        "wind_speed_10m": [None, 6.1, None],
    }
    kickoff = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
    assert select_kickoff_weather(hourly, kickoff) == {
        "temperature_f": 78.4, "sustained_wind_mph": 6.1,
    }


def test_kickoff_weather_returns_nothing_when_every_hour_is_null():
    hourly = {
        "time": ["2026-09-19T00:00"],
        "temperature_2m": [None],
        "wind_speed_10m": [None],
    }
    kickoff = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
    assert select_kickoff_weather(hourly, kickoff) == {}
