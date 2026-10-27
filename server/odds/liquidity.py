"""Minimum-liquidity filter for the edge scanners.

A price's `max_stake_dollars` is the top-of-book depth at that price
(Kalshi / Polymarket US). Prices below the user's minimum are dropped
BEFORE the arb / low-hold scans so the scanner can fall back to the
next-best leg that does have depth. Prices with no depth figure
(sportsbooks, exchange rows not yet sized) always pass.
"""
from __future__ import annotations


def is_liquid(price: dict, min_dollars: float) -> bool:
    size = price.get("max_stake_dollars")
    return min_dollars <= 0 or size is None or size >= min_dollars


def filter_games_min_liquidity(games: list[dict], min_dollars: float) -> list[dict]:
    """`games` (rows_to_games shape) without prices below `min_dollars`.

    Structural sharing: games/markets/outcomes with nothing to drop are
    returned as-is, so the cost is one pass over prices plus copies of the
    few exchange-touched outcomes. Outcomes left with no prices are removed;
    `best_price` is recomputed from what remains.
    """
    if min_dollars <= 0:
        return games
    out: list[dict] = []
    for g in games:
        new_markets = None
        markets = g.get("markets") or []
        for mi, m in enumerate(markets):
            new_outcomes = None
            outcomes = m.get("outcomes") or []
            for oi, o in enumerate(outcomes):
                prices = o.get("prices") or []
                if all(is_liquid(p, min_dollars) for p in prices):
                    if new_outcomes is not None:
                        new_outcomes.append(o)
                    continue
                if new_outcomes is None:
                    new_outcomes = list(outcomes[:oi])
                kept = [p for p in prices if is_liquid(p, min_dollars)]
                if kept:
                    best = max(kept, key=lambda p: _payout(p["price_american"]))
                    new_outcomes.append({**o, "prices": kept, "best_price": best})
            if new_outcomes is None:
                if new_markets is not None:
                    new_markets.append(m)
                continue
            if new_markets is None:
                new_markets = list(markets[:mi])
            if new_outcomes:
                new_markets.append({**m, "outcomes": new_outcomes})
        out.append(g if new_markets is None else {**g, "markets": new_markets})
    return out


def _payout(american: int) -> float:
    return 1 + american / 100.0 if american > 0 else 1 + 100.0 / -american


def resolve_min_liquidity(param: float | None, settings_store) -> float:
    """Explicit query param wins; omitted = the saved Settings value."""
    if param is not None:
        return max(0.0, float(param))
    if settings_store is None:
        return 0.0
    return settings_store.get().min_liquidity_dollars
