"""HTTP endpoints for the unified bet tracker.

  GET  /api/bets                  — list with filters + CLV per row
  GET  /api/bets/rollups          — 30d/90d/lifetime + by_book/sport/market
  POST /api/bets/import           — CSV upload
  GET  /api/bets/import/template  — example CSV download
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, UploadFile, File
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from ..odds.bets import query_bets, rollups, upsert_bets
from ..odds.bets_csv import parse_csv_to_bet_rows
from ..odds.cache import OddsCache
from ..odds.clv import lookup_clv_for_bet


logger = logging.getLogger(__name__)


class BetModel(BaseModel):
    source_book: str
    external_id: str
    customer_id: str | None = None
    accepted_at: datetime
    settled_at: datetime | None = None
    status: str
    wager_type: str
    total_picks: int
    sport_key: str | None = None
    event_id: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    market_key: str | None = None
    outcome_name: str | None = None
    outcome_point: float = 0.0
    odds_american: int | None = None
    stake: float
    to_win: float | None = None
    settled_amount: float | None = None
    is_free_play: bool = False
    raw_description: str | None = None
    clv_pct: float | None = None


class BetsResponse(BaseModel):
    bets: list[BetModel]
    total_count: int


class WindowRollup(BaseModel):
    count: int
    wagered: float
    net: float
    roi_pct: float


class GroupRollup(BaseModel):
    source_book: str | None = None
    sport_key: str | None = None
    market_key: str | None = None
    count: int
    wagered: float
    net: float
    roi_pct: float


class RollupsResponse(BaseModel):
    window_30d: WindowRollup
    window_90d: WindowRollup
    lifetime: WindowRollup
    by_book: list[GroupRollup]
    by_sport: list[GroupRollup]
    by_market: list[GroupRollup]


class ImportResponse(BaseModel):
    accepted: int
    rejected: list[dict]


def _attach_clv(rows: list[dict], cache: OddsCache) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        clv_pct: float | None = None
        try:
            res = lookup_clv_for_bet(r, cache)
            if res is not None:
                clv_pct = round(res.clv_pct * 100.0, 2)
        except Exception:
            logger.exception("CLV lookup failed for bet %s:%s",
                             r.get("source_book"), r.get("external_id"))
        r = {**r, "is_free_play": bool(r.get("is_free_play")), "clv_pct": clv_pct}
        out.append(r)
    return out


_TEMPLATE_CSV = (
    "date,book,sport,event,market,side,odds,stake,result\n"
    "2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W\n"
    "2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending\n"
    "2026-06-20,Pinnacle,tennis,Sinner vs Alcaraz,h2h,Alcaraz,+105,100,L\n"
)


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/bets", response_model=BetsResponse)
    def get_bets(
        status: Optional[str] = Query(default=None, description="open|win|loss|push|void|pending"),
        book: Optional[str] = Query(default=None),
        sport: Optional[str] = Query(default=None),
        market_key: Optional[str] = Query(default=None),
        from_: Optional[str] = Query(default=None, alias="from"),
        to: Optional[str] = Query(default=None),
        limit: Optional[int] = Query(default=None, ge=1, le=10000),
    ) -> BetsResponse:
        rows = query_bets(
            cache,
            book=book, sport=sport, status=status, market_key=market_key,
            from_iso=from_, to_iso=to, limit=limit,
        )
        rows = _attach_clv(rows, cache)
        return BetsResponse(
            bets=[BetModel.model_validate(r) for r in rows],
            total_count=len(rows),
        )

    @router.get("/api/bets/rollups", response_model=RollupsResponse)
    def get_rollups() -> RollupsResponse:
        return RollupsResponse.model_validate(rollups(cache))

    @router.post("/api/bets/import", response_model=ImportResponse)
    async def post_import(file: UploadFile = File(...)) -> ImportResponse:
        body = (await file.read()).decode("utf-8", errors="replace")
        rows, errors = parse_csv_to_bet_rows(io.StringIO(body))
        # Coral33 ticket collisions: the mirror is authoritative.
        coral33_ids = {
            r["external_id"] for r in query_bets(cache, book="coral33", limit=10000)
        }
        filtered_errors = list(errors)
        accepted: list = []
        for i, r in enumerate(rows, start=2):
            if r.external_id in coral33_ids:
                filtered_errors.append({
                    "row": i,
                    "reason": "external_id collides with an existing coral33 ticket",
                })
                continue
            accepted.append(r)
        if accepted:
            upsert_bets(cache, accepted)
        return ImportResponse(accepted=len(accepted), rejected=filtered_errors)

    @router.get("/api/bets/import/template")
    def get_template() -> Response:
        return PlainTextResponse(
            _TEMPLATE_CSV,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="bets-template.csv"'},
        )

    return router
