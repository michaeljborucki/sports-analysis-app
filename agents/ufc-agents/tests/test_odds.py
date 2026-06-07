from unittest.mock import patch, MagicMock
from scrapers.odds import OddsData, get_ufc_odds, american_to_implied_prob


def test_american_to_implied_prob_favorite():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    assert abs(american_to_implied_prob(150) - 0.4) < 0.001


def test_odds_data_defaults():
    od = OddsData(fighter_a="Islam Makhachev", fighter_b="Charles Oliveira",
                  commence_time="2026-04-12T22:00:00Z")
    assert od.moneyline == {}
    assert od.total_rounds == {}
    assert od.implied_probs == {}
    assert od.method_odds == {}


@patch("scrapers.odds.requests.get")
def test_get_ufc_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "home_team": "Islam Makhachev",
            "away_team": "Charles Oliveira",
            "commence_time": "2026-04-12T22:00:00Z",
            "bookmakers": [
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Islam Makhachev", "price": -200},
                                {"name": "Charles Oliveira", "price": 170},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -115, "point": 2.5},
                                {"name": "Under", "price": -105},
                            ],
                        },
                    ]
                },
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Islam Makhachev", "price": -210},
                                {"name": "Charles Oliveira", "price": 180},
                            ],
                        },
                    ]
                }
            ],
        }
    ]
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ufc_odds()
    assert len(results) == 1
    od = results[0]
    assert od.fighter_a == "Islam Makhachev"
    assert od.fighter_b == "Charles Oliveira"
    assert od.moneyline["fighter_a"] == -205  # median of [-200, -210]
    assert od.moneyline["fighter_b"] == 175   # median of [170, 180]
    assert od.moneyline["num_books"] == 2
    assert od.total_rounds["line"] == 2.5
    assert od.total_rounds["over_odds"] == -115
    assert od.total_rounds["under_odds"] == -105
    assert "fighter_a" in od.implied_probs
    assert "fighter_b" in od.implied_probs


@patch("scrapers.odds.requests.get")
def test_get_ufc_odds_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ufc_odds()
    assert results == []
