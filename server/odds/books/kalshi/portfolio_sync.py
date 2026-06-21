"""Kalshi portfolio sync — fills → unified bets table.

Periodic 5-min task (wired into clv_scheduler in a later step).
Pulls /portfolio/fills via the existing KalshiClient (auth required),
translates each fill into a BetRow, upserts. Idempotent on
(source_book='kalshi', external_id=fill_id).

Outcome address (event_id / market_key / outcome_name) resolution via
kalshi/event_matcher.py is a follow-up — for now event_id stays NULL
and CLV is unavailable on these rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...bets import BetRow, upsert_bets
from ...cache import OddsCache


logger = logging.getLogger(__name__)


def _price_to_american(price_cents: int, side: str) -> int | None:
    """Kalshi prices are in cents (0-99). Buyer paid `price_cents/100`
    per contract, wins $1.00 if the bet resolves their way → implied
    probability is price/100. Convert to American odds the bettor
    effectively took."""
    if not (0 < price_cents < 100):
        return None
    p = price_cents / 100.0
    if p < 0.5:
        return int(round((1 / p - 1) * 100))
    else:
        return int(round(-p / (1 - p) * 100))


def _fill_status(fill: dict) -> str:
    """Kalshi fills are placement events; resolution comes later via
    /portfolio/positions. New fills enter as 'open'; subsequent syncs
    upgrade them once settlement_outcome is populated."""
    if fill.get("settled"):
        outcome = fill.get("settlement_outcome")
        if outcome == "win":
            return "win"
        if outcome == "loss":
            return "loss"
    return "open"


async def sync_kalshi_fills(
    *, client, cache: OddsCache,
    settings_store=None,
) -> int:
    """One sync cycle. Returns rows upserted (0 if no fills or
    unauthed). Tolerates auth being unconfigured — the wrapper task
    checks client.is_authenticated and skips this call if not."""
    try:
        fills = await client.get_portfolio_fills()
    except Exception:
        logger.exception("kalshi portfolio sync: get_portfolio_fills failed")
        return 0

    if not fills:
        return 0

    rows: list[BetRow] = []
    for f in fills:
        fill_id = f.get("fill_id") or f.get("trade_id")
        if not fill_id:
            continue
        price = f.get("price")
        count = f.get("count")
        side = (f.get("side") or "yes").lower()
        if price is None or count is None:
            continue
        odds = _price_to_american(int(price), side)
        stake = round(int(price) / 100.0 * int(count), 2)
        ts_raw = f.get("created_time") or f.get("trade_time") or f.get("ts")
        try:
            accepted_at = datetime.fromisoformat(
                str(ts_raw).replace("Z", "+00:00")
            ) if ts_raw else datetime.now(timezone.utc)
        except ValueError:
            accepted_at = datetime.now(timezone.utc)

        # TODO(#11-followup): resolve event_id via kalshi/event_matcher.py
        rows.append(BetRow(
            source_book="kalshi",
            external_id=str(fill_id),
            customer_id=None,
            accepted_at=accepted_at,
            settled_at=None,
            status=_fill_status(f),
            wager_type="straight",
            total_picks=1,
            sport_key=None,
            event_id=None,
            home_team=None,
            away_team=None,
            market_key="h2h",
            outcome_name=side.upper(),
            outcome_point=0.0,
            odds_american=odds,
            stake=stake,
            to_win=round(int(count) - stake, 2),
            settled_amount=None,
            is_free_play=False,
            raw_description=f.get("ticker"),
            imported_at=None,
        ))

    if not rows:
        return 0
    return upsert_bets(cache, rows)
