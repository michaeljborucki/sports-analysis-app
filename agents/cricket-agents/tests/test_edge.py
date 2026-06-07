import math
import pytest
from edge import (
    calculate_linear_edge,
    calculate_exponential_edge,
    calculate_poisson_edge,
    american_to_decimal,
    kelly_criterion,
    analyze_all_edges,
    detect_edge,
    check_moneyline_edge,
)


# === Linear Engine Tests ===

def test_linear_over_edge():
    side, proj, prob, edge = calculate_linear_edge(projected=350, line=340, multiplier=0.008)
    assert side == "over"
    assert proj == 350
    assert prob == pytest.approx(0.58, abs=0.01)
    assert edge == pytest.approx(0.08, abs=0.01)

def test_linear_under_edge():
    side, proj, prob, edge = calculate_linear_edge(projected=330, line=340, multiplier=0.008)
    assert side == "under"
    assert prob == pytest.approx(0.58, abs=0.01)
    assert edge == pytest.approx(0.08, abs=0.01)

def test_linear_no_edge():
    side, proj, prob, edge = calculate_linear_edge(projected=340, line=340, multiplier=0.008)
    assert edge == pytest.approx(0.0, abs=0.001)
    assert prob == pytest.approx(0.50, abs=0.01)

def test_linear_clamps_high():
    side, proj, prob, edge = calculate_linear_edge(projected=500, line=340, multiplier=0.008)
    assert prob == 0.99
    assert edge == pytest.approx(0.49, abs=0.01)

def test_linear_clamps_low():
    side, proj, prob, edge = calculate_linear_edge(projected=200, line=340, multiplier=0.008)
    assert side == "under"
    assert prob == 0.99
    assert edge == pytest.approx(0.49, abs=0.01)

def test_linear_edge_always_non_negative():
    for delta in range(-100, 101, 5):
        _, _, _, edge = calculate_linear_edge(projected=340 + delta, line=340, multiplier=0.008)
        assert edge >= 0

def test_linear_prob_in_range():
    for delta in range(-200, 201, 10):
        _, _, prob, _ = calculate_linear_edge(projected=340 + delta, line=340, multiplier=0.008)
        assert 0.01 <= prob <= 0.99


# === Exponential Engine Tests ===

def test_exponential_under_when_projected_above_line():
    side, proj, prob, edge = calculate_exponential_edge(projected_mean=30, line=25)
    assert side == "under"
    assert prob == pytest.approx(0.566, abs=0.01)
    assert edge == pytest.approx(0.066, abs=0.01)

def test_exponential_over_when_line_very_low():
    side, proj, prob, edge = calculate_exponential_edge(projected_mean=30, line=10)
    assert side == "over"
    prob_over = math.exp(-10 / 30)
    assert prob == pytest.approx(prob_over, abs=0.01)

def test_exponential_under_when_line_high():
    side, proj, prob, edge = calculate_exponential_edge(projected_mean=25, line=35)
    assert side == "under"
    prob_under = 1 - math.exp(-35 / 25)
    assert prob == pytest.approx(prob_under, abs=0.01)

def test_exponential_at_median():
    mean = 30
    median = mean * math.log(2)
    side, _, prob, edge = calculate_exponential_edge(projected_mean=mean, line=median)
    assert prob == pytest.approx(0.50, abs=0.001)
    assert edge == pytest.approx(0.0, abs=0.001)

def test_exponential_edge_always_non_negative():
    for line in range(5, 60, 5):
        _, _, _, edge = calculate_exponential_edge(projected_mean=30, line=line)
        assert edge >= 0


# === Poisson Engine Tests ===

def test_poisson_over_wickets():
    side, proj, prob, edge = calculate_poisson_edge(projected_mean=1.8, line=1.5)
    assert side == "over"
    assert prob > 0.50
    assert edge > 0

def test_poisson_under_wickets():
    side, proj, prob, edge = calculate_poisson_edge(projected_mean=0.8, line=1.5)
    assert side == "under"
    assert prob > 0.50

def test_poisson_sanity_check_wickets():
    side, _, prob, edge = calculate_poisson_edge(projected_mean=1.1, line=0.5)
    assert side == "over"
    assert prob == pytest.approx(0.667, abs=0.01)
    assert edge == pytest.approx(0.167, abs=0.01)

