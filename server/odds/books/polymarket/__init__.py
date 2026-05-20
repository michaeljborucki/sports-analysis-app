"""Polymarket direct-API integration — public REST + WebSocket, no auth.

Phase 1: per-game h2h moneylines for NBA / MLB / NHL.

Polymarket exposes prediction-market YES/NO contracts for each game outcome.
The two outcomes per event correspond to the two teams; the YES decimal
price for outcome i is the implied probability for that side, mapped to
American odds via the same `yes_to_american` scheme as Kalshi.

Replaces nothing — adds Polymarket alongside Odds API / Coral33 / Kalshi.
"""
from .client import PolymarketAPIError, PolymarketClient
from .event_matcher import PolymarketEventMatcher
from .fetcher import PolymarketFetcher
from .mapping import (
    PolymarketConfig,
    PolymarketSportConfig,
    TEAM_CODE_TO_CANONICAL,
    load_polymarket_config,
)

__all__ = [
    "PolymarketAPIError",
    "PolymarketClient",
    "PolymarketConfig",
    "PolymarketEventMatcher",
    "PolymarketFetcher",
    "PolymarketSportConfig",
    "TEAM_CODE_TO_CANONICAL",
    "load_polymarket_config",
]
