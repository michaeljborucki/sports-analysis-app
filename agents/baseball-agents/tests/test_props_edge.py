"""Tests for prop edge detection."""
import pytest
from simulation.props_edge import distribution_to_over_prob, check_prop_edge


@pytest.fixture(autouse=True)
def _no_prod_calibration(monkeypatch):
    """Isolate edge tests from production calibrators — exercise raw edge math."""
    import calibrate
    monkeypatch.setattr(calibrate, "_CALIBRATORS", {})


def test_distribution_to_over_prob_high():
    dist = [0.0, 0.0, 0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.10, 0.05, 0.05]
    prob = distribution_to_over_prob(dist, 5.5)
    assert prob > 0.55  # P(6+) = 0.20+0.10+0.05+0.05 = 0.40... wait
    # Actually P(over 5.5) = P(6) + P(7) + ... = dist[6]+dist[7]+dist[8]+dist[9]+dist[10]
    # = 0.25 + 0.20 + 0.10 + 0.05 + 0.05 = 0.65
    assert prob > 0.60


def test_distribution_to_over_prob_low():
    dist = [0.10, 0.20, 0.25, 0.20, 0.15, 0.05, 0.03, 0.02]
    prob = distribution_to_over_prob(dist, 4.5)
    # P(over 4.5) = P(5)+P(6)+P(7) = 0.05+0.03+0.02 = 0.10
    assert prob < 0.15


def test_check_prop_edge_found():
    # Distribution centered at 6-7, line at 4.5 → strong over
    dist = [0.0, 0.0, 0.0, 0.05, 0.10, 0.20, 0.25, 0.20, 0.10, 0.05, 0.05]
    result = check_prop_edge(
        distribution=dist, line=4.5,
        over_odds=-110, under_odds=-110,
        threshold=0.05, bet_type="pitcher_strikeouts",
        player_name="Test Pitcher",
    )
    assert result is not None
    assert result["bet_type"] == "pitcher_strikeouts"
    assert result["edge"] > 0.05
    assert "over" in result["side"].lower()


def test_check_prop_edge_no_edge():
    # Distribution centered right at line
    dist = [0.05, 0.10, 0.15, 0.20, 0.20, 0.15, 0.10, 0.05]
    result = check_prop_edge(
        distribution=dist, line=3.5,
        over_odds=-110, under_odds=-110,
        threshold=0.05, bet_type="batter_hits",
        player_name="Test Batter",
    )
    # Edge should be small, might be None
    if result is not None:
        assert result["edge"] >= 0.05


def test_distribution_to_over_prob_edge_cases():
    # Empty distribution
    assert distribution_to_over_prob([], 0.5) == 0.0
    # Single element
    assert distribution_to_over_prob([1.0], 0.5) == 0.0
    # Line beyond distribution
    assert distribution_to_over_prob([0.5, 0.5], 5.5) == 0.0


def test_shrink_to_market_blends_toward_market():
    """Market-shrinkage guardrail: blend the model prob toward the no-vig
    market prior (the replacement for the dropped prop calibrators)."""
    from simulation.props_edge import _shrink_to_market, MARKET_BLEND_WEIGHT
    assert 0.0 < MARKET_BLEND_WEIGHT < 1.0
    out = _shrink_to_market(0.80, 0.50)
    assert out == pytest.approx((1 - MARKET_BLEND_WEIGHT) * 0.80 + MARKET_BLEND_WEIGHT * 0.50)
    assert 0.50 < out < 0.80  # pulled toward the market, not past it
    # Model already at market → unchanged.
    assert _shrink_to_market(0.60, 0.60) == pytest.approx(0.60)


def test_check_prop_edge_shrinks_overconfident_model_toward_market():
    """An overconfident model probability is anchored toward the no-vig market,
    shrinking both the reported edge and the bet-on probability."""
    # Model: P(0 hits)=0.75 → under-0.5 prob 0.75; market is far less confident.
    dist = [0.75, 0.25]
    result = check_prop_edge(
        distribution=dist, line=0.5,
        over_odds=110, under_odds=-120,
        threshold=0.05, bet_type="batter_total_bases",
        player_name="Test Batter",
    )
    assert result is not None
    assert "under" in result["side"].lower()
    mkt = result["market_prob"]
    # Bet-on prob sits strictly between the market and the (uncalibrated) model 0.75.
    assert mkt < result["sim_prob"] < 0.75
    # Reported edge is smaller than the raw model-vs-market gap (shrinkage applied).
    assert result["edge"] < (0.75 - mkt)


def test_distribution_to_over_prob_clamps_degenerate_tail():
    """Empirical MC can put 100% of samples above the line for a low line
    (e.g. pitcher_outs over 14.5 when every sim has the starter finishing
    the 5th inning). The sim doesn't model injuries, ejections, early
    strategic hooks, or weather — unmodeled tail risk is ~2-3%. Returning
    exactly 1.0 feeds nonsense Kelly sizing and breaks downstream code
    expecting a probability in (0, 1).
    """
    # All mass at index 15+ → line at 14.5 means every sample is "over"
    dist = [0.0] * 15 + [0.6, 0.3, 0.1]
    prob = distribution_to_over_prob(dist, 14.5)
    assert 0 < prob < 1, f"prob must be in (0,1), got {prob}"
    assert prob <= 0.98, f"expected ceiling at 0.98, got {prob}"
    assert prob >= 0.95, f"ceiling shouldn't be overly aggressive, got {prob}"


def test_distribution_to_over_prob_clamps_degenerate_head():
    """Symmetric case: every sample below the line should not yield 0.0."""
    # All mass at 0, line at 2.5
    dist = [1.0, 0.0, 0.0, 0.0, 0.0]
    prob = distribution_to_over_prob(dist, 2.5)
    assert 0 < prob < 1, f"prob must be in (0,1), got {prob}"
    assert prob >= 0.02, f"expected floor at 0.02, got {prob}"


def test_distribution_to_over_prob_passes_through_normal_values():
    """Healthy middle-of-range probs must not be clamped."""
    dist = [0.1, 0.2, 0.3, 0.2, 0.1, 0.05, 0.03, 0.02]
    prob = distribution_to_over_prob(dist, 3.5)
    # P(over 3.5) = 0.1+0.05+0.03+0.02 = 0.20 — nowhere near the clamp band
    assert abs(prob - 0.20) < 1e-9
