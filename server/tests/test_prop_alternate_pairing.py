from datetime import datetime, timedelta, timezone

import pytest

from server.odds.normalize import rows_to_games
from server.odds.arbitrage import scan_all_arbs
from server.odds.low_hold import scan_all_low_hold
from server.odds.ev import scan_all_ev


NOW = datetime.now(timezone.utc)


def row(market, name, book, odds, point=24.5, age=0):
    return {
        "event_id": "nfl-prop", "sport_key": "nfl",
        "home_team": "Home", "away_team": "Away",
        "commence_time": NOW + timedelta(hours=2),
        "market_key": market, "outcome_name": name,
        "bookmaker_key": book, "price_american": odds,
        "outcome_point": point, "fetched_at": NOW - timedelta(seconds=age),
        "wager_type": "both" if book == "coral33" else None,
    }


@pytest.mark.parametrize("scan", [scan_all_arbs, scan_all_low_hold])
def test_main_and_alternate_props_pair_across_books(scan):
    rows = [
        row("player_receptions", "Test Player Under", "coral33", 110),
        row("player_receptions_alternate", "Test Player Over", "draftkings", 110),
    ]
    result = scan(rows_to_games(rows, NOW))
    assert len(result) == 1
    assert result[0]["market_kind"] == "player_receptions"
    assert result[0]["point"] == 24.5
    assert {s["book"] for s in result[0]["sides"]} == {"coral33", "draftkings"}
    assert rows[1]["market_key"] == "player_receptions_alternate"


@pytest.mark.parametrize("name,point", [("Other Player Over", 24.5), ("Test Player Over", 25.5), ("Test Player Over", 25)])
def test_alternate_props_do_not_pair_different_players_or_thresholds(name, point):
    games = rows_to_games([
        row("player_receptions", "Test Player Under", "coral33", 110),
        row("player_receptions_alternate", name, "draftkings", 110, point),
    ], NOW)
    assert scan_all_arbs(games) == []
    assert scan_all_low_hold(games) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_prop_quotes_use_newest_per_book(reverse):
    rows = [
        row("player_receptions", "Test Player Over", "draftkings", 150, age=60),
        row("player_receptions_alternate", "Test Player Over", "draftkings", -120),
    ]
    games = rows_to_games(rows[::-1] if reverse else rows, NOW)
    assert len(games[0]["markets"]) == 1
    prices = games[0]["markets"][0]["outcomes"][0]["prices"]
    assert len(prices) == 1
    assert prices[0]["price_american"] == -120


def test_alternate_sharp_quotes_supply_ev_anchor_for_coral33():
    games = rows_to_games([
        row("player_receptions", "Test Player Over", "coral33", 120),
        row("player_receptions_alternate", "Test Player Over", "pinnacle", -110),
        row("player_receptions_alternate", "Test Player Under", "pinnacle", -110),
    ], NOW)
    result = scan_all_ev(games, now=NOW)
    coral = [o for o in result if o["book"] == "coral33"]
    assert len(coral) == 1
    assert coral[0]["market_kind"] == "player_receptions"
    assert coral[0]["ev_pct"] == pytest.approx(10)


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_timestamp_duplicates_prefer_main_quote(reverse):
    rows = [
        row("player_receptions", "Test Player Over", "draftkings", -120),
        row("player_receptions_alternate", "Test Player Over", "draftkings", 150),
    ]
    game = rows_to_games(rows[::-1] if reverse else rows, NOW)[0]
    prices = game["markets"][0]["outcomes"][0]["prices"]
    assert len(prices) == 1
    assert prices[0]["price_american"] == -120


def test_categorical_alternates_are_not_reinterpreted_as_over_under():
    game = rows_to_games([
        row("player_receptions", "Test Player Under", "coral33", 110),
        row("player_receptions_alternate", "Test Player Yes", "draftkings", 110),
    ], NOW)[0]
    assert len(game["markets"]) == 2
    assert scan_all_arbs([game]) == []
