"""Virtual books and venue identity.

`novig_maker` is not a book you can take a price from: it is the price you
would POST on Novig — one tick better than the current best bid on that
outcome (or joining the bid when the spread is a single tick). The Novig
fetcher writes those quotes as their own rows so the existing scanners can
find edges that only exist if your resting order fills.

Two rules keep the virtual book from leaking into anything else:

  * OPT-IN: a scanner considers an opt-in book only when the request's
    books filter names it explicitly. `books_filter=None` ("all books")
    excludes it, so the odds/props grids, CLV, dashboards and every caller
    that doesn't know about maker pricing behave exactly as before.
  * VENUE: a maker quote and a take quote on the same exchange are one
    venue. Pairing them (or two maker quotes) isn't an arb — it's your own
    bid against the book's other side — so two-leg scanners require
    distinct venues, not just distinct book keys.
"""
from __future__ import annotations

from typing import Iterable


OPT_IN_BOOKS: frozenset[str] = frozenset({"novig_maker"})

_VENUE: dict[str, str] = {"novig_maker": "novig"}

# Taker book → its maker counterpart (and back), for showing both prices.
MAKER_OF: dict[str, str] = {"novig": "novig_maker"}
TAKER_OF: dict[str, str] = {v: k for k, v in MAKER_OF.items()}


def venue(book: str) -> str:
    return _VENUE.get(book, book)


def book_allowed(book: str, books_filter: Iterable[str] | None) -> bool:
    if book in OPT_IN_BOOKS:
        return books_filter is not None and book in books_filter
    return books_filter is None or book in books_filter
