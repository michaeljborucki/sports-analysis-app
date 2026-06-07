"""Tests for scrapers/odds.py."""
from unittest.mock import patch, MagicMock
from scrapers.odds import american_to_implied_prob, OddsData, get_nba_odds, _pick_bookmaker, merge_event_odds


def test_implied_prob_favorite():
    p = american_to_implied_prob(-150)
    assert abs(p - 0.6) < 0.01


def test_implied_prob_underdog():
    p = american_to_implied_prob(150)
    assert abs(p - 0.4) < 0.01


def test_odds_data_fields():
    od = OddsData(home="BOS", away="LAL", commence_time="2026-03-22T00:30:00Z")
    assert od.spread == {}
    assert od.h1_moneyline == {}
    assert od.h1_total == {}
    assert od.h1_spread == {}
    assert not hasattr(od, "run_line")
    assert not hasattr(od, "f5_moneyline")


def test_odds_data_has_event_id():
    od = OddsData(home="BOS", away="LAL", commence_time="2026-03-22T00:30:00Z")
    assert hasattr(od, "event_id")
    assert od.event_id == ""


def test_odds_data_has_quarter_fields():
    od = OddsData(home="BOS", away="LAL", commence_time="2026-03-22T00:30:00Z")
    # Quarter fields
    assert od.q1_moneyline == {}
    assert od.q1_spread == {}
    assert od.q1_total == {}
    assert od.q2_moneyline == {}
    assert od.q2_spread == {}
    assert od.q2_total == {}
    assert od.q3_moneyline == {}
    assert od.q3_spread == {}
    assert od.q3_total == {}
    assert od.q4_moneyline == {}
    assert od.q4_spread == {}
    assert od.q4_total == {}
    # Team totals
    assert od.team_totals == {}
    # Player props
    assert od.player_props == {}
    # Alternate lines
    assert od.alt_spreads == []
    assert od.alt_totals == []


def test_odds_data_has_h2_fields():
    od = OddsData(home="BOS", away="LAL", commence_time="2026-03-22T00:30:00Z")
    assert od.h2_moneyline == {}
    assert od.h2_spread == {}
    assert od.h2_total == {}


def test_pick_bookmaker_prefers_draftkings():
    bookmakers = [
        {"key": "betmgm", "markets": []},
        {"key": "fanduel", "markets": []},
        {"key": "draftkings", "markets": []},
    ]
    result = _pick_bookmaker(bookmakers)
    assert result["key"] == "draftkings"

    # When draftkings absent, prefer fanduel
    bookmakers2 = [
        {"key": "betmgm", "markets": []},
        {"key": "fanduel", "markets": []},
    ]
    result2 = _pick_bookmaker(bookmakers2)
    assert result2["key"] == "fanduel"

    # When only betmgm, return it
    bookmakers3 = [{"key": "betmgm", "markets": []}]
    result3 = _pick_bookmaker(bookmakers3)
    assert result3["key"] == "betmgm"

    # Empty list returns None
    assert _pick_bookmaker([]) is None


@patch("scrapers.odds.requests.get")
def test_get_nba_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.json.return_value = [
        {
            "id": "abc123",
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "commence_time": "2026-03-22T00:30:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": "Boston Celtics", "price": -150},
                            {"name": "Los Angeles Lakers", "price": 130},
                        ]},
                        {"key": "spreads", "outcomes": [
                            {"name": "Boston Celtics", "price": -110, "point": -4.5},
                            {"name": "Los Angeles Lakers", "price": -110, "point": 4.5},
                        ]},
                        {"key": "totals", "outcomes": [
                            {"name": "Over", "price": -110, "point": 218.5},
                            {"name": "Under", "price": -110},
                        ]},
                        {"key": "h2h_h1", "outcomes": [
                            {"name": "Boston Celtics", "price": -130},
                            {"name": "Los Angeles Lakers", "price": 110},
                        ]},
                        {"key": "totals_h1", "outcomes": [
                            {"name": "Over", "price": -115, "point": 108.5},
                            {"name": "Under", "price": -105},
                        ]},
                        {"key": "spreads_h1", "outcomes": [
                            {"name": "Boston Celtics", "price": -110, "point": -2.5},
                            {"name": "Los Angeles Lakers", "price": -110, "point": 2.5},
                        ]},
                    ]
                }
            ],
        }
    ]
    mock_get.return_value = mock_resp
    results = get_nba_odds()
    assert len(results) == 1
    assert results[0].home == "BOS"
    assert results[0].away == "LAL"
    assert results[0].moneyline["home"] == -150
    assert results[0].spread["home"] == -4.5
    assert results[0].total["line"] == 218.5
    assert results[0].h1_moneyline["home"] == -130
    assert results[0].h1_total["line"] == 108.5
    assert results[0].h1_total["over_odds"] == -115
    assert results[0].h1_spread["home"] == -2.5


