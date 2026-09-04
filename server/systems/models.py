from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


EvaluationStatus = Literal[
    "qualified", "no_match", "no_slate", "unable_to_evaluate", "disabled"
]


class EvaluationGame(BaseModel):
    event_id: str
    sport: Literal["mlb", "ncaaf", "nfl"]
    home_team: str
    away_team: str
    commence_time: datetime
    data_timestamp: datetime
    context: dict[str, Any] = Field(default_factory=dict)


class SystemSignal(BaseModel):
    system_id: str
    system_name: str
    sport: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    bet_type: Literal["spread", "total", "moneyline"]
    selection: str
    market_line: float | int | None = None
    # Coral33's price for this selection, and the book it came from
    # ("coral33"). None means Coral33 is not offering it — never the
    # market-best substitute, which cannot be placed.
    price_american: int | None = None
    book: str | None = None
    qualification_reason: str
    data_timestamp: datetime
    evaluated_at: datetime


class SystemEvaluation(BaseModel):
    system_id: str
    short_id: str
    system_name: str
    sport: str
    bet_type: str
    source_claim: str
    rule_status: str
    status: EvaluationStatus
    match_count: int = 0
    # Coverage, so partial data reads as partial rather than as total failure:
    # how many applicable games the rule actually judged, and how many it had
    # to skip for want of a required field.
    evaluated_games: int = 0
    skipped_games: int = 0
    missing_fields: list[str] = Field(default_factory=list)


class WagerCandidate(BaseModel):
    sport: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    bet_type: str
    selection: str
    market_line: float | int | None = None
    # Coral33's price for this selection, and the book it came from
    # ("coral33"). None means Coral33 is not offering it — never the
    # market-best substitute, which cannot be placed.
    price_american: int | None = None
    book: str | None = None
    qualification_reason: str
    data_timestamp: datetime
    supporting_system_ids: list[str]
    supporting_system_names: list[str]


class EvaluationResult(BaseModel):
    evaluations: list[SystemEvaluation]
    signals: list[SystemSignal]


class SystemsSummary(BaseModel):
    qualifying_systems: int
    qualifying_wagers: int
    no_match: int
    no_slate: int
    unable_to_evaluate: int
    disabled: int


class SystemsResponse(BaseModel):
    requested_date: date
    timeframe: Literal["today", "tomorrow", "upcoming", "date"]
    timezone: str
    evaluated_at: datetime
    evaluations: list[SystemEvaluation]
    signals: list[SystemSignal]
    wagers: list[WagerCandidate]
    summary: SystemsSummary
    context_warnings: list[str] = Field(default_factory=list)
