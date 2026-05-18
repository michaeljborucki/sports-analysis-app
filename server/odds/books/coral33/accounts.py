"""
Multi-account coral33 roll-up: balances + pending wagers across every
sub-account. Replaces the standalone ~/GitHub/account_scraper.py — uses
the existing curl_cffi-based Coral33Client (no Selenium / Firefox).

Account list comes from the `CORAL33_ACCOUNTS` env var as JSON, e.g.

    CORAL33_ACCOUNTS='[
      {"customer_id":"VR11601","password":"dixon1","label":"Account 1"},
      {"customer_id":"VR12509","password":"borucki1","label":"Primary"}
    ]'

`label` is optional — if omitted, the customerID is used as the display name.

Cached in process; UI polls `/api/coral33/accounts`. A manual refresh hits
`/api/coral33/accounts/refresh` which spawns a background scrape and
returns immediately.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .client import Coral33APIError, Coral33AuthError, Coral33Client


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountCredential:
    customer_id: str
    password: str
    label: str | None = None


@dataclass
class WagerSummary:
    """Roll-up of one customer's pending wagers."""
    open_count: int = 0
    open_amount_risked: float = 0.0   # dollars
    open_amount_to_win: float = 0.0   # dollars
    straight_count: int = 0
    parlay_count: int = 0
    parlay_partial_count: int = 0     # at least one leg graded, others open
    free_play_count: int = 0


@dataclass
class WagerLeg:
    """One leg of a pending wager. For straight bets a wager has 1 leg;
    parlays have N legs sharing TicketNumber + WagerNumber."""
    play_number: int
    description: str       # human description (sport + team + line)
    sport_type: str | None = None
    sport_sub_type: str | None = None
    period: str | None = None
    team1: str | None = None        # away
    team2: str | None = None        # home
    chosen_team: str | None = None
    final_money: int | None = None  # American odds at placement
    spread: float | None = None
    total_points: float | None = None
    game_datetime: str | None = None
    outcome: str | None = None      # "" / "W" / "L" / "P" — leg-level
    leg_amount_wagered: float = 0.0
    leg_to_win_amount: float = 0.0


@dataclass
class PendingWager:
    """One pending bet (1+ legs). Open straights, open parlays, and partially-
    graded parlays all live here until WagerStatus resolves to W/L/P."""
    ticket_number: int
    wager_number: int
    bet_type: str                   # "straight" | "parlay" | "teaser" | other
    wager_status: str | None        # "O" open / "W"/"L"/"P" — overall ticket
    amount_wagered: float           # dollars
    to_win_amount: float            # dollars
    is_free_play: bool
    accepted_at: str | None
    parlay_name: str | None = None
    teaser_name: str | None = None
    legs: list[WagerLeg] = field(default_factory=list)
    # Convenience flags for the UI
    has_open_legs: bool = False
    has_graded_legs: bool = False
    is_partial: bool = False        # both flags True


@dataclass
class HistoryPoint:
    """One day on the balance timeline.

    `balance` is the account's actual end-of-day balance; `net` is that
    day's P&L delta from coral33's daily-figure report. Anchored at the
    oldest week's `PreviousBalance` so the rightmost point lands on the
    live `ActualBalance`.

    `pending` is the dollar value of open wagers on that day. Coral33's
    daily-figures endpoint doesn't carry historical pending balance, so
    we leave it as 0 for every past day and only the API layer's "today"
    join populates it from the current AccountSnapshot. Once we start
    persisting daily snapshots locally, we can backfill non-zero pending
    for prior days.
    """
    date: str       # YYYY-MM-DD
    won: float      # unused with daily-figures source (kept for back-compat)
    lost: float
    net: float      # day P&L delta
    balance: float  # account balance at end of day
    pending: float = 0.0  # open-wager dollars at end of day (0 historically)


