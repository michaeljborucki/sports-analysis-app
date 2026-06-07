"""Tests for Phase 1 OddsData extensions."""
from scrapers.odds import OddsData


def test_odds_data_has_new_fields():
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    assert od.event_id == ""
    assert od.team_total_home == {}
    assert od.team_total_away == {}
    assert od.f5_spread == {}
    assert od.f1_total == {}
    assert od.f1_spread == {}
    assert od.f3_moneyline == {}
    assert od.f3_total == {}
    assert od.f3_spread == {}


def test_parse_team_totals():
    from scrapers.odds import _parse_additional_markets
    raw_markets = {
        "team_totals": {
            "key": "team_totals",
            "outcomes": [
                {"name": "Over", "description": "New York Yankees", "price": -110, "point": 4.5},
                {"name": "Under", "description": "New York Yankees", "price": -110, "point": 4.5},
                {"name": "Over", "description": "Boston Red Sox", "price": -115, "point": 3.5},
                {"name": "Under", "description": "Boston Red Sox", "price": -105, "point": 3.5},
            ],
        }
    }
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    _parse_additional_markets(od, raw_markets)
    assert od.team_total_home["line"] == 4.5
    assert od.team_total_home["over_odds"] == -110
    assert od.team_total_away["line"] == 3.5


def test_parse_f5_spread():
    from scrapers.odds import _parse_additional_markets
    raw_markets = {
        "spreads_1st_5_innings": {
            "key": "spreads_1st_5_innings",
            "outcomes": [
                {"name": "New York Yankees", "price": -125, "point": -0.5},
                {"name": "Boston Red Sox", "price": 105, "point": 0.5},
            ],
        }
    }
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    _parse_additional_markets(od, raw_markets)
    assert od.f5_spread["home"] == -0.5
    assert od.f5_spread["home_odds"] == -125
    assert od.f5_spread["away"] == 0.5
    assert od.f5_spread["away_odds"] == 105


def test_parse_nrfi():
    from scrapers.odds import _parse_additional_markets
    raw_markets = {
        "totals_1st_1_innings": {
            "key": "totals_1st_1_innings",
            "outcomes": [
                {"name": "Over", "price": 115, "point": 0.5},
                {"name": "Under", "price": -135, "point": 0.5},
            ],
        }
    }
    od = OddsData(home="NYY", away="BOS", commence_time="2026-03-20T18:00:00Z")
    _parse_additional_markets(od, raw_markets)
    assert od.f1_total["line"] == 0.5
    assert od.f1_total["over_odds"] == 115
    assert od.f1_total["under_odds"] == -135
