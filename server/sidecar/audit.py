"""sidecar_placements I/O — one row per placement attempt.

Audit-grade: every attempt (including pre-flight refusals and dry-runs) lands
here. Never deleted by code; user can DELETE manually.

The ``trigger_source`` column distinguishes user-initiated placements from
delta-tick re-arms. It defaults to ``'user'`` on the dataclass so callers
that don't care about the distinction (e.g. the original /api/sidecar/place
route) can omit it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal


Result = Literal[
    "placed", "dry_run",
    "no_eligible_account", "below_minimum", "partial_fill",
    "error",
]

TriggerSource = Literal["user", "delta_tick"]


@dataclass
class AuditRow:
    placement_id: str
    job_id: str
    created_at: int
    ev_row_id: str
    ev_leg: str               # JSON-encoded LegSpec
    parlay_name: str
    kelly_fraction: str       # 'full' | 'half' | 'quarter'
    target_stake: float
    stake: float | None
    mode: str                 # 'dry-run' | 'live'
    picked_account: str | None
    result: Result
    ticket_number: str | None
    accepted_payload: str | None
    error_message: str | None
    # New in plan amendment: distinguishes user-clicks from delta-tick refires.
    # Default 'user' so older call sites stay terse.
    trigger_source: TriggerSource = "user"


def insert_placement(conn: sqlite3.Connection, row: AuditRow) -> None:
    """Insert a single placement attempt. Commits the transaction.

    No conflict handling — placement_ids are UUIDs minted in-process, so a
    collision would indicate a bug worth surfacing as an IntegrityError.
    """
    conn.execute(
        """
        INSERT INTO sidecar_placements (
            placement_id, job_id, created_at, ev_row_id, ev_leg,
            parlay_name, kelly_fraction, target_stake, stake, mode,
            picked_account, result, ticket_number, accepted_payload,
            error_message, trigger_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.placement_id, row.job_id, row.created_at, row.ev_row_id,
            row.ev_leg, row.parlay_name, row.kelly_fraction,
            row.target_stake, row.stake, row.mode, row.picked_account,
            row.result, row.ticket_number, row.accepted_payload,
            row.error_message, row.trigger_source,
        ),
    )
    conn.commit()


def fetch_job(conn: sqlite3.Connection, job_id: str) -> list[AuditRow]:
    """All placements for a given job_id, oldest-first.

    Tied rows fall back to placement_id ASC for a stable order — handy when
    the splitter writes multiple rows in the same wall-clock second.
    """
    cur = conn.execute(
        "SELECT placement_id, job_id, created_at, ev_row_id, ev_leg, "
        "parlay_name, kelly_fraction, target_stake, stake, mode, "
        "picked_account, result, ticket_number, accepted_payload, "
        "error_message, trigger_source "
        "FROM sidecar_placements WHERE job_id = ? "
        "ORDER BY created_at ASC, placement_id ASC",
        (job_id,),
    )
    return [_row_from_cursor(r, cur) for r in cur.fetchall()]


def fetch_placements(
    conn: sqlite3.Connection, limit: int = 100,
) -> list[AuditRow]:
    """Most recent ``limit`` placements across all jobs, newest-first."""
    cur = conn.execute(
        "SELECT placement_id, job_id, created_at, ev_row_id, ev_leg, "
        "parlay_name, kelly_fraction, target_stake, stake, mode, "
        "picked_account, result, ticket_number, accepted_payload, "
        "error_message, trigger_source "
        "FROM sidecar_placements "
        "ORDER BY created_at DESC, placement_id DESC LIMIT ?",
        (limit,),
    )
    return [_row_from_cursor(r, cur) for r in cur.fetchall()]


def _row_from_cursor(r, cur) -> AuditRow:
    cols = [c[0] for c in cur.description]
    return AuditRow(**dict(zip(cols, r)))
