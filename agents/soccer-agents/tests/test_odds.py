import pytest
from unittest.mock import patch, MagicMock
from scrapers.odds import OddsData, get_soccer_odds, american_to_implied_prob


def test_american_to_implied_prob_negative():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.01


def test_american_to_implied_prob_positive():
    assert abs(american_to_implied_prob(150) - 0.4) < 0.01


def test_odds_data_has_soccer_fields():
    od = OddsData(home="Inter", away="Milan", commence_time="2026-03-25T20:00:00Z")
    assert hasattr(od, "asian_handicap")
    assert hasattr(od, "total")
    assert hasattr(od, "btts")
    assert hasattr(od, "moneyline_1x2")
    assert hasattr(od, "implied_probs")
    assert not hasattr(od, "run_line")
    assert not hasattr(od, "f5_moneyline")
    assert not hasattr(od, "f5_total")


MOCK_API_RESPONSE = [
    {
        "home_team": "Inter Miami CF",
        "away_team": "LA Galaxy",
        "commence_time": "2026-03-25T23:30:00Z",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Inter Miami CF", "price": -120},
                            {"name": "LA Galaxy", "price": 300},
                            {"name": "Draw", "price": 260},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Inter Miami CF", "price": -110, "point": -0.5},
                            {"name": "LA Galaxy", "price": -110, "point": 0.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -115, "point": 2.5},
                            {"name": "Under", "price": -105},
                        ],
                    },
                    {
                        "key": "btts",
                        "outcomes": [
                            {"name": "Yes", "price": -110},
                            {"name": "No", "price": -110},
                        ],
                    },
                ],
            }
        ],
    }
]


@patch("scrapers.odds.requests.get")
def test_get_soccer_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_API_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    results = get_soccer_odds(league="MLS")
    assert len(results) == 1
    od = results[0]
    assert od.home == "Inter Miami CF"
    assert od.away == "LA Galaxy"
    assert od.asian_handicap["home"] == -0.5
    assert od.asian_handicap["home_odds"] == -110
    assert od.total["line"] == 2.5
    assert od.moneyline_1x2["home"] == -120
    assert od.moneyline_1x2["draw"] == 260
    assert od.btts["yes_odds"] == -110
    assert od.btts["no_odds"] == -110


@patch("scrapers.odds.requests.get")
def test_get_soccer_odds_no_games(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    results = get_soccer_odds(league="MLS")
    assert results == []
