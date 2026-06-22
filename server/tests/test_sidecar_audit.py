"""Round-trip persistence tests for sidecar_placements I/O.

Covers the four shapes the audit row can take:
  - successful live placement (ticket + accepted payload)
  - dry-run placement (mode='dry-run')
  - pre-flight refusal (no picked_account, stake=None)
  - ordering (recent placements newest-first)

Plus the explicit ``trigger_source`` field added in the plan's latest
amendment — placements may be triggered by the user (default) or by the
delta-tick loop refreshing an armed signal.
"""
from __future__ import annotations

import json
import sqlite3
import time
from uuid import uuid4

import pytest

from server.odds.cache import init_schema_on_path
from server.sidecar.audit import (
    AuditRow,
    fetch_job,
    fetch_placements,
    insert_placement,
)


@pytest.fixture
def conn(tmp_path):
    """Return a sqlite3 connection with the sidecar_placements table."""
    path = tmp_path / "test_cache.db"
    init_schema_on_path(path)
    c = sqlite3.connect(path)
    yield c
    c.close()


def test_insert_then_fetch_by_job(conn):
    job_id = uuid4().hex
    row = AuditRow(
        placement_id=uuid4().hex,
        job_id=job_id,
        created_at=int(time.time()),
        ev_row_id="619136397|h2h|new_zealand",
        ev_leg=json.dumps({"team": "New Zealand", "price": 475}),
        parlay_name="10 team",
        kelly_fraction="half",
        target_stake=130.0,
        stake=100.0,
        mode="live",
        picked_account="VR11606",
        result="placed",
        ticket_number="1471133392",
        accepted_payload=json.dumps({"STATUS": {"STATE": 1, "DOC": 1471133392}}),
        error_message=None,
    )
    insert_placement(conn, row)
    fetched = fetch_job(conn, job_id)
    assert len(fetched) == 1
    assert fetched[0].picked_account == "VR11606"


def test_multiple_placements_same_job(conn):
    job_id = uuid4().hex
    for split_amount in (100, 30):
        insert_placement(conn, AuditRow(
            placement_id=uuid4().hex,
            job_id=job_id,
            created_at=int(time.time()),
            ev_row_id="rid",
            ev_leg="{}",
            parlay_name="10 team",
            kelly_fraction="half",
            target_stake=130.0,
            stake=split_amount,
            mode="live",
            picked_account="VR11606",
            result="placed",
            ticket_number=None,
            accepted_payload=None,
            error_message=None,
        ))
    rows = fetch_job(conn, job_id)
    assert len(rows) == 2
    assert sum(r.stake for r in rows) == 130.0


def test_pre_flight_refusal_row(conn):
    """no_eligible_account: picked_account NULL, stake NULL."""
    insert_placement(conn, AuditRow(
        placement_id=uuid4().hex,
        job_id=uuid4().hex,
        created_at=int(time.time()),
        ev_row_id="rid",
        ev_leg="{}",
        parlay_name="10 team",
        kelly_fraction="half",
        target_stake=200.0,
        stake=None,
        mode="live",
        picked_account=None,
        result="no_eligible_account",
        ticket_number=None,
        accepted_payload=None,
        error_message="lowest balance $20 < required $30",
    ))
    rows = fetch_placements(conn, limit=1)
    assert rows[0].result == "no_eligible_account"
    assert rows[0].picked_account is None


def test_recent_placements_orders_newest_first(conn):
    older_id = uuid4().hex
    newer_id = uuid4().hex
    insert_placement(conn, AuditRow(
        placement_id=older_id, job_id=older_id, created_at=1000,
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=30, stake=30, mode="dry-run",
        picked_account="VR11601", result="dry_run",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    insert_placement(conn, AuditRow(
        placement_id=newer_id, job_id=newer_id, created_at=2000,
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=30, stake=30, mode="dry-run",
        picked_account="VR11601", result="dry_run",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    rows = fetch_placements(conn, limit=2)
    assert rows[0].placement_id == newer_id
    assert rows[1].placement_id == older_id


def test_trigger_source_defaults_to_user(conn):
    """Omitting trigger_source on AuditRow yields 'user' on round-trip."""
    pid = uuid4().hex
    insert_placement(conn, AuditRow(
        placement_id=pid, job_id=pid, created_at=int(time.time()),
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=30, stake=30, mode="dry-run",
        picked_account="VR11601", result="dry_run",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    rows = fetch_placements(conn, limit=1)
    assert rows[0].trigger_source == "user"


def test_trigger_source_delta_tick_round_trips(conn):
    """Explicit trigger_source='delta_tick' round-trips through the DB."""
    pid = uuid4().hex
    insert_placement(conn, AuditRow(
        placement_id=pid, job_id=pid, created_at=int(time.time()),
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=30, stake=30, mode="live",
        picked_account="VR11601", result="placed",
        ticket_number="123", accepted_payload=None, error_message=None,
        trigger_source="delta_tick",
    ))
    rows = fetch_placements(conn, limit=1)
    assert rows[0].trigger_source == "delta_tick"


def test_fetch_placements_respects_limit(conn):
    """fetch_placements honors the limit parameter."""
    for i in range(5):
        pid = uuid4().hex
        insert_placement(conn, AuditRow(
            placement_id=pid, job_id=pid, created_at=1000 + i,
            ev_row_id="r", ev_leg="{}", parlay_name="10 team",
            kelly_fraction="half", target_stake=30, stake=30, mode="dry-run",
            picked_account="VR11601", result="dry_run",
            ticket_number=None, accepted_payload=None, error_message=None,
        ))
    rows = fetch_placements(conn, limit=3)
    assert len(rows) == 3


def test_fetch_job_returns_empty_for_unknown_job(conn):
    assert fetch_job(conn, "no-such-job") == []


def test_fetch_job_orders_by_created_at_ascending(conn):
    """Within a job, placements are ordered oldest-first so the UI can
    show the natural chronological order of split attempts."""
    job_id = uuid4().hex
    first_id = uuid4().hex
    second_id = uuid4().hex
    # Insert out-of-order to verify the ORDER BY clause does the work.
    insert_placement(conn, AuditRow(
        placement_id=second_id, job_id=job_id, created_at=2000,
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=60, stake=30, mode="live",
        picked_account="VR2", result="placed",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    insert_placement(conn, AuditRow(
        placement_id=first_id, job_id=job_id, created_at=1000,
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=60, stake=30, mode="live",
        picked_account="VR1", result="placed",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    rows = fetch_job(conn, job_id)
    assert [r.placement_id for r in rows] == [first_id, second_id]
