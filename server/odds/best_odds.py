from __future__ import annotations

from statistics import median

from .devig import american_to_implied_prob


def _american_to_payout_multiplier(odds: int) -> float:
    """Higher = better for the bettor. Used for comparison only."""
    if odds > 0:
        return 1 + odds / 100.0
    return 1 + 100.0 / (-odds)


def pick_best_price(prices: list[tuple[str, int]]) -> tuple[str, int] | None:
    """Given [(bookmaker_key, american_odds), ...] pick the best payout for the bettor."""
    if not prices:
        return None
    return max(prices, key=lambda p: _american_to_payout_multiplier(p[1]))


def best_price_dict(prices: list[dict]) -> dict | None:
    """Pick the dict from `prices` whose `price_american` gives the
    highest payout multiplier to the bettor. Returns None for an empty
    list.

    Coexists with `pick_best_price` (tuple API, retained for callers
    that work with (bookmaker_key, american_odds) tuples). This dict
    API saves the redundant linear scan in `rows_to_games` to recover
    the original dict from a (book, price) tuple match.
    """
    if not prices:
        return None
    return max(prices, key=lambda p: _american_to_payout_multiplier(p["price_american"]))


def _prob_to_american(p: float) -> int:
    if p <= 0 or p >= 1:
        return 0
    if p >= 0.5:
        return round(-p / (1 - p) * 100)
    return round((1 - p) / p * 100)


def median_american_odds(prices: list[int]) -> int | None:
    """Median in implied-probability space, converted back to American."""
    if not prices:
        return None
    probs = sorted(american_to_implied_prob(p) for p in prices)
    return _prob_to_american(median(probs))