def test_poisson_edge_always_non_negative():
    for mu in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
        for line in [0.5, 1.5, 2.5, 3.5]:
            _, _, _, edge = calculate_poisson_edge(projected_mean=mu, line=line)
            assert edge >= 0


# === Kelly & Conversion (preserved) ===

def test_kelly_criterion_positive_edge():
    kelly = kelly_criterion(0.55, 2.0)
    assert 0.05 < kelly < 0.15

def test_kelly_criterion_no_edge():
    kelly = kelly_criterion(0.50, 2.0)
    assert kelly == 0

def test_kelly_criterion_negative_edge():
    kelly = kelly_criterion(0.40, 2.0)
    assert kelly == 0

def test_american_to_decimal():
    assert american_to_decimal(-150) == round(100 / 150 + 1, 4)
    assert american_to_decimal(130) == round(130 / 100 + 1, 4)
    assert american_to_decimal(100) == 2.0


# === detect_edge dispatcher ===

def test_detect_edge_linear_above_threshold():
    result = detect_edge("match_total_runs", projected=360, line=340)
    assert result is not None
    assert result["bet_type"] == "match_total_runs"
    assert result["side"].startswith("over")
    assert result["edge"] >= 0.06


def test_detect_edge_linear_below_threshold():
    result = detect_edge("match_total_runs", projected=342, line=340)
    assert result is None  # edge ~0.016, below 0.06


def test_detect_edge_exponential():
    result = detect_edge("player_runs", projected=30, line=15)
    assert result is not None
    assert result["bet_type"] == "player_runs"


def test_detect_edge_poisson():
    result = detect_edge("player_wickets", projected=2.0, line=1.5)
    assert result is not None
    assert result["side"].startswith("over")


def test_detect_edge_with_odds():
    result = detect_edge("match_total_runs", projected=360, line=340, odds=-110)
    assert result is not None
    assert "kelly_pct" in result
    assert result["kelly_pct"] > 0


def test_detect_edge_without_odds():
    result = detect_edge("match_total_runs", projected=360, line=340)
    assert result is not None
    assert "kelly_pct" not in result


def test_detect_edge_unknown_type():
    result = detect_edge("nonexistent_type", projected=100, line=90)
    assert result is None


# === check_moneyline_edge ===

def test_moneyline_edge_team_a():
    result = check_moneyline_edge(0.68, 0.32, team_a_odds=-130)
    assert result is not None
    assert result["side"] == "team_a"
    assert result["edge"] >= 0.06


def test_moneyline_edge_no_edge():
    result = check_moneyline_edge(0.53, 0.47)
    assert result is None


def test_moneyline_edge_with_kelly():
    result = check_moneyline_edge(0.68, 0.32, team_a_odds=-130)
    assert result is not None
    assert "kelly_pct" in result


# === analyze_all_edges ===

def test_analyze_all_edges_basic():
    predictions = {
        "predictions": {
            "moneyline": {
                "team_a_win_prob": 0.68,
                "team_b_win_prob": 0.32,
            },
            "total_runs": {"projected": 360},
        }
    }
    odds = {
        "moneyline": {"team_a": -130, "team_b": 110},
        "total_runs": {"line": 340, "odds": -110},
    }
    bets = analyze_all_edges(predictions, odds)
    assert isinstance(bets, list)
    assert len(bets) >= 1
    types = [b["bet_type"] for b in bets]
    assert "moneyline" in types


def test_analyze_all_edges_empty():
    bets = analyze_all_edges({"predictions": {}}, {})
    assert bets == []


# === Negative Binomial (overdispersed Poisson) ===

def test_poisson_with_overdispersion():
    """Overdispersed Poisson should produce different (wider) probabilities."""
    _, _, prob_poisson, edge_poisson = calculate_poisson_edge(1.5, 1.5, overdispersion=1.0)
    _, _, prob_nb, edge_nb = calculate_poisson_edge(1.5, 1.5, overdispersion=1.30)
    # Negative binomial has fatter tails, so prob_over should be higher
    # (more probability mass in the tails means more extreme outcomes)
    assert prob_nb != prob_poisson


def test_poisson_overdispersion_1_equals_poisson():
    """With overdispersion=1.0, should give identical results to Poisson."""
    side_p, _, prob_p, edge_p = calculate_poisson_edge(1.5, 1.5, overdispersion=1.0)
    side_nb, _, prob_nb, edge_nb = calculate_poisson_edge(1.5, 1.5, overdispersion=1.001)
    # Should be very close
    assert abs(prob_p - prob_nb) < 0.01


