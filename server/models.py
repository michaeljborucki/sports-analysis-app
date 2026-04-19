from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

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


class PickTier(str, Enum):
    HIGH = "high"
    SWEET = "sweet"
    LEAN = "lean"


class PickStat(BaseModel):
    label: str
    value: str


class Pick(BaseModel):
    id: str
    tier: PickTier
    game_label: str
    market_label: str
    pick_side: str
    odds_american: int
    best_book: str | None = None
    stake_units: float
    probability_pct: float
    market_probability_pct: float
    edge_pct: float
    stats: list[PickStat] = Field(default_factory=list)
    reasoning: str
    agent_key: str = "baseball-agents"
    agent_record_30d: str = ""
    commence_time: datetime | None = None


class PicksResponse(BaseModel):
    picks: list[Pick]
    status: Literal["ok", "no_picks_today"]
    last_checked_at: datetime
    bet_card_date: str | None = None


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
