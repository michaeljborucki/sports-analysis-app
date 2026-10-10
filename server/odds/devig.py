from __future__ import annotations

import functools


# Pure arithmetic over bounded American-odds integers (typically
# -1000..+1000), called thousands of times per EV scan during devig.
# A small LRU cache turns the inner loop into a dict lookup — maxsize
# 4096 comfortably covers the full common range with hits to spare.
@functools.lru_cache(maxsize=4096)
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


# Devig method: POWER (fair_i = implied_i ** k with sum(fair) = 1), not
# proportional. Proportional scaling leaves the favourite-longshot bias in:
# it gives longshots too much probability (Clarke, Kovalchik & Ingram 2017;
# power beat proportional in every dataset tested). At -110/-110 both give
# 0.500; at +600/-1000 the longshot goes 13.6% -> 10.5%. Switched
# 2026-10-10 (novig-maker strategy plan B1).
@functools.lru_cache(maxsize=8192)
def _power_devig(implied: tuple[float, ...]) -> tuple[float, ...]:
    total = sum(implied)
    if total <= 1.0 + 1e-12 or any(p <= 0.0 or p >= 1.0 for p in implied):
        # No overround (or degenerate input): plain normalisation.
        return tuple(p / total for p in implied) if total > 0 else ()
    lo, hi = 1.0, 2.0
    while sum(p ** hi for p in implied) > 1.0 and hi < 1e4:
        hi *= 2.0
    for _ in range(60):
        k = (lo + hi) / 2.0
        if sum(p ** k for p in implied) > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2.0
    fair = [p ** k for p in implied]
    s = sum(fair)
    return tuple(f / s for f in fair)


def devig_two_way(price_a: int, price_b: int) -> tuple[float, float]:
    """Remove vig from a two-way market (power method).
    Returns (prob_a, prob_b) summing to 1.0.
    """
    p_a, p_b = _power_devig((american_to_implied_prob(price_a), american_to_implied_prob(price_b)))
    return (p_a, p_b)


def devig_n_way(prices: list[int]) -> list[float]:
    """Power devig for an n-outcome market. Returns fair probabilities
    summing to 1.0 in the same order as the input prices. Used for soccer
    h2h_3_way (Home/Draw/Away) and any future n-way market.
    """
    if not prices:
        return []
    return list(_power_devig(tuple(american_to_implied_prob(p) for p in prices)))