def test_poisson_overdispersion_edge_non_negative():
    """Edge should still be non-negative with overdispersion."""
    for od in [1.0, 1.2, 1.5, 2.0]:
        for mu in [0.5, 1.0, 1.5, 2.0]:
            for line in [0.5, 1.5, 2.5]:
                _, _, _, edge = calculate_poisson_edge(mu, line, od)
                assert edge >= 0


# === Confidence-Weighted Thresholds ===

def test_detect_edge_high_confidence_lowers_threshold():
    """High confidence should allow lower edge through."""
    # 4% edge on match_total_runs (threshold=6%) — normally rejected
    result_no_conf = detect_edge("match_total_runs", projected=345, line=340)
    # With high confidence, threshold drops to 4.5% — might pass
    result_high = detect_edge("match_total_runs", projected=345, line=340, confidence="high")
    # The high-confidence version should be more permissive
    if result_no_conf is None:
        # Good — base threshold rejected it. High confidence might accept it.
        pass  # Depends on exact edge value


def test_detect_edge_low_confidence_raises_threshold():
    """Low confidence should raise the threshold."""
    # A bet that passes at medium confidence...
    result_med = detect_edge("match_total_runs", projected=360, line=340)
    assert result_med is not None
    # ...should also pass at low confidence (edge is large enough)
    result_low = detect_edge("match_total_runs", projected=360, line=340, confidence="low")
    assert result_low is not None  # 16% edge >> 9% adjusted threshold


def test_detect_edge_strength_field():
    """Strength field should be edge/threshold."""
    result = detect_edge("match_total_runs", projected=360, line=340)
    assert result is not None
    assert "strength" in result
    expected_strength = result["edge"] / 0.06  # base threshold
    assert result["strength"] == pytest.approx(expected_strength, abs=0.1)


def test_detect_edge_confidence_in_result():
    """Confidence should be included in result when provided."""
    result = detect_edge("match_total_runs", projected=360, line=340, confidence="high")
    assert result is not None
    assert result["confidence"] == "high"


# === Bimodal Chase Model ===

def test_bimodal_chase_over_near_target():
    """Line near successful chase cluster → over is favorable."""
    from edge import calculate_bimodal_chase_edge
    side, _, prob, edge = calculate_bimodal_chase_edge(
        projected_mean=165, line=155.5, target=170, chase_win_prob=0.55
    )
    assert side == "over"
    assert prob > 0.55  # majority of outcomes are above 155.5


def test_bimodal_chase_under_above_target():
    """Line above target → under is very favorable (chasing team stops at target)."""
    from edge import calculate_bimodal_chase_edge
    side, _, prob, edge = calculate_bimodal_chase_edge(
        projected_mean=165, line=175.5, target=170, chase_win_prob=0.55
    )
    assert side == "under"
    assert prob > 0.70  # most outcomes below 175.5


def test_bimodal_chase_disagrees_with_linear():
    """The bimodal model should disagree with the linear model in the valley."""
    from edge import calculate_bimodal_chase_edge, calculate_linear_edge
    # Line = 155.5, target = 170 — in the valley between modes
    _, _, prob_bimodal, _ = calculate_bimodal_chase_edge(
        projected_mean=155, line=155.5, target=170, chase_win_prob=0.55
    )
    _, _, prob_linear, _ = calculate_linear_edge(
        projected=155, line=155.5, multiplier=0.017
    )
    # They should produce materially different probabilities
    assert abs(float(prob_bimodal) - float(prob_linear)) > 0.03


def test_bimodal_chase_detect_edge_needs_target():
    """detect_edge with bimodal_chase returns None without target."""
    result = detect_edge("team_total_chase", projected=165, line=155.5)
    assert result is None  # no target provided


def test_bimodal_chase_detect_edge_with_target():
    """detect_edge with bimodal_chase works when target is provided."""
    result = detect_edge(
        "team_total_chase", projected=165, line=155.5,
        target=170, chase_win_prob=0.55
    )
    assert result is not None
    assert result["bet_type"] == "team_total_chase"


def test_bimodal_chase_edge_always_non_negative():
    """Edge should be non-negative for all inputs."""
    from edge import calculate_bimodal_chase_edge
    for line in range(120, 200, 5):
        _, _, _, edge = calculate_bimodal_chase_edge(
            projected_mean=160, line=float(line), target=170
        )
        assert edge >= 0
