from unittest.mock import patch, MagicMock
from scrapers.odds import get_ncaab_odds, american_to_implied_prob, OddsData, power_devig, worst_case_devig


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
        "sport_key": "basketball_ncaab",
        "commence_time": "2026-03-20T23:00:00Z",
        "home_team": "Duke Blue Devils",
        "away_team": "North Carolina Tar Heels",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Duke Blue Devils", "price": -200},
                            {"name": "North Carolina Tar Heels", "price": 170},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Duke Blue Devils", "price": -110, "point": -6.5},
                            {"name": "North Carolina Tar Heels", "price": -110, "point": 6.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 142.5},
                            {"name": "Under", "price": -110, "point": 142.5},
                        ],
                    },
                    {
                        "key": "h2h_1st_half",
                        "outcomes": [
                            {"name": "Duke Blue Devils", "price": -160},
                            {"name": "North Carolina Tar Heels", "price": 140},
                        ],
                    },
                    {
                        "key": "totals_1st_half",
                        "outcomes": [
                            {"name": "Over", "price": -115, "point": 68.5},
                            {"name": "Under", "price": -105, "point": 68.5},
                        ],
                    },
                ],
            },
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Duke Blue Devils", "price": -210},
                            {"name": "North Carolina Tar Heels", "price": 180},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Duke Blue Devils", "price": -108, "point": -6.5},
                            {"name": "North Carolina Tar Heels", "price": -112, "point": 6.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -108, "point": 143.0},
                            {"name": "Under", "price": -112, "point": 143.0},
                        ],
                    },
                ],
            },
            {
                "key": "betmgm",
                "title": "BetMGM",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Duke Blue Devils", "price": -195},
                            {"name": "North Carolina Tar Heels", "price": 165},
                        ],
                    },
                ],
            },
        ],
    }
]


@patch("scrapers.odds.requests.get")
def test_get_ncaab_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ncaab_odds()
    assert len(results) == 1
    game = results[0]
    assert game.home == "Duke Blue Devils"
    assert game.away == "North Carolina Tar Heels"
    assert game.moneyline["home"] == -200
    assert game.moneyline["away"] == 170
    assert game.spread["home_odds"] == -109
    assert game.spread["home"] == -6.5
    assert game.total["line"] == 142.75
    assert 0 < game.implied_probs["ml_home"] < 1
    # 1H markets
    assert game.h1_moneyline["home"] == -160
    assert game.h1_total["line"] == 68.5


@patch("scrapers.odds.requests.get")
def test_get_ncaab_odds_handles_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ncaab_odds()
    assert results == []


@patch("scrapers.odds.requests.get")
def test_get_ncaab_odds_uses_consensus(mock_get):
    """Odds should be median across multiple bookmakers, not just one."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ncaab_odds()
    game = results[0]
    # Median of [-200, -210, -195] = -200
    assert game.moneyline["home"] == -200
    # Median of [170, 180, 165] = 170
    assert game.moneyline["away"] == 170
    # Spreads: median of [-110, -108] = -109
    assert game.spread["home_odds"] == -109


def test_power_devig_symmetric():
    """Symmetric odds should devig to 50/50."""
    p_a = american_to_implied_prob(-110)
    p_b = american_to_implied_prob(-110)
    fair_a, fair_b = power_devig(p_a, p_b)
    assert abs(fair_a - 0.5) < 0.01
    assert abs(fair_b - 0.5) < 0.01
    assert abs(fair_a + fair_b - 1.0) < 0.001


def test_power_devig_asymmetric():
    """Power devig should reduce favorite less than additive does."""
    p_fav = american_to_implied_prob(-300)
    p_dog = american_to_implied_prob(250)
    fair_fav, fair_dog = power_devig(p_fav, p_dog)

    additive_fav = p_fav / (p_fav + p_dog)
    assert fair_fav > additive_fav, "Power should give favorite HIGHER fair prob than additive"
    assert fair_dog < (p_dog / (p_fav + p_dog)), "Power should give underdog LOWER fair prob"
    assert abs(fair_fav + fair_dog - 1.0) < 0.001


def test_power_devig_sums_to_one():
    """Devigged probabilities must sum to 1.0 for various odds."""
    for home_odds, away_odds in [(-150, 130), (-200, 170), (-500, 400), (-110, -110)]:
        p_a = american_to_implied_prob(home_odds)
        p_b = american_to_implied_prob(away_odds)
        fair_a, fair_b = power_devig(p_a, p_b)
        assert abs(fair_a + fair_b - 1.0) < 0.001, f"Failed for {home_odds}/{away_odds}"


def test_worst_case_devig():
    """Worst case should be more conservative than power devig."""
    p_fav = american_to_implied_prob(-200)
    p_dog = american_to_implied_prob(170)
    wc_fav, wc_dog = worst_case_devig(p_fav, p_dog)
    fair_fav, fair_dog = power_devig(p_fav, p_dog)
    # Worst case for favorite should be lower (more conservative)
    assert wc_fav < fair_fav
    # Worst case for underdog should be lower (more conservative)
    assert wc_dog < fair_dog
