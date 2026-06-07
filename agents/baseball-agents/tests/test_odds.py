from unittest.mock import patch, MagicMock
from scrapers.odds import get_mlb_odds, american_to_implied_prob, OddsData


def test_american_to_implied_prob_favorite():
    # -150 implies 60%
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    # +130 implies ~43.5%
    assert abs(american_to_implied_prob(130) - 0.4348) < 0.001


def test_american_to_implied_prob_even():
    assert abs(american_to_implied_prob(100) - 0.5) < 0.001


MOCK_ODDS_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-04-01T23:05:00Z",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "New York Yankees", "price": -150},
                            {"name": "Boston Red Sox", "price": 130},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "New York Yankees", "price": 140, "point": -1.5},
                            {"name": "Boston Red Sox", "price": -165, "point": 1.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 8.5},
                            {"name": "Under", "price": -110, "point": 8.5},
                        ],
                    },
                    {
                        "key": "h2h_1st_5_innings",
                        "outcomes": [
                            {"name": "New York Yankees", "price": -135},
                            {"name": "Boston Red Sox", "price": 115},
                        ],
                    },
                    {
                        "key": "totals_1st_5_innings",
                        "outcomes": [
                            {"name": "Over", "price": -115, "point": 4.5},
                            {"name": "Under", "price": -105, "point": 4.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@patch("scrapers.odds.requests.get")
def test_get_mlb_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_mlb_odds()
    assert len(results) == 1
    game = results[0]
    assert game.home == "NYY"
    assert game.away == "BOS"
    assert game.moneyline["home"] == -150
    assert game.moneyline["away"] == 130
    assert game.run_line["home_odds"] == 140
    assert game.total["line"] == 8.5
    assert 0 < game.implied_probs["ml_home"] < 1
    # F5 markets
    assert game.f5_moneyline["home"] == -135
    assert game.f5_moneyline["away"] == 115
    assert game.f5_total["line"] == 4.5
    assert game.f5_total["over"] == -115


@patch("scrapers.odds.requests.get")
def test_get_mlb_odds_handles_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_mlb_odds()
    assert results == []


def test_power_devig_sums_to_one():
    from scrapers.odds import power_devig, american_to_implied_prob
    a = american_to_implied_prob(-200)
    b = american_to_implied_prob(170)
    da, db = power_devig(a, b)
    assert abs(da + db - 1.0) < 1e-6


def test_power_devig_shifts_favorite():
    from scrapers.odds import power_devig, american_to_implied_prob
    a = american_to_implied_prob(-200)
    b = american_to_implied_prob(170)
    da, db = power_devig(a, b)
    naive_a = a / (a + b)
    # Power method gives favorites a higher true prob than naive normalization
    assert da > naive_a
    assert da > 0.5


def test_power_devig_even_odds():
    from scrapers.odds import power_devig, american_to_implied_prob
    a = american_to_implied_prob(-110)
    b = american_to_implied_prob(-110)
    da, db = power_devig(a, b)
    assert abs(da - 0.5) < 1e-4
    assert abs(db - 0.5) < 1e-4


def test_power_devig_no_vig_passthrough():
    from scrapers.odds import power_devig
    da, db = power_devig(0.6, 0.4)
    assert abs(da - 0.6) < 1e-6
    assert abs(db - 0.4) < 1e-6


def test_best_line_selection_picks_best_odds():
    """get_mlb_odds should pick best decimal odds per side across books."""
    from unittest.mock import patch, MagicMock
    from scrapers.odds import get_mlb_odds

    mock_event = {
        "id": "test123",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "commence_time": "2099-12-31T23:00:00Z",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -150},
                    {"name": "Boston Red Sox", "price": 130},
                ]}],
            },
            {
                "key": "draftkings",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -140},
                    {"name": "Boston Red Sox", "price": 125},
                ]}],
            },
            {
                "key": "betmgm",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -145},
                    {"name": "Boston Red Sox", "price": 135},
                ]}],
            },
        ],
    }

    with patch("scrapers.odds.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [mock_event]
        mock_resp.headers = {"x-requests-remaining": "450"}
        mock_get.return_value = mock_resp

        results = get_mlb_odds()
        assert len(results) == 1
        game = results[0]
        # Best home: -140 (highest decimal = 1.714 from draftkings)
        assert game.moneyline["home"] == -140
        # Best away: +135 (highest decimal = 2.35 from betmgm)
        assert game.moneyline["away"] == 135
        # Book sources tracked
        assert game.book_sources.get("h2h_home") == "draftkings"
        assert game.book_sources.get("h2h_away") == "betmgm"


def test_implied_probs_average_across_all_books():
    """Implied probs should be the average of power-devigged probs across all books."""
    from scrapers.odds import power_devig

    mock_event = {
        "id": "test456",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "commence_time": "2099-12-31T23:00:00Z",
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -150},
                    {"name": "Boston Red Sox", "price": 130},
                ]}],
            },
            {
                "key": "draftkings",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -160},
                    {"name": "Boston Red Sox", "price": 140},
                ]}],
            },
            {
                "key": "betmgm",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -140},
                    {"name": "Boston Red Sox", "price": 120},
                ]}],
            },
        ],
    }

    with patch("scrapers.odds.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [mock_event]
        mock_resp.headers = {"x-requests-remaining": "450"}
        mock_get.return_value = mock_resp

        results = get_mlb_odds()
        game = results[0]

        # Manually compute expected: power_devig each book, then average
        books = [(-150, 130), (-160, 140), (-140, 120)]
        dv_homes, dv_aways = [], []
        for home_odds, away_odds in books:
            h = american_to_implied_prob(home_odds)
            a = american_to_implied_prob(away_odds)
            dh, da = power_devig(h, a)
            dv_homes.append(dh)
            dv_aways.append(da)

        expected_home = sum(dv_homes) / len(dv_homes)
        expected_away = sum(dv_aways) / len(dv_aways)

        assert abs(game.implied_probs["ml_home"] - expected_home) < 1e-4
        assert abs(game.implied_probs["ml_away"] - expected_away) < 1e-4
        assert game.implied_probs["ml_book_count"] == 3
