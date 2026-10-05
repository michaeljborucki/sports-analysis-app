"""Novig direct-API integration — public REST order books, read-only.

Novig is a peer-to-peer exchange. Its Odds API copy carries one take price
per outcome and no size; this fetcher reads the order book itself and
overrides those rows (same PK) with fresher take prices plus the size
available at them. No key, no signing, no placement.
"""
from .client import NovigAPIError, NovigClient
from .fetcher import NovigFetcher