@dataclass
class AccountSnapshot:
    customer_id: str
    label: str
    fetched_at: str
    # All in DOLLARS. coral33 stores some fields in cents — converted here.
    current_balance: float = 0.0
    available_balance: float = 0.0
    pending_wager_balance: float = 0.0
    free_play_balance: float = 0.0
    credit_limit: float = 0.0
    wager_limit: float = 0.0
    player_name: str | None = None
    agent_id: str | None = None
    wagers: WagerSummary = field(default_factory=WagerSummary)
    pending_wagers: list[PendingWager] = field(default_factory=list)
    error: str | None = None


@dataclass
class AccountsRollup:
    snapshots: list[AccountSnapshot]
    refreshed_at: str | None
    refreshing: bool = False

    @property
    def total_current_balance(self) -> float:
        return sum(s.current_balance for s in self.snapshots if s.error is None)

    @property
    def total_available_balance(self) -> float:
        return sum(s.available_balance for s in self.snapshots if s.error is None)

    @property
    def total_pending_balance(self) -> float:
        return sum(s.pending_wager_balance for s in self.snapshots if s.error is None)

    @property
    def total_free_play(self) -> float:
        return sum(s.free_play_balance for s in self.snapshots if s.error is None)

    @property
    def total_open_wagers(self) -> int:
        return sum(s.wagers.open_count for s in self.snapshots if s.error is None)


