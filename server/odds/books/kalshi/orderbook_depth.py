"""Kalshi orderbook response → max_stake_dollars translator.

Kalshi's /markets/{ticker}/orderbook returns each side's BIDS — `yes`
is people bidding to buy YES; `no` is people bidding to buy NO. A
taker filling YES at the best ask is equivalent to taking the best
NO bid (since YES_ask_cents = 100 - NO_bid_cents). This module owns
that inversion + size lookup, isolated so it can be unit-tested
without the rest of the WS stack.

Tolerates both array-of-pairs (`[[price, size], ...]`) and
array-of-dicts (`[{"price": ..., "size": ...}, ...]`) formats since
Kalshi's docs and live samples occasionally differ.
"""
from __future__ import annotations

import logging
from typing import Iterable


logger = logging.getLogger(__name__)


def _highest_price_entry(entries: Iterable) -> tuple[int, float] | None:
    """Walk a side's bid list; return (price_cents, size_contracts) of
    the highest-price entry. Returns None if empty or unparseable."""
    best_p: int | None = None
    best_s: float | None = None
    if entries is None:
        return None
    for raw in entries:
        try:
            if isinstance(raw, dict):
                p = int(raw.get("price"))
                s = float(raw.get("size"))
            else:
                p = int(raw[0])
                s = float(raw[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if not (0 < p < 100):
            continue
        if s <= 0:
            continue
        if best_p is None or p > best_p:
            best_p = p
            best_s = s
    if best_p is None or best_s is None:
        return None
    return best_p, best_s


def max_stake_for_side(
    orderbook_response: dict | None, *, ws_side: str,
) -> float | None:
    """Compute max_stake_dollars at the best ask for a given side.

    For ws_side='yes', use the opposite side's best bid (NO bids) and
    invert: yes_ask = 100 - no_bid_cents; size = that no_bid's size.
    For ws_side='no', symmetric using YES bids.

    Returns the dollar amount fillable at the displayed price, or
    None when the orderbook is empty / malformed / one-sided.
    """
    if not isinstance(orderbook_response, dict):
        return None
    ob = orderbook_response.get("orderbook")
    if not isinstance(ob, dict):
        return None
    opposite_side = "no" if ws_side == "yes" else "yes"
    best = _highest_price_entry(ob.get(opposite_side))
    if best is None:
        return None
    opposite_bid_cents, size = best
    inferred_ask_cents = 100 - opposite_bid_cents
    if inferred_ask_cents <= 0:
        return None
    return round(inferred_ask_cents / 100.0 * size, 2)
