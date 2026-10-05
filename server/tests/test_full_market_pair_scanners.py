"""Arbitrage and low-hold cover the same pairable market universe as EV."""

from server.odds.arbitrage import scan_all_arbs
from server.odds.low_hold import scan_all_low_hold


def _price(book: str, odds: int, point=None, wager_type=None):
    return {
        "bookmaker_key": book,
        "price_american": odds,
        "point": point,
        "wager_type": wager_type,
    }


def _outcome(name: str, *prices: dict):
    return {"outcome_name": name, "prices": list(prices)}


def _game(market_key: str, outcomes: list[dict]):
    return {
        "sport_key": "nba",
        "event_id": "event-1",
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2026-08-01T20:00:00Z",
        "markets": [{"market_key": market_key, "outcomes": outcomes}],
    }


def test_player_prop_is_scanned_for_arb_and_preserves_wager_type():
    game = _game("player_points", [
        _outcome("Jane Doe Over", _price("coral33", 110, 24.5, "both")),
        _outcome("Jane Doe Under", _price("draftkings", 110, 24.5)),
    ])

    rows = scan_all_arbs([game])

    assert len(rows) == 1
    assert rows[0]["market_kind"] == "player_points"
    assert rows[0]["point"] == 24.5
    assert rows[0]["sides"][0]["wager_type"] == "both"


def test_player_prop_is_scanned_for_low_hold():
    game = _game("player_points", [
        _outcome("Jane Doe Over", _price("coral33", -101, 24.5, "parlay")),
        _outcome("Jane Doe Under", _price("fanduel", -101, 24.5)),
    ])

    rows = scan_all_low_hold([game], max_hold_pct=2.5)

    assert len(rows) == 1
    assert rows[0]["market_kind"] == "player_points"
    assert 0 < rows[0]["hold_pct"] < 2.5


def test_arbitrage_is_included_in_low_hold_as_negative_hold():
    game = _game("player_points", [
        _outcome("Jane Doe Over", _price("coral33", 110, 24.5, "both")),
        _outcome("Jane Doe Under", _price("draftkings", 110, 24.5)),
    ])

    rows = scan_all_low_hold([game], max_hold_pct=2.5)

    assert len(rows) == 1
    assert rows[0]["hold_pct"] < 0


def test_period_spread_uses_complementary_points():
    game = _game("spreads_h1", [
        _outcome("Home", _price("draftkings", 110, -2.5)),
        _outcome("Away", _price("fanduel", 110, 2.5)),
    ])

    rows = scan_all_arbs([game])

    assert len(rows) == 1
    assert rows[0]["market_kind"] == "spreads_h1"
    assert rows[0]["point"] == 2.5


def test_three_way_market_is_scanned_for_low_hold():
    game = _game("h2h_3_way", [
        _outcome("Home", _price("draftkings", 195)),
        _outcome("Draw", _price("fanduel", 195)),
        _outcome("Away", _price("draftkings", 195)),
    ])

    rows = scan_all_low_hold([game], max_hold_pct=2.5)

    assert len(rows) == 1
    assert rows[0]["market_kind"] == "h2h_3_way"
    assert len(rows[0]["sides"]) == 3
