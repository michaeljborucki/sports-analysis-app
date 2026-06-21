"""Polymarket portfolio sync — wallet trades → unified bets table.

Periodic 5-min task. Uses the public data-api.polymarket.com/trades
endpoint keyed by wallet address (no auth). Translates each trade
into a BetRow.

Polymarket fills are tied to on-chain wallets, so wallet_address is
required. If unconfigured in user_settings, the task no-ops.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...bets import BetRow, upsert_bets
from ...cache import OddsCache


logger = logging.getLogger(__name__)


def _prob_to_american(p: float) -> int | None:
    """0 < p < 1 → American odds for the contract buyer."""
    if not (0 < p < 1):
        return None
    if p < 0.5:
        return int(round((1 / p - 1) * 100))
    return int(round(-p / (1 - p) * 100))


async def sync_polymarket_trades(
    *, client, cache: OddsCache, wallet_address: str,
) -> int:
    """One sync cycle. Returns rows upserted (0 if wallet empty)."""
    if not wallet_address:
        return 0

    try:
        trades = await client.get_user_trades(wallet_address)
    except Exception:
        logger.exception("polymarket sync: get_user_trades failed")
        return 0

    if not trades:
        return 0

    rows: list[BetRow] = []
    for t in trades:
        trade_id = t.get("trade_id") or t.get("transaction_hash")
        if not trade_id:
            continue
        try:
            price = float(t.get("price") or 0)
            size = float(t.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue

        ts_raw = t.get("timestamp") or t.get("created_at")
        try:
            accepted_at = datetime.fromisoformat(
                str(ts_raw).replace("Z", "+00:00")
            ) if ts_raw else datetime.now(timezone.utc)
        except ValueError:
            accepted_at = datetime.now(timezone.utc)

        side = (t.get("side") or "BUY").upper()
        if side == "SELL":
            # TODO(#11-followup): treat SELL as an early-exit settlement.
            continue

        odds = _prob_to_american(price)
        stake = round(price * size, 2)
        to_win = round(size - stake, 2)

        # TODO(#11-followup): resolve event_id via polymarket/event_matcher.py.
        rows.append(BetRow(
            source_book="polymarket",
            external_id=str(trade_id),
            customer_id=None,
            accepted_at=accepted_at,
            settled_at=None,
            status="open",
            wager_type="straight",
            total_picks=1,
            sport_key=None,
            event_id=None,
            home_team=None,
            away_team=None,
            market_key="h2h",
            outcome_name=t.get("outcome"),
            outcome_point=0.0,
            odds_american=odds,
            stake=stake,
            to_win=to_win,
            settled_amount=None,
            is_free_play=False,
            raw_description=t.get("market"),
            imported_at=None,
        ))

    if not rows:
        return 0
    return upsert_bets(cache, rows)
