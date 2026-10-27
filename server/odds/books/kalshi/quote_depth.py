"""Kalshi top-of-book quote → (price, max_stake_dollars) per side.

A REST `/markets` item and a WS `ticker` message carry the same quote
fields, so one helper serves both:

  * YES is bought at `yes_ask_dollars`; `yes_ask_size_fp` contracts rest there.
  * NO is bought by hitting the best YES bid: NO ask = 1 - `yes_bid_dollars`,
    with `yes_bid_size_fp` contracts available.

`max_stake_dollars` = ask price x contracts at that price (what a taker can
spend at the displayed price), the same figure the old REST orderbook poller
derived. That poller was retired 2026-10-24: Kalshi moved the orderbook
response to `orderbook_fp` and it had silently written nothing since, while
these quote fields were already arriving on every market and every tick.
"""
from __future__ import annotations


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def ask_dollars(quote: dict, *, side: str) -> float | None:
    """Best ask for `side` in dollars (0..1), or None when there is none."""
    if side == "yes":
        ask = _num(quote.get("yes_ask_dollars"))
    else:
        bid = _num(quote.get("yes_bid_dollars"))
        ask = None if bid is None else round(1.0 - bid, 4)
    if ask is None or not (0.0 < ask < 1.0):
        return None
    return ask


def max_stake_from_quote(quote: dict, *, side: str) -> float | None:
    """Dollars fillable at `side`'s best ask, or None when the quote has no
    size figure (or no ask)."""
    ask = ask_dollars(quote, side=side)
    size = _num(quote.get("yes_ask_size_fp" if side == "yes" else "yes_bid_size_fp"))
    if ask is None or size is None or size <= 0:
        return None
    return round(ask * size, 2)