def load_account_credentials() -> list[AccountCredential]:
    """Read accounts from the `CORAL33_ACCOUNTS` env (JSON). Falls back to
    the single-account `CORAL33_CUSTOMER_ID` / `CORAL33_PASSWORD` env pair."""
    raw = os.environ.get("CORAL33_ACCOUNTS", "").strip()
    if raw:
        try:
            entries = json.loads(raw)
            return [
                AccountCredential(
                    customer_id=e["customer_id"],
                    password=e["password"],
                    label=e.get("label"),
                )
                for e in entries
                if e.get("customer_id") and e.get("password")
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("CORAL33_ACCOUNTS env malformed: %s", e)
    cust = os.environ.get("CORAL33_CUSTOMER_ID", "").strip()
    pwd = os.environ.get("CORAL33_PASSWORD", "").strip()
    if cust and pwd:
        return [AccountCredential(customer_id=cust, password=pwd)]
    return []


# ───────────────────────── Scraper ─────────────────────────────────────────


_BET_TYPE_BY_WAGER_TYPE = {
    "S": "straight",
    "P": "parlay",
    "T": "teaser",
    "I": "if-bet",
    "R": "round-robin",
    "M": "straight",   # money-line single
}


def _classify_leg_status(outcome: str | None) -> str:
    """Per-leg outcome → simple status label."""
    out = (outcome or "").strip().upper()
    if out == "W":
        return "won"
    if out == "L":
        return "lost"
    if out == "P":
        return "push"
    return "open"


def _build_leg(row: dict) -> WagerLeg:
    desc = (row.get("Description") or "").strip()
    if not desc:
        # Description is sometimes only on the head row; fall back to
        # team-vs-team if missing on later legs.
        t1 = (row.get("Team1ID") or "").strip()
        t2 = (row.get("Team2ID") or "").strip()
        if t1 and t2:
            desc = f"{t1} vs {t2}"
    return WagerLeg(
        play_number=int(row.get("PlayNumber") or 0),
        description=desc,
        sport_type=(row.get("SportType") or "").strip() or None,
        sport_sub_type=(row.get("SportSubType") or "").strip() or None,
        period=(row.get("PeriodDescription") or "").strip() or None,
        team1=(row.get("Team1ID") or "").strip() or None,
        team2=(row.get("Team2ID") or "").strip() or None,
        chosen_team=(row.get("ChosenTeamID") or "").strip() or None,
        final_money=row.get("FinalMoney"),
        spread=row.get("AdjSpread") or None,
        total_points=row.get("AdjTotalPoints") or None,
        game_datetime=(row.get("GameDateTime") or "").strip() or None,
        outcome=_classify_leg_status(row.get("Outcome")),
        leg_amount_wagered=(row.get("LegAmountWagered") or 0) / 100.0,
        leg_to_win_amount=(row.get("LegToWinAmount") or 0) / 100.0,
    )


def _classify_pending_wagers(
    pending: list[dict],
) -> tuple[WagerSummary, list[PendingWager]]:
    """Group `Pending` response rows by (TicketNumber, WagerNumber) and
    classify each grouped wager. coral33's response carries one row per
    LEG, so a 3-leg parlay arrives as 3 entries sharing the same ticket+
    wager number.

    Returns the roll-up summary plus the structured wager list (used by
    the UI's expandable per-bet detail view).

    Outcome legend (per coral33 dumps):
      - WagerStatus: 'O' open / 'W' won / 'L' lost / 'P' push (overall ticket)
      - Outcome:     leg-level result, blank/None when leg is still open
    """
    summary = WagerSummary()
    wagers_out: list[PendingWager] = []
    by_ticket: dict[tuple, list[dict]] = {}
    for row in pending or []:
        key = (row.get("TicketNumber"), row.get("WagerNumber"))
        by_ticket.setdefault(key, []).append(row)

    for key, leg_rows in by_ticket.items():
        # Sort legs by PlayNumber so the UI gets them in placement order.
        leg_rows.sort(key=lambda r: r.get("PlayNumber") or 0)
        head = leg_rows[0]
        wager_type = (head.get("WagerType") or "").strip().upper()
        total_picks = head.get("TotalPicks") or len(leg_rows)
        is_parlay = wager_type == "P" or total_picks > 1
        legs = [_build_leg(r) for r in leg_rows]
        graded_count = sum(1 for l in legs if l.outcome in ("won", "lost", "push"))
        open_count = sum(1 for l in legs if l.outcome == "open")
        is_partial = graded_count > 0 and open_count > 0
        # Summary tallies
        if is_parlay:
            summary.parlay_count += 1
            if is_partial:
                summary.parlay_partial_count += 1
        else:
            summary.straight_count += 1
        summary.open_count += 1
        amount = (head.get("AmountWagered") or 0) / 100.0
        to_win = (head.get("ToWinAmount") or 0) / 100.0
        summary.open_amount_risked += amount
        summary.open_amount_to_win += to_win
        is_free = (head.get("FreePlayFlag") or "").upper() == "Y"
        if is_free:
            summary.free_play_count += 1
        bet_type = _BET_TYPE_BY_WAGER_TYPE.get(wager_type, "parlay" if is_parlay else "straight")
        wagers_out.append(PendingWager(
            ticket_number=int(head.get("TicketNumber") or 0),
            wager_number=int(head.get("WagerNumber") or 0),
            bet_type=bet_type,
            wager_status=(head.get("WagerStatus") or "").strip() or None,
            amount_wagered=amount,
            to_win_amount=to_win,
            is_free_play=is_free,
            accepted_at=(head.get("AcceptedDateTime") or "").strip() or None,
            parlay_name=(head.get("ParlayName") or "").strip() or None,
            teaser_name=(head.get("TeaserName") or "").strip() or None,
            legs=legs,
            has_open_legs=open_count > 0,
            has_graded_legs=graded_count > 0,
            is_partial=is_partial,
        ))
    # Sort wagers: partial first (most-actionable), then by accepted_at desc.
    wagers_out.sort(key=lambda w: (
        0 if w.is_partial else 1,
        -(int((w.accepted_at or "0").replace("-", "").replace(":", "").replace(" ", "").replace(".", "") or "0")),
    ))
    return summary, wagers_out


async def fetch_account(cred: AccountCredential) -> AccountSnapshot:
    """Authenticate, pull account info + pending wagers, return a snapshot.
    Errors are caught and stored in `snapshot.error` rather than raised."""
    label = cred.label or cred.customer_id
    snap = AccountSnapshot(
        customer_id=cred.customer_id,
        label=label,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    client = Coral33Client(cred.customer_id, cred.password)
    try:
        await client.authenticate()
    except (Coral33AuthError, Coral33APIError) as e:
        snap.error = f"auth: {e}"
        return snap
    try:
        info = await client.post_form("getAccountInfo", {"RRO": "0"})
        ai = info.get("accountInfo") or {}
        snap.player_name = (ai.get("PlayerName") or "").strip() or None
        snap.agent_id = (ai.get("AgentID") or "").strip() or None
        # CurrentBalance, PendingWagerBalance, FreePlayBalance are CENTS.
        # AvailableBalance comes through in dollars already.
        # CreditLimit / WagerLimit are dollars.
        snap.current_balance = (ai.get("CurrentBalance") or 0) / 100.0
        snap.pending_wager_balance = (ai.get("PendingWagerBalance") or 0) / 100.0
        snap.free_play_balance = (ai.get("FreePlayBalance") or 0) / 100.0
        snap.available_balance = float(ai.get("AvailableBalance") or 0)
        snap.credit_limit = float(ai.get("CreditLimit") or 0)
        snap.wager_limit = float(ai.get("WagerLimit") or 0)
    except Coral33APIError as e:
        snap.error = f"getAccountInfo: {e}"
        return snap
    try:
        pend = await client.post_form("Pending", {
            "agentID": cred.customer_id,
            "ticketNumber": "0",
            "RRO": "0",
        })
        summary, pending_wagers = _classify_pending_wagers(
            pend.get("Pending") or []
        )
        snap.wagers = summary
        snap.pending_wagers = pending_wagers
    except Coral33APIError as e:
        # Non-fatal: balances are already populated, wager summary stays empty.
        logger.warning("Pending failed for %s: %s", cred.customer_id, e)
    return snap


async def fetch_account_history(
    cred: AccountCredential, weeks_back: int = 12
) -> list[HistoryPoint]:
    """Pull daily P&L for the past `weeks_back` figure weeks.

    Uses coral33's `getDailyFiguresByCustomer` which returns pre-computed
    daily nets (the same numbers the agent's settlement report uses), so
    we don't have to derive P&L from individual wager outcomes. One call
    per `week=N` (0 = current, 1 = last week, …) returns the week's BOW
    plus day1..day7 deltas keyed Mon→Sun.

    Response shape (verified):
      {"INFO": {"AgentID": "TYSONR", "BOW": "2026-04-21 00:00:00.000",
                "day1": 0, "day2": 0, ..., "day7": 0,
                "ActualBalance": 1416.43, "PreviousBalance": 3056.43,
                "figuredays": "0, 4, 5, 6", ...}}
    """
    client = Coral33Client(cred.customer_id, cred.password)
    try:
        await client.authenticate()
    except (Coral33AuthError, Coral33APIError) as e:
        logger.warning("history auth failed for %s: %s", cred.customer_id, e)
        return []

    # Need agentID to call getDailyFiguresByCustomer. One getAccountInfo
    # call up-front is the cheapest way to discover it.
    try:
        info = await client.post_form("getAccountInfo", {"RRO": "0"})
        agent_id = ((info.get("accountInfo") or {}).get("AgentID") or "").strip()
    except Coral33APIError as e:
        logger.warning("history agent lookup failed for %s: %s", cred.customer_id, e)
        return []
    if not agent_id:
        logger.warning("no AgentID for %s — cannot fetch history", cred.customer_id)
        return []

    today = datetime.now(timezone.utc).date()
    week_offsets = list(range(weeks_back - 1, -1, -1))

    # Fan out the 13 weekly figure calls in parallel. Each post_form
    # spins up its own AsyncSession (curl_cffi) and the client lock only
    # guards JWT refresh, so concurrent calls don't serialize on each
    # other. Cuts /accounts/history from ~7s → ~1.2s for 8 accounts.
    async def fetch_week(week_offset: int) -> tuple[int, dict | None]:
        try:
            resp = await client.post_form("getDailyFiguresByCustomer", {
                "agentID": agent_id,
                "week": str(week_offset),
            })
        except Coral33APIError as e:
            logger.warning(
                "history fetch failed for %s @ week=%d: %s",
                cred.customer_id, week_offset, e,
            )
            return week_offset, None
        info_row = resp.get("INFO")
        return week_offset, info_row if isinstance(info_row, dict) else None

    week_results = await asyncio.gather(*(fetch_week(w) for w in week_offsets))

    points: list[HistoryPoint] = []
    # Iterate oldest → newest. Each week anchors independently at its own
    # PreviousBalance (start-of-week), so the per-day balances within the
    # week match coral33's settled figures exactly. Anchoring per-week
    # rather than walking across the whole window avoids drift from
    # deposits/withdrawals — those just appear as a small Monday jump.
    for _week_offset, info_row in week_results:
        if info_row is None:
            continue
        bow_raw = (info_row.get("BOW") or "").strip()
        if not bow_raw:
            continue
        try:
            bow_date = datetime.strptime(bow_raw[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        try:
            balance = float(info_row.get("PreviousBalance") or 0)
        except (TypeError, ValueError):
            balance = 0.0
        for i in range(1, 8):  # day1..day7 → Monday..Sunday
            day_date = bow_date + timedelta(days=i - 1)
            if day_date > today:
                # Skip future days — they always come back as 0 and would
                # flatten the right edge of the chart.
                break
            net = float(info_row.get(f"day{i}") or 0)
            balance += net
            points.append(HistoryPoint(
                date=day_date.isoformat(),
                won=0.0,
                lost=0.0,
                net=net,
                balance=balance,
            ))
    return points


class AccountsScraper:
    """Singleton-style holder of the latest multi-account snapshot. The
    backend instantiates one and exposes it via the API. Refreshing is
    serialized by an asyncio.Lock so concurrent refresh requests collapse
    to one pull."""

    def __init__(self, cache=None) -> None:
        self._lock = asyncio.Lock()
        self._creds = load_account_credentials()
        self._cached: AccountsRollup | None = None
        self._refreshing = False
        # Optional OddsCache reference — when provided, every successful
        # refresh writes a balance_snapshots row per account. Makes the
        # daily-chart "pending overlay" self-populating; no need to run
        # the external balance-dump script anymore.
        self._cache = cache
        # History cache: {customer_id: (refreshed_at_iso, weeks, points)}
        self._history: dict[str, tuple[str, int, list[HistoryPoint]]] = {}
        self._history_lock = asyncio.Lock()
        # Wager-log cache: {customer_id: (refreshed_at_iso, weeks, wagers)}.
        # Used to reconstruct historical pending balance per day. Settled
        # wagers are immutable so this cache is reused aggressively —
        # callers pass force=True only when they want a full re-pull.
        self._wager_log: dict[str, tuple[str, int, list]] = {}
        self._wager_log_lock = asyncio.Lock()

    @property
    def credentials(self) -> list[AccountCredential]:
        return self._creds

    def cached(self) -> AccountsRollup:
        if self._cached is None:
            return AccountsRollup(
                snapshots=[],
                refreshed_at=None,
                refreshing=self._refreshing,
            )
        return AccountsRollup(
            snapshots=self._cached.snapshots,
            refreshed_at=self._cached.refreshed_at,
            refreshing=self._refreshing,
        )

    async def refresh(self) -> AccountsRollup:
        """Re-pull every configured account. Safe to call concurrently;
        only one actual refresh happens at a time. Returns the new rollup."""
        if self._lock.locked():
            # Another caller is already refreshing — wait for it to finish
            # and return the result.
            async with self._lock:
                pass
            return self.cached()
        async with self._lock:
            self._refreshing = True
            try:
                t0 = time.time()
                snapshots = await asyncio.gather(
                    *(fetch_account(c) for c in self._creds),
                    return_exceptions=False,
                )
                self._cached = AccountsRollup(
                    snapshots=list(snapshots),
                    refreshed_at=datetime.now(timezone.utc).isoformat(),
                )
                logger.info(
                    "coral33 accounts refresh: %d accounts in %.1fs",
                    len(snapshots), time.time() - t0,
                )
                # Persist a balance-snapshot row per account so the
                # daily-chart pending overlay accumulates indefinitely
                # without external scripts. Best-effort: any DB error
                # logs and continues — we don't want a write failure
                # to drop a successful refresh.
                if self._cache is not None:
                    try:
                        now = datetime.now(timezone.utc)
                        rows = [
                            {
                                "customer_id": s.customer_id,
                                "captured_at": now.isoformat(),
                                "local_date": now.date().isoformat(),
                                "current_balance": float(s.current_balance),
                                "pending": float(s.pending_wager_balance),
                                "available": float(s.available_balance),
                                "free_play": float(s.free_play_balance),
                                "source": "scraper_refresh",
                            }
                            for s in self._cached.snapshots
                            if s.error is None
                        ]
                        if rows:
                            self._cache.upsert_balance_snapshots(rows)
                    except Exception:
                        logger.exception(
                            "balance_snapshots upsert failed (continuing)"
                        )
            finally:
                self._refreshing = False
        return self.cached()

    def trigger_refresh_async(self) -> dict[str, Any]:
        """Fire-and-forget refresh. Returns immediately with status."""
        if self._refreshing:
            return {"status": "already_refreshing"}
        if not self._creds:
            return {"status": "no_credentials_configured"}
        asyncio.create_task(self.refresh())
        return {"status": "triggered", "account_count": len(self._creds)}

    async def get_history(
        self, weeks_back: int = 12, force: bool = False
    ) -> dict[str, list[HistoryPoint]]:
        """Return per-account weekly P&L. Cached per (customer_id, weeks);
        callers can pass `force=True` to bypass cache. Concurrent calls
        collapse via the history lock."""
        async with self._history_lock:
            need_fetch: list[AccountCredential] = []
            for cred in self._creds:
                cached = self._history.get(cred.customer_id)
                if force or not cached or cached[1] != weeks_back:
                    need_fetch.append(cred)
            if need_fetch:
                results = await asyncio.gather(
                    *(fetch_account_history(c, weeks_back) for c in need_fetch),
                    return_exceptions=False,
                )
                stamp = datetime.now(timezone.utc).isoformat()
                for cred, points in zip(need_fetch, results):
                    self._history[cred.customer_id] = (stamp, weeks_back, points)
            return {
                cred.customer_id: self._history[cred.customer_id][2]
                for cred in self._creds
                if cred.customer_id in self._history
            }

    async def get_wager_log(
        self, weeks_back: int | None = None, force: bool = False,
    ) -> dict[str, list]:
        """Return the persisted wager log per account. Per the design
        constraint, the live API backfill runs ONCE per account — on
        first call when no JSON file exists, or when `force=True`. After
        that, every call reads from the on-disk JSON.

        Imported lazily to keep the module-level import of `accounts.py`
        out of the wager_log → accounts cycle.
        """
        from .wager_log import (
            DEFAULT_BACKFILL_WEEKS,
            fetch_account_wager_log,
            load_wager_log,
            save_wager_log,
        )
        if weeks_back is None:
            weeks_back = DEFAULT_BACKFILL_WEEKS

        async with self._wager_log_lock:
            need_fetch: list[AccountCredential] = []
            for cred in self._creds:
                if force:
                    need_fetch.append(cred)
                    continue
                cached = self._wager_log.get(cred.customer_id)
                if cached:
                    continue  # already in-memory for this process
                disk = load_wager_log(cred.customer_id)
                if disk is not None:
                    # Promote to in-memory cache; no API hit.
                    self._wager_log[cred.customer_id] = (
                        datetime.now(timezone.utc).isoformat(),
                        weeks_back,
                        disk,
                    )
                    continue
                need_fetch.append(cred)

            if need_fetch:
                logger.info(
                    "coral33 wager_log: backfilling %d account(s) × %d weeks",
                    len(need_fetch), weeks_back,
                )
                results = await asyncio.gather(
                    *(fetch_account_wager_log(c, weeks_back) for c in need_fetch),
                    return_exceptions=False,
                )
                stamp = datetime.now(timezone.utc).isoformat()
                for cred, wagers in zip(need_fetch, results):
                    self._wager_log[cred.customer_id] = (stamp, weeks_back, wagers)
                    save_wager_log(cred.customer_id, wagers, weeks_back)

            return {
                cred.customer_id: self._wager_log[cred.customer_id][2]
                for cred in self._creds
                if cred.customer_id in self._wager_log
            }
