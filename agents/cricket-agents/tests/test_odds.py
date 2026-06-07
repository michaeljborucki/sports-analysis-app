"""Tests for scrapers/odds.py — cricket rewrite."""
from unittest.mock import patch, MagicMock
from scrapers.odds import get_cricket_odds, american_to_implied_prob, OddsData


# --- american_to_implied_prob ---

def test_american_to_implied_prob_favorite():
    # -150 implies 60%
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    # +130 implies ~43.5%
    assert abs(american_to_implied_prob(130) - 0.4348) < 0.001


def test_american_to_implied_prob_even():
    assert abs(american_to_implied_prob(100) - 0.5) < 0.001


# --- Mock API response for get_cricket_odds ---

MOCK_CRICKET_ODDS_RESPONSE = [
    {
        "id": "ipl_match_001",
        "sport_key": "cricket_ipl",
        "commence_time": "2026-03-22T14:00:00Z",
        "home_team": "Mumbai Indians",
        "away_team": "Chennai Super Kings",
        "bookmakers": [
            {
                "key": "bet365",
                "title": "Bet365",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Mumbai Indians", "price": -130},
                            {"name": "Chennai Super Kings", "price": 110},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 320.5},
                            {"name": "Under", "price": -110, "point": 320.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_returns_oddsdata(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_cricket_odds("ipl")
    assert len(results) == 1
    game = results[0]
    assert isinstance(game, OddsData)


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_team_abbrevs(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_cricket_odds("ipl")
    game = results[0]
    assert game.team_a == "MI"
    assert game.team_b == "CSK"
    assert game.team_a_full == "Mumbai Indians"
    assert game.team_b_full == "Chennai Super Kings"


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_moneyline_keys(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_cricket_odds("ipl")
    game = results[0]
    # Critical: keys must be "team_a" and "team_b"
    assert "team_a" in game.moneyline
    assert "team_b" in game.moneyline
    assert game.moneyline["team_a"] == -130
    assert game.moneyline["team_b"] == 110


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_total_runs_keys(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_cricket_odds("ipl")
    game = results[0]
    # Critical: keys must be "line", "over", "under"
    assert "line" in game.total_runs
    assert "over" in game.total_runs
    assert "under" in game.total_runs
    assert game.total_runs["line"] == 320.5
    assert game.total_runs["over"] == -110
    assert game.total_runs["under"] == -110


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_implied_probs(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_cricket_odds("ipl")
    game = results[0]
    # Critical: keys must be "team_a" and "team_b"
    assert "team_a" in game.implied_probs
    assert "team_b" in game.implied_probs
    # Vig-removed probs should sum to ~1.0
    total = game.implied_probs["team_a"] + game.implied_probs["team_b"]
    assert abs(total - 1.0) < 0.001
    # MI is favourite (-130) so implied prob should be > 0.5
    assert game.implied_probs["team_a"] > 0.5


@patch("scrapers.odds.requests.get")
def test_get_cricket_odds_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_cricket_odds("ipl")
    assert results == []
