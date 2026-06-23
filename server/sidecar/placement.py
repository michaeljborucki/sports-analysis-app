"""Sidecar orchestrator: splitter -> per-assignment placement loop -> audit + SSE.

Run inside a FastAPI BackgroundTask. The HTTP route validates the request,
enqueues the orchestrator, and returns a job_id immediately. UI subscribes
to SSE for updates.

Cascade semantics
-----------------
Account-scoped exceptions (Coral33AuthError, Coral33APIError) burn the
session for the affected customer_id. Remaining same-customer sibling
assignments are recorded as ``error`` with message
``auth_failed (account-scoped cascade)`` WITHOUT a second HTTP attempt.
Parlay-scoped failures (line_changed, transient timeouts, generic
exceptions) are recorded for the single assignment only — siblings still
fire because the same session may still be valid.

Off-mode gate
-------------
When ``self.mode == "off"`` the orchestrator writes a single refusal
audit row, emits ``sidecar_signal_skipped`` with ``reason=mode_off``,
and returns. The placer is never constructed in this path; tests rely
on the placer-factory NOT being called to assert the gate works.

Force-refresh
-------------
After the assignment loop, an ``asyncio.create_task`` fires a fresh
balance pull for every customer_id that was actually used so the
account-pool grid updates immediately without waiting for the next
periodic scrape. The refresh runs in the background; ``handle_place``
returns as soon as the loop and audit writes finish.

See docs/superpowers/specs/2026-06-21-auto-bet-sidecar-design.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from server.sidecar import audit, sse
from server.sidecar.models import (
    AccountSnapshot,
    LegSpec,
    SidecarPlaceRequest,
    SplitAssignment,
    SplitPlan,
)
from server.sidecar.settings import KellyFraction, kelly_to_pct
from server.sidecar.splitter import plan_splits


__all__ = [
    "SidecarOrchestrator",
    "SidecarPlaceRequest",
    "JitterDisabled",
    "JitterRandom",
]


logger = logging.getLogger(__name__)


class JitterDisabled:
    """Sentinel for tests: no sleep between assignments."""

    async def sleep(self, ix: int, total: int) -> None:
        return None


class JitterRandom:
    """Production jitter: 3-8s uniform between assignments, no gap on the
    first one or single-assignment jobs."""

    def __init__(self, low: float = 3.0, high: float = 8.0):
        self.low, self.high = low, high

    async def sleep(self, ix: int, total: int) -> None:
        if total <= 1 or ix == 0:
            return
        await asyncio.sleep(random.uniform(self.low, self.high))


class _PlacerFactory(Protocol):
    """Anything with `.for_account(snapshot) -> placer`. The placer must
    expose `place_open_parlay(ev_leg, stake_dollars, live)` returning a
    PlacementResult-shaped object (ticket_number, dry_run, accepted_payload,
    would_be_payload, decimal_payout, expected_win)."""

    def for_account(self, snapshot: AccountSnapshot) -> Any: ...


def _payload_for_audit(result: Any) -> dict | None:
    """Pick whichever placement payload exists for the audit row.

    - live success -> accepted_payload (the actual server response)
    - dry-run     -> would_be_payload  (the payload we constructed)
    - error path  -> None              (caller passes result=None)
    """
    if result is None:
        return None
    return result.accepted_payload or result.would_be_payload


def _target_for(req: SidecarPlaceRequest) -> int:
    """Resolve the dollar target the splitter should fill.

    Delta-tick path passes ``stake_override_dollars``; user-triggered
    placements leave it None and we compute from Kelly here.

    All targets are rounded to the nearest $5 (see
    ``settings.compute_kelly_target``)."""
    from server.sidecar.settings import compute_kelly_target, round_stake_to_5
    if req.stake_override_dollars is not None:
        return round_stake_to_5(req.stake_override_dollars)
    return compute_kelly_target(
        req.kelly_fraction, req.kelly_full_pct, req.bankroll,
    )


class SidecarOrchestrator:
    """Owns the splitter -> loop -> audit -> SSE pipeline for one job.

    Stateless across requests; a single instance is shared by the route
    layer and the delta-tick scheduler. Per-call state (pool snapshot,
    plan, burned-accounts set) lives in ``handle_place``."""

    def __init__(
        self,
        pool_provider: Callable[[], list[AccountSnapshot]],
        placer_factory: _PlacerFactory,
        mode: str,                       # 'off' | 'dry-run' | 'live'
        db_path,
        jitter: Any = None,
        refresh_accounts: Callable[[set[str]], Any] | None = None,
    ):
        self.pool_provider = pool_provider
        self.placer_factory = placer_factory
        self.mode = mode
        self.db_path = db_path
        self.jitter = jitter if jitter is not None else JitterRandom()
        # Optional hook for I1's force-refresh. Wired by the route layer
        # to ``scraper.trigger_refresh_async`` (or a more targeted call).
        # Tests can leave this None — the orchestrator will skip the
        # refresh step rather than reach into FastAPI.
        self._refresh_hook = refresh_accounts
        # Per-account placer cache. Hoisted from per-job to per-orchestrator
        # so subsequent placements on the same account reuse the JWT +
        # proxied AsyncSession + cached getParlaySpecs. Saves ~500ms-1s of
        # re-auth round-trip per follow-up placement.
        # Keyed by customer_id; each Coral33Placer wraps one Coral33Client
        # with that account's proxy. Cleared by reset().
        self._placers: dict[str, Any] = {}

    @property
    def audit_conn(self) -> sqlite3.Connection:
        """Fresh connection per access — sqlite3 connections are NOT
        safe to share across awaits in async code. Caller is responsible
        for closing."""
        return sqlite3.connect(self.db_path)

    async def handle_place(
        self,
        req: SidecarPlaceRequest,
        job_id: str,
    ) -> str:
        # --- Off-mode hard gate (E3) -----------------------------------
        if self.mode == "off":
            conn = self.audit_conn
            try:
                audit.insert_placement(conn, audit.AuditRow(
                    placement_id=uuid.uuid4().hex,
                    job_id=job_id,
                    created_at=int(time.time()),
                    ev_row_id=req.ev_row_id,
                    ev_leg=json.dumps(req.ev_leg.__dict__),
                    parlay_name="10 team",
                    kelly_fraction=req.kelly_fraction.value,
                    target_stake=0.0,
                    stake=None,
                    mode="off",
                    picked_account=None,
                    result="no_eligible_account",
                    ticket_number=None,
                    accepted_payload=None,
                    error_message="sidecar mode is off",
                    trigger_source=req.trigger_source,
                ))
            finally:
                conn.close()
            sse.emit_signal_skipped({
                "job_id": job_id,
                "target_stake": 0,
                "reason": "mode_off",
            })
            return job_id

        target = _target_for(req)
        pool = self.pool_provider()
        plan = plan_splits(target, pool, pinned_customer_id=req.customer_id)

        conn = self.audit_conn
        try:
            if plan.status == "below_minimum":
                self._record_refusal(
                    conn, job_id, req, plan, "below_minimum",
                    f"Kelly target ${target} below $30 floor",
                )
                sse.emit_signal_skipped({
                    "job_id": job_id,
                    "target_stake": target,
                    "floor": 30,
                })
                return job_id

            if plan.status == "no_eligible_account":
                self._record_refusal(
                    conn, job_id, req, plan, "no_eligible_account",
                    "no account has $30+ available",
                )
                lowest_cid: str | None = None
                if pool:
                    lowest = min(pool, key=lambda a: a.available_balance)
                    lowest_cid = lowest.customer_id
                sse.emit_topup_required({
                    "job_id": job_id,
                    "target_stake": target,
                    "max_fundable": 0,
                    "lowest_balance_account": lowest_cid,
                })
                return job_id

            # --- Placement loop ----------------------------------------
            # Per-account session reuse + account-scoped failure cascade.
            # Pull from the instance-level placer cache so repeat jobs
            # reuse Coral33Client + JWT + getParlaySpecs result.
            placers: dict[str, Any] = self._placers
            burned_accounts: set[str] = set()

            total = len(plan.assignments)
            for ix, assignment in enumerate(plan.assignments):
                cid = assignment.account.customer_id

                if cid in burned_accounts:
                    # Cascade: same-account sibling after an
                    # account-scoped failure. Record without firing.
                    cascade_msg = "auth_failed (account-scoped cascade)"
                    self._record_placement(
                        conn, job_id, req, assignment, None, "error",
                        error_message=cascade_msg,
                    )
                    sse.emit_placement({
                        "job_id": job_id,
                        "result": "error",
                        "picked_account": cid,
                        "stake": assignment.amount,
                        "mode": self.mode,
                        "error_message": cascade_msg,
                    })
                    continue

                await self.jitter.sleep(ix, total)
                if cid not in placers:
                    placers[cid] = self.placer_factory.for_account(
                        assignment.account,
                    )
                placer = placers[cid]

                account_scoped_failed = await self._fire_one(
                    conn, job_id, req, assignment, placer,
                )
                if account_scoped_failed:
                    burned_accounts.add(cid)

            if plan.status == "partial_fill":
                self._record_partial(conn, job_id, req, plan)
                sse.emit_partial_fill({
                    "job_id": job_id,
                    "target_stake": target,
                    "filled_stake": plan.filled,
                    "unfilled_stake": plan.unfilled,
                })

            # --- I1: force-refresh in the background --------------------
            used_account_ids = {
                a.account.customer_id for a in plan.assignments
            }
            if used_account_ids:
                # Fire-and-forget — tests with no refresh hook are unaffected.
                try:
                    asyncio.create_task(
                        self._refresh_accounts(used_account_ids),
                    )
                except RuntimeError:
                    # No running event loop (shouldn't happen under
                    # FastAPI/pytest-asyncio, but guard anyway).
                    pass

            return job_id
        finally:
            conn.close()

    async def _fire_one(
        self,
        conn,
        job_id: str,
        req: SidecarPlaceRequest,
        assignment: SplitAssignment,
        placer: Any,
    ) -> bool:
        """Fire one placement.

        Returns True iff the failure was ACCOUNT-SCOPED (auth, proxy,
        balance) and the caller should cascade-skip remaining
        same-account siblings. Returns False on success, dry-run, or
        parlay-scoped failures."""
        # Lazy imports so this module can be imported without the coral33
        # client being available — useful for tests that fake everything.
        from server.odds.books.coral33.client import (
            Coral33APIError,
            Coral33AuthError,
        )

        try:
            result = await placer.place_open_parlay(
                ev_leg=req.ev_leg,
                stake_dollars=assignment.amount,
                live=(self.mode == "live"),
            )
            kind = "placed" if not result.dry_run else "dry_run"
            self._record_placement(
                conn, job_id, req, assignment, result, kind,
            )
            self._update_signal_state(
                conn, req, assignment.amount, first_placement=True,
            )
            sse.emit_placement({
                "job_id": job_id,
                "result": kind,
                "ticket_number": (
                    str(result.ticket_number)
                    if result.ticket_number else None
                ),
                "picked_account": assignment.account.customer_id,
                "stake": assignment.amount,
                "mode": self.mode,
            })
            return False
        except Coral33AuthError as ex:
            self._record_failure(conn, job_id, req, assignment, str(ex))
            return True   # account-scoped: cascade siblings
        except Coral33APIError as ex:
            # Coral33APIError covers connection errors + non-200s. Treat
            # as account-scoped: the same session/proxy is likely burned
            # for this signal.
            self._record_failure(conn, job_id, req, assignment, str(ex))
            return True
        except Exception as ex:
            # Parlay-scoped (line_changed, timeout, etc.): record but
            # DON'T cascade — sibling assignments on the same account
            # can still be attempted.
            self._record_failure(conn, job_id, req, assignment, str(ex))
            return False

    def _update_signal_state(
        self,
        conn,
        req: SidecarPlaceRequest,
        stake: int,
        first_placement: bool,
    ) -> None:
        """Bump total_placed (and arm on first call) for the ev_row_id.

        Imported lazily so this module stays loadable in environments
        where the active-signals module isn't installed yet (it lands
        in parallel via task E4). Failures are swallowed: audit/SSE
        already captured the placement, and the delta tick is a separate
        concern from the user-facing job outcome.
        """
        try:
            from server.sidecar import active_signals
        except ImportError:
            return
        try:
            if first_placement:
                # commence_time is not on the request — pass a far-future
                # placeholder if unknown. The delta-tick reader filters
                # by commence_time > now, so using a value of 0 would
                # skip the row; we use req.ev_leg.game_datetime if
                # parseable, otherwise default to far-future so the
                # signal stays trackable.
                commence_ts = _commence_ts_from_leg(req.ev_leg)
                active_signals.arm_signal(
                    conn,
                    ev_row_id=req.ev_row_id,
                    kelly_fraction=req.kelly_fraction,
                    bankroll_at_arm=req.bankroll,
                    commence_time=commence_ts,
                    armed_customer_id=req.customer_id,
                )
            active_signals.update_total_placed(
                conn, req.ev_row_id, float(stake),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "active_signals update failed for ev_row_id=%s",
                req.ev_row_id,
            )

    async def _refresh_accounts(self, customer_ids: set[str]) -> None:
        """Background hook: fire the accounts-refresh after a job ends.

        I1 says force-refresh ONLY the customer_ids that were actually
        used. The existing /api/coral33/accounts/refresh endpoint
        refreshes the entire pool (no per-customer scope); we accept
        that for now — refreshing extra accounts is cheap. If a
        `refresh_accounts` hook was passed to the constructor we defer
        to it (route layer wires it to ``scraper.trigger_refresh_async``).
        Tests that don't pass a hook get a no-op."""
        if not customer_ids:
            return
        hook = self._refresh_hook
        if hook is None:
            return
        try:
            ret = hook(customer_ids)
            # Hook may be sync or async; await if it's awaitable.
            if asyncio.iscoroutine(ret):
                await ret
        except Exception:  # noqa: BLE001
            logger.exception(
                "post-job account refresh failed for %s", customer_ids,
            )

    # --- audit row helpers (one per result kind) -------------------------

    def _record_placement(
        self,
        conn,
        job_id: str,
        req: SidecarPlaceRequest,
        assignment: SplitAssignment,
        result: Any,
        kind: str,
        error_message: str | None = None,
    ) -> None:
        payload = _payload_for_audit(result)
        audit.insert_placement(conn, audit.AuditRow(
            placement_id=uuid.uuid4().hex,
            job_id=job_id,
            created_at=int(time.time()),
            ev_row_id=req.ev_row_id,
            ev_leg=json.dumps(req.ev_leg.__dict__),
            parlay_name="10 team",
            kelly_fraction=req.kelly_fraction.value,
            target_stake=float(_target_for(req)),
            stake=float(assignment.amount),
            mode=self.mode,
            picked_account=assignment.account.customer_id,
            result=kind,
            ticket_number=(
                str(result.ticket_number)
                if result and result.ticket_number else None
            ),
            accepted_payload=(
                json.dumps(payload) if payload is not None else None
            ),
            error_message=error_message,
            trigger_source=req.trigger_source,
        ))

    def _record_failure(
        self,
        conn,
        job_id: str,
        req: SidecarPlaceRequest,
        assignment: SplitAssignment,
        msg: str,
    ) -> None:
        self._record_placement(
            conn, job_id, req, assignment, None, "error", msg,
        )
        sse.emit_placement({
            "job_id": job_id,
            "result": "error",
            "picked_account": assignment.account.customer_id,
            "stake": assignment.amount,
            "mode": self.mode,
            "error_message": msg,
        })

    def _record_refusal(
        self,
        conn,
        job_id: str,
        req: SidecarPlaceRequest,
        plan: SplitPlan,
        kind: str,
        msg: str,
    ) -> None:
        audit.insert_placement(conn, audit.AuditRow(
            placement_id=uuid.uuid4().hex,
            job_id=job_id,
            created_at=int(time.time()),
            ev_row_id=req.ev_row_id,
            ev_leg=json.dumps(req.ev_leg.__dict__),
            parlay_name="10 team",
            kelly_fraction=req.kelly_fraction.value,
            target_stake=float(plan.target),
            stake=None,
            mode=self.mode,
            picked_account=None,
            result=kind,
            ticket_number=None,
            accepted_payload=None,
            error_message=msg,
            trigger_source=req.trigger_source,
        ))

    def _record_partial(
        self,
        conn,
        job_id: str,
        req: SidecarPlaceRequest,
        plan: SplitPlan,
    ) -> None:
        audit.insert_placement(conn, audit.AuditRow(
            placement_id=uuid.uuid4().hex,
            job_id=job_id,
            created_at=int(time.time()),
            ev_row_id=req.ev_row_id,
            ev_leg=json.dumps(req.ev_leg.__dict__),
            parlay_name="10 team",
            kelly_fraction=req.kelly_fraction.value,
            target_stake=float(plan.target),
            stake=float(plan.filled),
            mode=self.mode,
            picked_account=None,
            result="partial_fill",
            ticket_number=None,
            accepted_payload=None,
            error_message=f"pool filled ${plan.filled} of ${plan.target}",
            trigger_source=req.trigger_source,
        ))


def _commence_ts_from_leg(leg: LegSpec) -> int:
    """Best-effort parse of LegSpec.game_datetime to a Unix timestamp.

    The LegSpec field is a Coral33-shaped string like
    ``"2026-06-21 19:00:01.000"``. If parsing fails we return a
    far-future sentinel so the active_signals row still passes the
    ``commence_time > now`` filter in the delta-tick scanner. The
    on-disk row is rewritten with the real commence_time the first
    time the tick scanner refreshes from the EV source.
    """
    raw = (leg.game_datetime or "").strip()
    if not raw:
        return _FAR_FUTURE
    try:
        from datetime import datetime, timezone
        # Coral's format: "YYYY-MM-DD HH:MM:SS.mmm" (UTC assumed).
        dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except (ValueError, TypeError):
        return _FAR_FUTURE


# 2099-01-01 00:00:00 UTC — placeholder when we can't parse a leg's
# game_datetime. Keeps the active-signal row visible to the tick
# scanner until the EV source re-attaches the real commence_time.
_FAR_FUTURE = 4070908800
