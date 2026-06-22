"""Active-signal tracker for the autonomous Kelly-delta re-fire loop.

One row in sidecar_active_signals per (ev_row_id) currently being tracked.
Inserted on first user-triggered placement; updated on every successful
placement (user or delta-tick) to keep total_placed current; filtered by
commence_time > now at tick scan time."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from server.sidecar.settings import KellyFraction


@dataclass
class ActiveSignal:
    ev_row_id: str
    kelly_fraction: str         # 'full' | 'half' | 'quarter'
    bankroll_at_arm: int
    commence_time: int
    total_placed: float
    first_armed_at: int
    last_checked_at: int | None
    last_delta_at: int | None
    last_target: float | None


def arm_signal(
    conn: sqlite3.Connection,
    ev_row_id: str,
    kelly_fraction: KellyFraction,
    bankroll_at_arm: int,
    commence_time: int,
) -> None:
    """Idempotent — if the row already exists, leave total_placed alone."""
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO sidecar_active_signals
          (ev_row_id, kelly_fraction, bankroll_at_arm, commence_time,
           total_placed, first_armed_at)
        VALUES (?, ?, ?, ?, 0, ?)
        ON CONFLICT(ev_row_id) DO NOTHING
        """,
        (ev_row_id, kelly_fraction.value, bankroll_at_arm,
         commence_time, now),
    )
    conn.commit()


def update_total_placed(
    conn: sqlite3.Connection, ev_row_id: str, delta: float,
) -> None:
    """Atomically add `delta` dollars to total_placed."""
    conn.execute(
        "UPDATE sidecar_active_signals SET total_placed = total_placed + ? "
        "WHERE ev_row_id = ?",
        (float(delta), ev_row_id),
    )
    conn.commit()


def list_active(
    conn: sqlite3.Connection, *, now: int | None = None,
) -> list[ActiveSignal]:
    """Returns signals where commence_time > now (pre-game)."""
    if now is None:
        now = int(time.time())
    cur = conn.execute(
        "SELECT * FROM sidecar_active_signals WHERE commence_time > ? "
        "ORDER BY commence_time ASC",
        (now,),
    )
    return [_row(r, cur) for r in cur.fetchall()]


def get_signal(
    conn: sqlite3.Connection, ev_row_id: str,
) -> ActiveSignal | None:
    cur = conn.execute(
        "SELECT * FROM sidecar_active_signals WHERE ev_row_id = ?",
        (ev_row_id,),
    )
    r = cur.fetchone()
    return _row(r, cur) if r else None


def mark_checked(
    conn: sqlite3.Connection, ev_row_id: str,
    last_target: float | None, fired: bool,
) -> None:
    now = int(time.time())
    if fired:
        conn.execute(
            "UPDATE sidecar_active_signals "
            "SET last_checked_at = ?, last_target = ?, last_delta_at = ? "
            "WHERE ev_row_id = ?",
            (now, last_target, now, ev_row_id),
        )
    else:
        conn.execute(
            "UPDATE sidecar_active_signals "
            "SET last_checked_at = ?, last_target = ? WHERE ev_row_id = ?",
            (now, last_target, ev_row_id),
        )
    conn.commit()


def _row(r, cur) -> ActiveSignal:
    cols = [c[0] for c in cur.description]
    return ActiveSignal(**dict(zip(cols, r)))
