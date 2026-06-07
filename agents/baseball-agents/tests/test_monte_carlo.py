"""Tests for Monte Carlo distribution aggregation."""
from simulation.monte_carlo import run_monte_carlo

AVG_BATTER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
              "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459,
              "player_id": 1}
AVG_PITCHER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
               "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459,
               "avg_pitch_count": 90, "player_id": 100}


def test_monte_carlo_returns_distributions():
    import random
    random.seed(42)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    result = run_monte_carlo(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher={**AVG_PITCHER, "player_id": 100},
        away_pitcher={**AVG_PITCHER, "player_id": 200},
        n_sims=100,
    )
    assert result["n_sims"] == 100
    assert "pitcher_distributions" in result
    assert "batter_distributions" in result
    assert "game_results" in result
    assert 100 in result["pitcher_distributions"]
    assert "k" in result["pitcher_distributions"][100]
    assert 1 in result["batter_distributions"]
    assert "h" in result["batter_distributions"][1]
    gr = result["game_results"]
    assert 0 <= gr["tied_after_1"] <= 1
    assert 0 <= gr["tied_after_5"] <= 1


def test_monte_carlo_distributions_sum_to_one():
    import random
    random.seed(42)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    result = run_monte_carlo(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher={**AVG_PITCHER, "player_id": 100},
        away_pitcher={**AVG_PITCHER, "player_id": 200},
        n_sims=100,
    )
    k_dist = result["pitcher_distributions"][100]["k"]
    assert abs(sum(k_dist) - 1.0) < 0.01


def test_monte_carlo_game_results():
    import random
    random.seed(42)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    result = run_monte_carlo(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher={**AVG_PITCHER, "player_id": 100},
        away_pitcher={**AVG_PITCHER, "player_id": 200},
        n_sims=100,
    )
    gr = result["game_results"]
    assert gr["home_wins"] + gr["away_wins"] == 100
    assert 3 < gr["avg_total"] < 15
