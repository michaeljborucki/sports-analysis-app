from __future__ import annotations


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied (vigged) probability."""
    if odds < 0:
        return -odds / (-odds + 100)
    return 100 / (odds + 100)


def devig_two_way(price_a: int, price_b: int) -> tuple[float, float]:
    """Remove vig from a two-way market using proportional method.
    Returns (prob_a, prob_b) summing to 1.0.
    """
    p_a = american_to_implied_prob(price_a)
    p_b = american_to_implied_prob(price_b)
    total = p_a + p_b
    return (p_a / total, p_b / total)
