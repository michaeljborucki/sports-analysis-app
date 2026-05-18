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

from datetime import datetime

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


class BetEntryModel(BaseModel):
    """One ticket on the bet-history table. Parlays/teasers are flattened
    to a single row representing the HEAD leg per the product spec —
    `total_picks` tells the UI to render a "PARLAY ×N" chip."""
    customer_id: str
    account_label: str
    ticket_number: int
    accepted_at: datetime
    settled_at: datetime | None = None
    wager_status: str
    wager_type: str
    total_picks: int

    amount_wagered: float
    to_win_amount: float
    amount_won: float
    amount_lost: float
    is_free_play: bool

    # Head-leg market detail
    sport_type: str | None = None
    sport_sub_type: str | None = None
    period: str | None = None
    team1_id: str | None = None
    team2_id: str | None = None
    chosen_team_id: str | None = None
    description: str | None = None
    final_money: int | None = None
    adj_spread: float | None = None
    adj_total_points: float | None = None

    # CLV placeholder — populated once we wire closing-line snapshots.
    # Null means "not yet computed" rather than "no edge".
    clv_pct: float | None = None


class BetsResponse(BaseModel):
    bets: list[BetEntryModel]
    total_count: int
    backfill_weeks: int


def build_router(
    scraper: AccountsScraper,
    cache=None,
    odds_client=None,
) -> APIRouter:
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

            # Overlay imported balance snapshots — last-write-wins per
            # local date. This fills pending for dates OUTSIDE the wager-
            # log's 2-week window (where the wager-log compute returns
            # 0). For dates within the window, the snapshot value
            # overrides the wager-log value since the snapshot is a
            # direct measurement from Coral33 itself (no derivation).
            if cache is not None:
                snap_by_date = cache.latest_balance_snapshot_per_date(cid)
                if snap_by_date and point_models:
                    for p in point_models:
                        s = snap_by_date.get(p.date)
                        if s is not None:
                            p.pending = float(s["pending"])

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

    @router.get(
        "/api/coral33/accounts/bets",
        response_model=BetsResponse,
    )
    async def get_bets(
        status: str = Query(
            default="any",
            description="any | open | settled (graded W/L/P/X)",
        ),
        force_wager_log: bool = Query(default=False),
    ) -> BetsResponse:
        """Flat bet-history across all accounts, one row per ticket.

        Backed by the same wager-log cache that powers historical
        pending. Parlays/teasers are collapsed to their head leg before
        persistence, so this endpoint trivially returns one row per
        ticket.

        Sorted by accepted_at descending (newest first). Filters apply
        in-memory — the dataset is small (~hundreds of tickets across
        the 2-week window).
        """
        from ..odds.books.coral33.wager_log import DEFAULT_BACKFILL_WEEKS
        from ..odds.clv import get_coral33_config, lookup_clv

        creds_by_id = {c.customer_id: c for c in scraper.credentials}
        log_by_cid = await scraper.get_wager_log(force=force_wager_log)

        # CLV is computed on every request rather than persisted with the
        # wager log. That way newly captured closing lines show up
        # immediately and we don't need a schema bump to add a column to
        # the persisted JSON. The lookup is cheap (single SQLite query
        # per wager), and the dataset is small (~hundreds of bets).
        config_pair = get_coral33_config() if cache is not None else None

        all_bets: list[BetEntryModel] = []
        for cid, wagers in log_by_cid.items():
            cred = creds_by_id.get(cid)
            label = (cred.label if cred and cred.label else cid)
            for w in wagers:
                clv_pct: float | None = None
                if cache is not None and config_pair is not None:
                    config, reverse = config_pair
                    try:
                        result = lookup_clv(w, cache, config, reverse)
                    except Exception:
                        # Defensive — CLV failures must never break the
                        # bets endpoint. Log + null-out for this wager.
                        import logging
                        logging.getLogger(__name__).exception(
                            "CLV lookup failed for ticket %s",
                            w.ticket_number,
                        )
                        result = None
                    if result is not None:
                        # clv_pct is stored as a fraction (e.g. 0.025 for
                        # 2.5% over the close). UI multiplies by 100.
                        clv_pct = result.clv_pct * 100.0
                all_bets.append(BetEntryModel(
                    customer_id=cid,
                    account_label=label,
                    ticket_number=w.ticket_number,
                    accepted_at=w.accepted_at,
                    settled_at=w.settled_at,
                    wager_status=w.wager_status,
                    wager_type=w.wager_type,
                    total_picks=w.total_picks,
                    amount_wagered=w.amount_wagered,
                    to_win_amount=w.to_win_amount,
                    amount_won=w.amount_won,
                    amount_lost=w.amount_lost,
                    is_free_play=w.is_free_play,
                    sport_type=w.sport_type,
                    sport_sub_type=w.sport_sub_type,
                    period=w.period,
                    team1_id=w.team1_id,
                    team2_id=w.team2_id,
                    chosen_team_id=w.chosen_team_id,
                    description=w.description,
                    final_money=w.final_money,
                    adj_spread=w.adj_spread,
                    adj_total_points=w.adj_total_points,
                    clv_pct=clv_pct,
                ))

        status_norm = status.lower().strip() if status else "any"
        if status_norm == "open":
            all_bets = [b for b in all_bets if b.wager_status == "O"]
        elif status_norm == "settled":
            all_bets = [b for b in all_bets if b.wager_status != "O"]
        all_bets.sort(key=lambda b: b.accepted_at, reverse=True)

        return BetsResponse(
            bets=all_bets,
            total_count=len(all_bets),
            backfill_weeks=DEFAULT_BACKFILL_WEEKS,
        )

    @router.post("/api/coral33/accounts/clv-backfill")
    async def clv_backfill(
        dry_run: bool = Query(default=True, description="Estimate cost without spending credits"),
        include_props: bool = Query(default=False, description="Fetch player-prop markets too (≈2× cost)"),
        max_credits: int | None = Query(default=None, description="Cap total credits consumed; abort once reached"),
    ) -> dict:
        """One-shot historical CLV backfill.

        Walks the persisted wager log, finds entries that don't yet
        have a closing line, discovers their Odds API event_ids via the
        historical events endpoint, and fetches per-event archived odds
        ~7 minutes before commence. Devigs and writes to closing_lines.

        Default `dry_run=True` performs event discovery and reports the
        match counts + estimated cost without spending credits on
        per-event fetches. Re-run with `dry_run=false` to execute.

        Idempotent — already-covered wagers are skipped, partial runs
        can resume.
        """
        if cache is None or odds_client is None:
            return {
                "status": "unavailable",
                "reason": (
                    "CLV backfill requires both the OddsCache and the "
                    "OddsAPIClient — wire them through build_router()."
                ),
            }
        from ..odds.clv import get_coral33_config
        from ..odds.clv_backfill import backfill_clv

        config, _ = get_coral33_config()
        # Union all accounts' wager logs.
        log_by_cid = await scraper.get_wager_log(force=False)
        wagers = [w for ws in log_by_cid.values() for w in ws]

        stats = await backfill_clv(
            wagers=wagers,
            cache=cache,
            client=odds_client,
            config=config,
            include_props=include_props,
            dry_run=dry_run,
            max_credits=max_credits,
        )
        result = stats.as_dict()
        result["dry_run"] = dry_run
        result["include_props"] = include_props
        return result

    return router
