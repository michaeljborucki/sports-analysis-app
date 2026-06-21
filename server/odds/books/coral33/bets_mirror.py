"""Coral33 wager log → unified bets table mirror.

The wager log JSON files (per customer_id under server/data/
coral33_wager_log/) are the scrape cache — authoritative for what
Coral33 has reported. This module mirrors them into the unified
`bets` table so the /bets endpoint can return them alongside Kalshi,
Polymarket, and imported rows from a single source.

Called from the existing 30-min wager-log refresh tick in main.py.
No new HTTP traffic — purely a DB→DB copy.
"""
from __future__ import annotations

import logging
from typing import Iterable

from ...bets import BetRow, upsert_bets
from ...cache import OddsCache
from ...clv import get_coral33_config, wager_to_market_lookup
from .wager_log import WagerLogEntry


logger = logging.getLogger(__name__)


# Coral33 wager_status codes → unified status values.
_STATUS_MAP = {
    "O": "open",
    "W": "win",
    "L": "loss",
    "P": "push",
    "X": "void",
}


# Coral33 wager_type codes → unified wager_type values.
_WAGER_TYPE_MAP = {
    "S": "straight",
    "P": "parlay",
    "T": "teaser",
    "I": "if_bet",
    "R": "round_robin",
    "M": "straight",
}


def _to_bet_row(w: WagerLogEntry, customer_id: str, cache: OddsCache) -> BetRow:
    """Translate a WagerLogEntry → BetRow. Resolves event_id /
    market_key / outcome address by reusing wager_to_market_lookup,
    so the resulting row carries the CLV-ready address."""
    status = _STATUS_MAP.get(w.wager_status, "open")
    settled_amount: float | None
    if status == "win":
        settled_amount = float(w.amount_wagered + w.amount_won)
    elif status == "loss":
        settled_amount = 0.0
    elif status == "push":
        settled_amount = float(w.amount_wagered)
    elif status == "void":
        settled_amount = float(w.amount_wagered)
    else:
        settled_amount = None

    sport_key: str | None = None
    event_id: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    market_key: str | None = None
    outcome_name: str | None = None
    outcome_point: float = 0.0
    try:
        config, reverse = get_coral33_config()
        lookup = wager_to_market_lookup(w, cache, config, reverse)
        if lookup is not None:
            sport_key = lookup.sport_key
            event_id = lookup.event_id
            home_team = lookup.canonical_home
            away_team = lookup.canonical_away
            market_key = lookup.market_key
            outcome_name = lookup.outcome_name
            outcome_point = lookup.outcome_point
    except Exception:
        logger.exception("coral33 mirror: market lookup failed for ticket %s", w.ticket_number)

    return BetRow(
        source_book="coral33",
        external_id=str(w.ticket_number),
        customer_id=customer_id,
        accepted_at=w.accepted_at,
        settled_at=w.settled_at,
        status=status,
        wager_type=_WAGER_TYPE_MAP.get(w.wager_type, "straight"),
        total_picks=w.total_picks,
        sport_key=sport_key,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        market_key=market_key,
        outcome_name=outcome_name,
        outcome_point=outcome_point,
        odds_american=w.final_money,
        stake=float(w.amount_wagered),
        to_win=float(w.to_win_amount),
        settled_amount=settled_amount,
        is_free_play=bool(w.is_free_play),
        raw_description=w.description,
        imported_at=None,
    )


def mirror_coral33_wager_log_to_bets(
    cache: OddsCache,
    wagers_by_cid: dict[str, Iterable[WagerLogEntry]],
) -> int:
    """Mirror every wager across all accounts into the bets table.

    Idempotent — re-runs produce the same end state. Status / settled
    fields update on re-mirror; accepted_at stays put.

    Returns total rows upserted.
    """
    rows: list[BetRow] = []
    for cid, wagers in wagers_by_cid.items():
        for w in wagers:
            rows.append(_to_bet_row(w, cid, cache))
    if not rows:
        return 0
    return upsert_bets(cache, rows)
