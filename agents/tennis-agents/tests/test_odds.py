from unittest.mock import patch, MagicMock
from scrapers.odds import (
    get_tennis_odds, american_to_implied_prob, OddsData, compute_clv,
    american_be_with_wiggle,
)


def test_be_with_wiggle_favorite_stays_valid():
    assert american_be_with_wiggle(-150) == -145


def test_be_with_wiggle_underdog_stays_valid():
    assert american_be_with_wiggle(150) == 145


def test_be_with_wiggle_favorite_crosses_zero():
    # -103 with 5-cent wiggle → magnitude 95, which is invalid. Must cross to positive side.
    result = american_be_with_wiggle(-103)
    assert result > 100, f"expected valid dog price after zero-crossing, got {result}"
    assert result % 5 == 0


def test_be_with_wiggle_underdog_crosses_zero():
    result = american_be_with_wiggle(103)
    assert result < -100, f"expected valid fav price after zero-crossing, got {result}"
    assert result % 5 == 0


def test_compute_clv_dog_beat_the_close():
    # Bet +150, close +130 → we beat the close on the dog side (got a longer price).
    clv = compute_clv(bet_odds=150, close_odds=130)
    assert clv["clv_cents"] == 20
    assert clv["clv_pct"] > 0


def test_compute_clv_dog_lost_the_close():
    # Bet +120, close +140 → close lengthened, we were on the wrong side of the move.
    clv = compute_clv(bet_odds=120, close_odds=140)
    assert clv["clv_cents"] == -20
    assert clv["clv_pct"] < 0


def test_compute_clv_favorite_beat_the_close():
    # Bet -130, close -150 → shortened toward favorite; we got a better price.
    clv = compute_clv(bet_odds=-130, close_odds=-150)
    assert clv["clv_cents"] == 20
    assert clv["clv_pct"] > 0


def test_compute_clv_cross_zero_bet_dog_close_fav():
    # Bet +110, close -110 → market moved to favorite; our +110 beats a -110 close.
    clv = compute_clv(bet_odds=110, close_odds=-110)
    # Our decimal: 2.10; close decimal: 1.9091 → clv_pct ≈ 0.10
    assert clv["clv_pct"] > 0.09
    assert clv["clv_cents"] > 0  # Crossing from +to- counts as positive cents


def test_compute_clv_no_movement_returns_zero():
    clv = compute_clv(bet_odds=-110, close_odds=-110)
    assert clv["clv_cents"] == 0
    assert clv["clv_pct"] == 0.0


def test_american_to_implied_prob_favorite():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    assert abs(american_to_implied_prob(130) - 0.4348) < 0.001


def test_american_to_implied_prob_even():
    assert abs(american_to_implied_prob(100) - 0.5) < 0.001


MOCK_ODDS_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "tennis_atp",
        "commence_time": "2026-06-30T14:00:00Z",
        "home_team": "Novak Djokovic",
        "away_team": "Carlos Alcaraz",
        "bookmakers": [{
            "key": "fanduel", "title": "FanDuel",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Novak Djokovic", "price": -150},
                    {"name": "Carlos Alcaraz", "price": 130},
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": "Novak Djokovic", "price": -110, "point": -3.5},
                    {"name": "Carlos Alcaraz", "price": -110, "point": 3.5},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -110, "point": 22.5},
                    {"name": "Under", "price": -110},
                ]},
            ],
        }],
    },
]


@patch("scrapers.odds.requests.get")
def test_get_tennis_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp
    results = get_tennis_odds("atp")
    assert len(results) == 1
    assert results[0].player_a == "Novak Djokovic"
    assert results[0].player_b == "Carlos Alcaraz"
    assert results[0].moneyline["player_a"] == -150
    assert results[0].game_handicap["player_a_point"] == -3.5
    assert results[0].total_games["line"] == 22.5
    assert "player_a" in results[0].implied_probs


@patch("scrapers.odds.requests.get")
def test_get_tennis_odds_handles_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp
    results = get_tennis_odds("wta")
    assert results == []


def test_odds_data_defaults():
    od = OddsData(player_a="A", player_b="B", commence_time="2026-01-01T00:00:00Z")
    assert od.moneyline == {}
    assert od.game_handicap == {}
    assert od.total_games == {}
