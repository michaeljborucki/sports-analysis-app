"""Kalshi orderbook poller — periodic top-of-book depth refresh.

Runs every 60s from the lifespan scheduler. For each registered
Kalshi market (per KalshiTickerIngestor.registered_tickers), hits
GET /markets/{ticker}/orderbook, translates the response to
max_stake_dollars via orderbook_depth.max_stake_for_side, and upserts
the per-(template, side) cache row. WS ticker channel still owns
price; this owns size.

Tolerates per-market failures — one ticker's 5xx doesn't block the
rest of the cycle. Sleep between calls is a single `await asyncio.
sleep(0.05)` to stay under Kalshi's 100/sec auth'd rate limit even
for ~200-market batches.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ...cache import OddsCache
from .orderbook_depth import max_stake_for_side


logger = logging.getLogger(__name__)

_INTER_CALL_DELAY_S = 0.05


async def poll_kalshi_orderbooks(
    *, client, ingestor, cache: OddsCache,
) -> int:
    """One sync cycle. Returns count of rows updated with non-null
    max_stake_dollars. Exceptions during a single market's poll are
    logged + skipped; the rest of the batch continues."""
    tickers = ingestor.registered_tickers()
    if not tickers:
        return 0

    updated = 0
    for ticker in tickers:
        try:
            ob = await client.get_orderbook(ticker)
        except Exception:
            logger.exception(
                "kalshi orderbook poll: get failed for %s", ticker,
            )
            continue

        templates = getattr(ingestor, "_templates", {}).get(ticker, [])
        if not templates:
            continue

        now = datetime.now(timezone.utc)
        rows_to_upsert: list[dict] = []
        for template, side in templates:
            max_stake = max_stake_for_side(ob, ws_side=side)
            if max_stake is None:
                continue
            new_row = {
                **template,
                "fetched_at": template.get("fetched_at") or now,
                "max_stake_dollars": max_stake,
            }
            rows_to_upsert.append(new_row)

        if rows_to_upsert:
            try:
                cache.upsert(rows_to_upsert)
                updated += len(rows_to_upsert)
            except Exception:
                logger.exception(
                    "kalshi orderbook poll: upsert failed for %s",
                    ticker,
                )
                continue

        await asyncio.sleep(_INTER_CALL_DELAY_S)

    if updated:
        logger.info(
            "kalshi orderbook poll: %d rows refreshed", updated,
        )
    return updated
