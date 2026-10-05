from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BookPrice(BaseModel):
    bookmaker_key: str
    price_american: int
    point: float | None = None
    fetched_at: datetime


class MarketOutcome(BaseModel):
    outcome_name: str
    prices: list[BookPrice]
    best_price: BookPrice | None = None
    consensus_price_american: int | None = None


class Market(BaseModel):
    market_key: str
    outcomes: list[MarketOutcome]


class Game(BaseModel):
    event_id: str
    sport_key: str = "mlb"
    league_key: str | None = None
    league_title: str | None = None
    home_team: str
    away_team: str
    commence_time: datetime
    is_live: bool = False
    markets: list[Market]
    stale_seconds: int = 0


class OddsResponse(BaseModel):
    games: list[Game]
    stale_seconds: int
    fetched_at: datetime


class FetcherStatus(BaseModel):
    last_fetch_at: datetime | None = None
    requests_used: int | None = None
    requests_remaining: int | None = None
    last_error: str | None = None
    fetcher_running: bool = False
    enabled_tiers: list[str] = Field(default_factory=list)


class FetcherControlResponse(BaseModel):
    status: str
    tiers: list[str] = Field(default_factory=list)
    retry_after_seconds: int | None = None
    event_id: str | None = None
    polled: list[str] = Field(default_factory=list)
