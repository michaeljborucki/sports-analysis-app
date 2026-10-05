from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.free_bets import build_router
from server.odds.free_bet import scan_all_free_bets


def outcome(name, book, odds, point=None):
    return {"outcome_name": name, "prices": [{
        "bookmaker_key": book, "price_american": odds, "point": point,
        "wager_type": "both" if book == "coral33" else None,
    }]}


def game(market, suffix):
    if market == "h2h":
        markets = [{"market_key": market + suffix, "outcomes": [
            outcome("Home", "coral33", 200), outcome("Away", "fanduel", -200),
        ]}]
    else:
        names = ("Home", "Away") if market == "spreads" else ("Over", "Under")
        points = (-3.5, 3.5) if market == "spreads" else (23.5, 23.5)
        markets = [
            {"market_key": market + suffix, "outcomes": [outcome(names[0], "coral33", 200, points[0])]},
            {"market_key": "alternate_" + market + suffix, "outcomes": [outcome(names[1], "fanduel", -200, points[1])]},
        ]
    return {
        "event_id": "period-game", "sport_key": "nfl",
        "home_team": "Home", "away_team": "Away",
        "commence_time": datetime.now(timezone.utc) + timedelta(hours=2),
        "markets": markets,
    }


@pytest.mark.parametrize("suffix", ["", "_h1", "_h2", "_q1", "_q2", "_q3", "_q4"])
@pytest.mark.parametrize("market", ["h2h", "spreads", "totals"])
def test_free_bet_api_includes_period_pairs_and_alternates(market, suffix):
    g = game(market, suffix)

    class SnapshotService:
        async def get(self):
            return SimpleNamespace(generation=1, non_prop_games=(g,))

    cache = MagicMock()
    cache.path = "/tmp/free-bet-periods-test.db"
    app = FastAPI()
    app.include_router(build_router(cache, SnapshotService()))
    response = TestClient(app).get("/api/free-bets", params={
        "books": "coral33,fanduel", "free_bet_books": "coral33",
    })
    assert response.status_code == 200
    rows = response.json()["opportunities"]
    assert len(rows) == 1
    op = rows[0]
    assert op["market_kind"] == market + suffix
    assert op["free_leg"]["book"] == "coral33"
    assert op["free_leg"]["wager_type"] == "both"
    assert op["hedge_leg"]["book"] == "fanduel"
    assert op["conversion_pct"] == pytest.approx(200 / 3)
    assert op["hedge_stake_per_100"] == pytest.approx(400 / 3)


@pytest.mark.parametrize("market", ["spreads", "totals"])
def test_free_bets_never_pair_across_periods(market):
    g = game(market, "_h1")
    g["markets"][1]["market_key"] = "alternate_" + market + "_q1"
    assert scan_all_free_bets([g]) == []


@pytest.mark.parametrize("market,wrong_point", [("spreads", -3.5), ("totals", 24.5)])
def test_free_bets_require_complementary_lines(market, wrong_point):
    g = game(market, "_q2")
    g["markets"][1]["outcomes"][0]["prices"][0]["point"] = wrong_point
    assert scan_all_free_bets([g]) == []
