from __future__ import annotations


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied (vigged) probability."""
    if odds < 0:
        return -odds / (-odds + 100)
    return 100 / (odds + 100)


def american_to_decimal(odds: int) -> float:
    """American → decimal (payout multiplier on a $1 bet, INCLUDING the stake).
    +100 → 2.00, -110 → 1.909, +250 → 3.50."""
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / -odds


def implied_to_american(p: float) -> int:
    """Fair probability → American odds (rounded). Used for displaying a
    devigged fair line in the UI. Returns 0 for degenerate inputs."""
    if p <= 0.0 or p >= 1.0:
        return 0
    dec = 1.0 / p
    if dec >= 2.0:
        return round((dec - 1.0) * 100.0)
    return -round(100.0 / (dec - 1.0))


def devig_two_way(price_a: int, price_b: int) -> tuple[float, float]:
    """Remove vig from a two-way market using proportional method.
    Returns (prob_a, prob_b) summing to 1.0.
    """
    p_a = american_to_implied_prob(price_a)
    p_b = american_to_implied_prob(price_b)
    total = p_a + p_b
    return (p_a / total, p_b / total)


def devig_n_way(prices: list[int]) -> list[float]:
    """Proportional (multiplicative) devig for an n-outcome market.
    Returns a list of fair probabilities summing to 1.0 in the same order
    as the input prices. Used for soccer h2h_3_way (Home/Draw/Away) and
    any future n-way market.
    """
    if not prices:
        return []
    implied = [american_to_implied_prob(p) for p in prices]
    total = sum(implied)
    if total <= 0:
        return []
    return [x / total for x in implied]
