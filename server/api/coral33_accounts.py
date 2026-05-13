"""coral33 multi-account API.

Routes:
  GET  /api/coral33/accounts          → cached roll-up (no scrape)
  POST /api/coral33/accounts/refresh  → kick off a fresh pull, async, returns 202
  GET  /api/coral33/accounts/history  → weekly P&L per account (cached)

The scraper runs serially (one account at a time, sharing a single asyncio
loop) so concurrent refresh requests collapse to one. While a pull is in
flight, `refreshing=true` is reported on the cached payload so the UI can
show a spinner.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..odds.books.coral33.accounts import (
    AccountsRollup,
    AccountsScraper,
)


class WagerSummaryModel(BaseModel):
    open_count: int
    open_amount_risked: float
    open_amount_to_win: float
    straight_count: int
    parlay_count: int
    parlay_partial_count: int
    free_play_count: int


class WagerLegModel(BaseModel):
    play_number: int
    description: str
    sport_type: str | None = None
    sport_sub_type: str | None = None
    period: str | None = None
    team1: str | None = None
    team2: str | None = None
    chosen_team: str | None = None
    final_money: int | None = None
    spread: float | None = None
    total_points: float | None = None
    game_datetime: str | None = None
    outcome: str | None = None
    leg_amount_wagered: float = 0.0
    leg_to_win_amount: float = 0.0


class PendingWagerModel(BaseModel):
    ticket_number: int
    wager_number: int
    bet_type: str
    wager_status: str | None = None
    amount_wagered: float
    to_win_amount: float
    is_free_play: bool
    accepted_at: str | None = None
    parlay_name: str | None = None
    teaser_name: str | None = None
    legs: list[WagerLegModel]
    has_open_legs: bool
    has_graded_legs: bool
    is_partial: bool


class AccountSnapshotModel(BaseModel):
    customer_id: str
    label: str
    fetched_at: str
    current_balance: float
    available_balance: float
    pending_wager_balance: float
    free_play_balance: float
    credit_limit: float
    wager_limit: float
    player_name: str | None = None
    agent_id: str | None = None
    wagers: WagerSummaryModel
    pending_wagers: list[PendingWagerModel] = []
    error: str | None = None


class AccountsRollupModel(BaseModel):
    snapshots: list[AccountSnapshotModel]
    refreshed_at: str | None
    refreshing: bool
    total_current_balance: float
    total_available_balance: float
    total_pending_balance: float
    total_free_play: float
    total_open_wagers: int
    account_count: int


def _to_model(rollup: AccountsRollup, account_count: int) -> AccountsRollupModel:
    return AccountsRollupModel(
        snapshots=[AccountSnapshotModel.model_validate(s, from_attributes=True) for s in rollup.snapshots],
        refreshed_at=rollup.refreshed_at,
        refreshing=rollup.refreshing,
        total_current_balance=rollup.total_current_balance,
        total_available_balance=rollup.total_available_balance,
        total_pending_balance=rollup.total_pending_balance,
        total_free_play=rollup.total_free_play,
        total_open_wagers=rollup.total_open_wagers,
        account_count=account_count,
    )


class RefreshResponse(BaseModel):
    status: str
    account_count: int = 0


class HistoryPointModel(BaseModel):
    date: str
    won: float
    lost: float
    net: float
    balance: float
    # Open-wager dollars at end of day. Historical days always 0 (Coral33's
    # daily-figures endpoint doesn't carry this); the latest point is
    # populated from the live AccountSnapshot via the API join below.
    pending: float = 0.0


class AccountHistoryModel(BaseModel):
    customer_id: str
    label: str
    points: list[HistoryPointModel]


class HistoryRollupModel(BaseModel):
    weeks: int
    accounts: list[AccountHistoryModel]


def build_router(scraper: AccountsScraper) -> APIRouter:
    router = APIRouter()

    @router.get("/api/coral33/accounts", response_model=AccountsRollupModel)
    async def get_accounts() -> AccountsRollupModel:
        return _to_model(scraper.cached(), len(scraper.credentials))

    @router.post(
        "/api/coral33/accounts/refresh",
        response_model=RefreshResponse,
    )
    async def refresh_accounts() -> RefreshResponse:
        result = scraper.trigger_refresh_async()
        return RefreshResponse(
            status=result["status"],
            account_count=result.get("account_count", 0),
        )

    @router.get(
        "/api/coral33/accounts/history",
        response_model=HistoryRollupModel,
    )
    async def get_history(
        weeks: int = Query(default=12, ge=1, le=52),
        force: bool = Query(default=False),
        force_wager_log: bool = Query(
            default=False,
            description=(
                "Re-run the one-time wager-log backfill. Default behavior "
                "reads from the persisted JSON cache (no API cost). Set "
                "true to refresh the cache from Coral33."
            ),
        ),
    ) -> HistoryRollupModel:
        from datetime import date as _date
        from ..odds.books.coral33.wager_log import compute_pending_by_date

        history = await scraper.get_history(weeks_back=weeks, force=force)
        creds_by_id = {c.customer_id: c for c in scraper.credentials}

        # Live pending-balance lookup from the current snapshot — overlays
        # onto today's HistoryPoint regardless of wager-log status, so the
        # rightmost bar is always accurate even before the backfill runs.
        current = scraper.cached()
        live_pending_by_cid: dict[str, float] = {
            s.customer_id: s.pending_wager_balance
            for s in current.snapshots
            if s.error is None
        }

        # Historical pending — derived once per account from the persisted
        # wager log. The log covers the last ~2 weeks (DEFAULT_BACKFILL_
        # WEEKS); points older than that stay at 0.
        wager_log = await scraper.get_wager_log(force=force_wager_log)

        accounts: list[AccountHistoryModel] = []
        for cid, points in history.items():
            cred = creds_by_id.get(cid)
            point_models = [
                HistoryPointModel.model_validate(p, from_attributes=True)
                for p in points
            ]

            # Compute per-date historical pending for this account.
            log = wager_log.get(cid) or []
            if log and point_models:
                dates = [_date.fromisoformat(p.date) for p in point_models]
                pending_by_date = compute_pending_by_date(log, dates)
                for p in point_models:
                    p.pending = pending_by_date.get(p.date, 0.0)

            # Overlay live pending onto today's point regardless — the
            # wager-log compute gives EOD-yesterday-ish for today (since
            # any wager open right now hasn't settled by EOD today either,
            # the values typically agree), but the live snapshot is more
            # authoritative for the rightmost bar.
            if point_models:
                latest = point_models[-1]
                latest.pending = live_pending_by_cid.get(
                    cid, latest.pending,
                )

            accounts.append(AccountHistoryModel(
                customer_id=cid,
                label=(cred.label if cred and cred.label else cid),
                points=point_models,
            ))
        return HistoryRollupModel(weeks=weeks, accounts=accounts)

    return router
