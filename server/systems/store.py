from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import SystemSignal


class SystemSignalStore:
    def __init__(self, path: Path):
        self.path = path
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_signals (
                    signal_key TEXT PRIMARY KEY,
                    system_id TEXT NOT NULL,
                    system_name TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    commence_time TEXT NOT NULL,
                    bet_type TEXT NOT NULL,
                    selection TEXT NOT NULL,
                    market_line REAL,
                    -- `best_book` predates the switch to Coral33-only
                    -- pricing; it now holds SystemSignal.book. Kept under
                    -- the old name so existing rows need no migration.
                    price_american INTEGER,
                    best_book TEXT,
                    qualification_reason TEXT NOT NULL,
                    data_timestamp TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
            """)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _key(signal: SystemSignal) -> str:
        return "|".join((
            signal.system_id, signal.event_id, signal.bet_type,
            signal.selection, str(signal.market_line),
        ))

    def record(self, signals: list[SystemSignal]) -> None:
        if not signals:
            return
        with self._conn() as conn:
            conn.executemany("""
                INSERT INTO system_signals (
                    signal_key, system_id, system_name, sport, event_id,
                    home_team, away_team, commence_time, bet_type, selection,
                    market_line, price_american, best_book,
                    qualification_reason, data_timestamp, first_seen_at,
                    last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_key) DO UPDATE SET
                    price_american=excluded.price_american,
                    best_book=excluded.best_book,
                    qualification_reason=excluded.qualification_reason,
                    data_timestamp=excluded.data_timestamp,
                    last_seen_at=excluded.last_seen_at
            """, [(
                self._key(s), s.system_id, s.system_name, s.sport, s.event_id,
                s.home_team, s.away_team, s.commence_time.isoformat(),
                s.bet_type, s.selection, s.market_line, s.price_american,
                s.book, s.qualification_reason,
                s.data_timestamp.isoformat(), s.evaluated_at.isoformat(),
                s.evaluated_at.isoformat(),
            ) for s in signals])

    def list_all(self) -> list[dict]:
        with self._conn() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM system_signals ORDER BY first_seen_at DESC"
            )]
