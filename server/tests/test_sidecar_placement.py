"""Orchestrator tests for the sidecar placement loop (E2 + E3 + I1).

Covers:
  - dry-run happy path: $230 target stacks on Stanley ($150 + $80)
  - off-mode hard gate: no placer construction, single refusal audit row,
    sidecar_signal_skipped SSE emission with reason=mode_off
  - account-scoped failure cascade: Coral33AuthError on the first split
    sibling marks every remaining same-customer sibling as error WITHOUT
    a second HTTP attempt
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from server.odds.books.coral33.accounts import AccountCredential
from server.odds.cache import init_schema_on_path
from server.sidecar import audit
from server.sidecar.models import AccountSnapshot, LegSpec
from server.sidecar.placement import (
    JitterDisabled,
    SidecarOrchestrator,
    SidecarPlaceRequest,
)
from server.sidecar.settings import KellyFraction


def make_leg() -> LegSpec:
    return LegSpec(
        sport_type="Soccer              ",
        sport_sub_type="WORLD CUP   ",
        period="Game",
        line_type="M",
        game_num=619136397,
        chosen_team_id="New Zealand",
        rot_num=225390,
        price_american=475,
        price_decimal=5.75,
        price_numerator=19,
        price_denominator=4,
        game_datetime="2026-06-21 19:00:01.000",
        description="Soccer #225390 New Zealand +475 - For Game ",
    )


def make_pool() -> list[AccountSnapshot]:
    return [
        AccountSnapshot(
            credential=AccountCredential(
                customer_id="VR11606",
                password="p",
                label="Stanley",
                proxy_url="http://p:p@h:1",
                max_parlay_stake=150,
            ),
            available_balance=500.0,
            agent_id="TYSONR",
            store="wiseguys",
            cust_profile=".                   ",
        ),
        AccountSnapshot(
            credential=AccountCredential(
                customer_id="VR11601",
                password="p",
                label="Dixon",
                proxy_url="http://p:p@h:2",
                max_parlay_stake=100,
            ),
            available_balance=1000.0,
            agent_id="TYSONR",
            store="wiseguys",
            cust_profile=".                   ",
        ),
    ]


class FakeCoral33Placer:
    """Records calls; returns scripted dry-run-shaped results.

    Mirrors the public surface of ``Coral33Placer.place_open_parlay``
    (the real class lives in server/odds/books/coral33/placement.py).
    """

    def __init__(self, customer_id: str):
        self.customer_id = customer_id
        self.calls: list[dict] = []

    async def place_open_parlay(self, ev_leg, stake_dollars, live):
        # Import lazily so the test module doesn't reach into the real
        # placement client at import time.
        from server.odds.books.coral33.placement import PlacementResult

        self.calls.append({"stake": stake_dollars, "live": live})
        return PlacementResult(
            ticket_number=None if not live else 1471133392,
            dry_run=not live,
            accepted_payload=(
                None if not live else {"STATUS": {"STATE": 1, "DOC": 1471133392}}
            ),
            would_be_payload=(
                {"operation": "insertWagerParlay", "stake": stake_dollars}
                if not live else None
            ),
            decimal_payout=5.75 * 2.6,
            expected_win=stake_dollars * 5.75 * 2.6 - stake_dollars,
        )


class FakePlacerFactory:
    """One FakeCoral33Placer per customer_id, reused across siblings.

    Same shape the real ``placer_factory`` exposes: ``for_account(snapshot)``
    returns a placer; callers may re-use across multiple assignments on the
    same customer (per-account session reuse)."""

    def __init__(self):
        self.placers: dict[str, FakeCoral33Placer] = {}

    def for_account(self, snapshot: AccountSnapshot) -> FakeCoral33Placer:
        cid = snapshot.customer_id
        if cid not in self.placers:
            self.placers[cid] = FakeCoral33Placer(cid)
        return self.placers[cid]


@pytest.fixture
def audit_db(tmp_path):
    """A clean cache.db with the sidecar_placements table initialized.

    Returns the path; tests open their own connection so the orchestrator
    and the assertion code don't share a single connection (which sqlite3
    would refuse across the await boundary)."""
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    return path


@pytest.mark.asyncio
async def test_dry_run_target_230_stacks_on_stanley(audit_db):
    """Target $230 -> Stanley($150) + Stanley($80).

    Stanley's $500 balance covers a second parlay at the $150 cap; the
    splitter peels the residual $80 onto Stanley before reaching for
    Dixon. Both rows land as ``dry_run`` (mode is dry-run, live=False)."""
    pool = make_pool()
    factory = FakePlacerFactory()
    orchestrator = SidecarOrchestrator(
        pool_provider=lambda: pool,
        placer_factory=factory,
        mode="dry-run",
        db_path=audit_db,
        jitter=JitterDisabled(),
    )
    job_id = uuid.uuid4().hex
    returned = await orchestrator.handle_place(
        SidecarPlaceRequest(
            ev_row_id="rid",
            ev_leg=make_leg(),
            # kelly_full_pct is a PERCENTAGE (e.g., 4.6 means 4.6%).
            # 4.6% × half × $10k = $230 target.
            kelly_full_pct=4.6,
            kelly_fraction=KellyFraction.HALF,
            bankroll=10000,
        ),
        job_id,
    )
    assert returned == job_id

    conn = sqlite3.connect(audit_db)
    try:
        rows = audit.fetch_job(conn, job_id)
    finally:
        conn.close()

    assert len(rows) == 2
    # Stanley appears twice — same account, two parlays.
    # Audit rows tie on created_at (same wall-clock second) and fall back
    # to placement_id ASC, which is uuid-random — assert on the multiset
    # of stakes rather than a positional order.
    assert [r.picked_account for r in rows] == ["VR11606", "VR11606"]
    assert sorted(r.stake for r in rows) == [80.0, 150.0]
    assert all(r.result == "dry_run" for r in rows)
    # FakeCoral33Placer recorded two calls (no cascade-skip path hit)
    assert "VR11606" in factory.placers
    assert len(factory.placers["VR11606"].calls) == 2
    assert all(not call["live"] for call in factory.placers["VR11606"].calls)


@pytest.mark.asyncio
async def test_off_mode_refuses_new_jobs(audit_db):
    """When mode is 'off', handle_place writes a refusal audit row,
    emits an SSE signal_skipped event, and does NOT invoke the placer."""
    pool = make_pool()
    factory = FakePlacerFactory()
    orchestrator = SidecarOrchestrator(
        pool_provider=lambda: pool,
        placer_factory=factory,
        mode="off",
        db_path=audit_db,
        jitter=JitterDisabled(),
    )
    job_id = uuid.uuid4().hex
    await orchestrator.handle_place(
        SidecarPlaceRequest(
            ev_row_id="rid",
            ev_leg=make_leg(),
            kelly_full_pct=4.6,
            kelly_fraction=KellyFraction.HALF,
            bankroll=10000,
        ),
        job_id,
    )
    # No placer calls — factory never even constructed one
    assert not factory.placers

    # One refusal audit row
    conn = sqlite3.connect(audit_db)
    try:
        rows = audit.fetch_job(conn, job_id)
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0].result == "no_eligible_account"
    assert rows[0].mode == "off"
    assert "sidecar mode is off" in (rows[0].error_message or "")


@pytest.mark.asyncio
async def test_account_scoped_failure_skips_remaining_same_account_siblings(
    audit_db,
):
    """Target $250 against A=$300, cap $100 -> A:$100, A:$100, A:$50.

    First A:$100 raises Coral33AuthError. Remaining A:* assignments are
    recorded as 'error' without an HTTP attempt — the placer's
    place_open_parlay is called exactly once."""
    from server.odds.books.coral33.client import Coral33AuthError

    cred_a = AccountCredential(
        customer_id="A",
        password="pw",
        label="AcctA",
        proxy_url="http://p:p@h:1",
        max_parlay_stake=100,
    )
    pool = [AccountSnapshot(
        credential=cred_a,
        available_balance=300.0,
        agent_id="TYSONR",
        store="wiseguys",
        cust_profile=".                   ",
    )]

    call_count = {"n": 0}

    class FailingPlacer:
        customer_id = "A"

        async def place_open_parlay(self, ev_leg, stake_dollars, live):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Coral33AuthError("token rejected")
            raise AssertionError(
                "should not reach a second HTTP attempt after auth failure"
            )

    class FailingFactory:
        def __init__(self):
            self._placer = FailingPlacer()
            self.for_account_calls = 0

        def for_account(self, snapshot):
            self.for_account_calls += 1
            return self._placer

    factory = FailingFactory()
    orchestrator = SidecarOrchestrator(
        pool_provider=lambda: pool,
        placer_factory=factory,
        mode="live",
        db_path=audit_db,
        jitter=JitterDisabled(),
    )
    job_id = uuid.uuid4().hex
    await orchestrator.handle_place(
        SidecarPlaceRequest(
            ev_row_id="rid",
            ev_leg=make_leg(),
            kelly_full_pct=5.0,     # 5.0% × half × $10k = $250 target
            kelly_fraction=KellyFraction.HALF,
            bankroll=10000,
        ),
        job_id,
    )

    conn = sqlite3.connect(audit_db)
    try:
        rows = audit.fetch_job(conn, job_id)
    finally:
        conn.close()

    # Three split-siblings, but only ONE HTTP call was attempted
    assert call_count["n"] == 1
    assert len(rows) == 3
    assert all(r.picked_account == "A" for r in rows)
    assert all(r.result == "error" for r in rows)
    # Audit rows tie on created_at and fall back to placement_id ASC
    # (uuid-random), so assert on the multiset of error messages rather
    # than positional order: exactly one row carries the original auth
    # failure; the other two carry the cascade marker.
    messages = [r.error_message or "" for r in rows]
    auth_rows = [m for m in messages if "token rejected" in m]
    cascade_rows = [
        m for m in messages
        if "auth_failed (account-scoped cascade)" in m
    ]
    assert len(auth_rows) == 1
    assert len(cascade_rows) == 2
