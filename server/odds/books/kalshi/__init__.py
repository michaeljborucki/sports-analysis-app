"""Kalshi direct-API integration — public REST, no auth, h2h-only (Phase 1).

Replaces the Odds API's `bookmaker_key="kalshi"` rows with a direct poll of
api.elections.kalshi.com — ~15s freshness instead of 2-5min stale.
"""
from .client import KalshiAPIError, KalshiClient
from .event_matcher import KalshiEventMatcher
from .fetcher import KalshiFetcher
from .mapping import (
    KalshiConfig,
    SERIES_TO_SPORT_MARKET,
    TEAM_CODE_TO_CANONICAL,
    load_kalshi_config,
)

__all__ = [
    "KalshiAPIError",
    "KalshiClient",
    "KalshiConfig",
    "KalshiEventMatcher",
    "KalshiFetcher",
    "SERIES_TO_SPORT_MARKET",
    "TEAM_CODE_TO_CANONICAL",
    "load_kalshi_config",
]
