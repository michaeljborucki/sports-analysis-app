"""Tests for plate appearance outcome sampling."""
from simulation.pa_engine import matchup_probability, sample_pa, OUTCOMES, normalize_probs


def test_matchup_probability_neutral():
    """When batter and pitcher are league average, result should be league average."""
    league = 0.20
    prob = matchup_probability(league, league, league)
    assert abs(prob - league) < 0.01


def test_matchup_probability_strong_batter():
    """Strong batter + average pitcher should exceed league average."""
    prob = matchup_probability(batter_rate=0.30, pitcher_rate=0.20, league_rate=0.20)
    assert prob > 0.20


def test_normalize_probs_sums_to_one():
    raw = {"K": 0.3, "BB": 0.1, "1B": 0.2, "2B": 0.05, "3B": 0.01, "HR": 0.04, "OUT": 0.5}
    normed = normalize_probs(raw)
    assert abs(sum(normed.values()) - 1.0) < 0.001


def test_sample_pa_returns_valid_outcome():
    batter = {"k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.03,
              "single_pct": 0.15, "double_pct": 0.04, "triple_pct": 0.004, "out_pct": 0.46}
    pitcher = {"k_pct": 0.25, "bb_pct": 0.07, "hr_pct": 0.025,
               "single_pct": 0.14, "double_pct": 0.04, "triple_pct": 0.003, "out_pct": 0.46}
    result = sample_pa(batter, pitcher)
    assert result in OUTCOMES


def test_sample_pa_distribution_reasonable():
    """Over 10000 samples, K rate should be roughly in expected range."""
    import random
    random.seed(42)
    batter = {"k_pct": 0.25, "bb_pct": 0.08, "hr_pct": 0.03,
              "single_pct": 0.15, "double_pct": 0.04, "triple_pct": 0.004, "out_pct": 0.44}
    pitcher = {"k_pct": 0.25, "bb_pct": 0.08, "hr_pct": 0.03,
               "single_pct": 0.15, "double_pct": 0.04, "triple_pct": 0.004, "out_pct": 0.44}
    results = [sample_pa(batter, pitcher) for _ in range(10000)]
    k_rate = results.count("K") / len(results)
    assert 0.20 < k_rate < 0.35