@patch("scrapers.odds.requests.get")
def test_get_nba_odds_extracts_event_id(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.json.return_value = [
        {
            "id": "event_xyz_789",
            "home_team": "Boston Celtics",
            "away_team": "Los Angeles Lakers",
            "commence_time": "2026-03-22T00:30:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": "Boston Celtics", "price": -150},
                            {"name": "Los Angeles Lakers", "price": 130},
                        ]},
                    ]
                }
            ],
        }
    ]
    mock_get.return_value = mock_resp
    results = get_nba_odds()
    assert len(results) == 1
    assert results[0].event_id == "event_xyz_789"


def test_merge_event_odds():
    od = OddsData(home="BOS", away="LAL", commence_time="2026-03-22T00:30:00Z", event_id="ev1")

    event_resp = {
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    # Q1 moneyline
                    {"key": "h2h_q1", "outcomes": [
                        {"name": "Boston Celtics", "price": -120},
                        {"name": "Los Angeles Lakers", "price": 100},
                    ]},
                    # Q1 total
                    {"key": "totals_q1", "outcomes": [
                        {"name": "Over", "price": -110, "point": 55.5},
                        {"name": "Under", "price": -110},
                    ]},
                    # Team totals
                    {"key": "team_totals", "outcomes": [
                        {"description": "Boston Celtics", "name": "Over", "price": -115, "point": 112.5},
                        {"description": "Boston Celtics", "name": "Under", "price": -105},
                        {"description": "Los Angeles Lakers", "name": "Over", "price": -110, "point": 108.5},
                        {"description": "Los Angeles Lakers", "name": "Under", "price": -110},
                    ]},
                    # Player props
                    {"key": "player_points", "outcomes": [
                        {"description": "Jayson Tatum", "name": "Over", "price": -115, "point": 27.5},
                        {"description": "Jayson Tatum", "name": "Under", "price": -105},
                    ]},
                    # H2 total
                    {"key": "totals_h2", "outcomes": [
                        {"name": "Over", "price": -110, "point": 110.0},
                        {"name": "Under", "price": -110},
                    ]},
                ]
            }
        ]
    }

    merge_event_odds(od, event_resp)

    # Q1 checks
    assert od.q1_moneyline.get("home") == -120
    assert od.q1_moneyline.get("away") == 100
    assert od.q1_total.get("line") == 55.5
    assert od.q1_total.get("over_odds") == -110

    # Team totals checks
    assert od.team_totals.get("home", {}).get("line") == 112.5
    assert od.team_totals.get("home", {}).get("over_odds") == -115
    assert od.team_totals.get("away", {}).get("line") == 108.5

    # Player props checks
    assert "Jayson Tatum" in od.player_props
    assert od.player_props["Jayson Tatum"]["points"]["line"] == 27.5
    assert od.player_props["Jayson Tatum"]["points"]["over_odds"] == -115
    assert od.player_props["Jayson Tatum"]["points"]["under_odds"] == -105

    # H2 total checks
    assert od.h2_total.get("line") == 110.0
    assert od.h2_total.get("over_odds") == -110
