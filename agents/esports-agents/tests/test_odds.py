import json
import os
from unittest.mock import patch, MagicMock
from scrapers.odds import OddsData, get_esports_odds, american_to_implied_prob

def test_american_to_implied_prob_negative():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001

def test_american_to_implied_prob_positive():
    assert abs(american_to_implied_prob(150) - 0.4) < 0.001

def test_odds_data_to_dict():
    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": -175, "team_b": 145},
    )
    d = od.to_dict()
    assert d["team_a"] == "NaVi"
    assert d["moneyline"]["team_a"] == -175
    assert d["format"] == "bo3"

def test_odds_data_implied_probs():
    od = OddsData(
        team_a="NaVi", team_b="FaZe",
        commence_time="2026-03-20T15:00:00Z",
        game_title="cs2", tournament="IEM", format="bo3",
        moneyline={"team_a": -175, "team_b": 145},
    )
    od.compute_implied_probs()
    assert "ml_team_a" in od.implied_probs
    assert "ml_team_b" in od.implied_probs
    assert abs(od.implied_probs["ml_team_a"] + od.implied_probs["ml_team_b"] - 1.0) < 0.001

def test_get_esports_odds_empty_on_no_key():
    with patch.dict(os.environ, {"ODDSPAPI_API_KEY": ""}, clear=False):
        from importlib import reload
        import config
        reload(config)
        result = get_esports_odds("cs2")
        assert result == []
