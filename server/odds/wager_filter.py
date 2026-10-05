"""Shared Coral33 wager-type (straight/parlay) filter for edge scanners.

`wager_type` is a Coral33-only single-line eligibility tag: which betslip
tab (straight / parlay / both) the line is offered on. It is NULL for every
other book — all Odds-API books are inherently straight-bettable and never
parlay-eligible on their own.

For the paired modes (arb, low-hold, free-bet) a "parlay" can't span two
different books, so the only coherent meaning — and the one the EV scanner
already uses (see server/api/ev.py) — keys off each opportunity's Coral33
leg(s):

  straight — keep unless a Coral33 leg is parlay-only. Non-Coral33 legs
             always pass (they're always straight-bettable).
  parlay   — keep ONLY opportunities with a Coral33 leg that is parlay-
             eligible (wager_type in {parlay, both}). Everything else is
             dropped, since you can't parlay a non-Coral33 line.
  any      — no filter.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


def normalize_wager_filter(raw: str) -> str:
    return raw if raw in ("any", "straight", "parlay") else "any"


def _leg_straight_ok(book: str | None, wager_type: str | None) -> bool:
    # Non-coral33 books are always straight-bettable; a coral33 leg passes
    # only if its line is offered on the straight tab (straight or both).
    return book != "coral33" or wager_type in ("straight", "both")


def _leg_parlay_ok(book: str | None, wager_type: str | None) -> bool:
    return book == "coral33" and wager_type in ("parlay", "both")


def legs_pass_wager_filter(
    legs: Sequence[Mapping[str, object]], wf: str
) -> bool:
    """Whether an opportunity passes the filter, given its priced legs.

    Each leg is a mapping carrying at least `book` and `wager_type` keys.
    """
    if wf == "straight":
        # Drop only if some coral33 leg is parlay-only.
        return all(
            _leg_straight_ok(l.get("book"), l.get("wager_type")) for l in legs  # type: ignore[arg-type]
        )
    if wf == "parlay":
        # At least one coral33 leg must be parlay-eligible.
        return any(
            _leg_parlay_ok(l.get("book"), l.get("wager_type")) for l in legs  # type: ignore[arg-type]
        )
    return True
