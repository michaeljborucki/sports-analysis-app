from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshot (
  event_id       TEXT NOT NULL,
  home_team      TEXT NOT NULL,
  away_team      TEXT NOT NULL,
  commence_time  TEXT NOT NULL,
  bookmaker_key  TEXT NOT NULL,
  market_key     TEXT NOT NULL,
  outcome_name   TEXT NOT NULL,
  outcome_point  REAL NOT NULL DEFAULT 0.0,
  price_american INTEGER NOT NULL,
  fetched_at     TEXT NOT NULL,
  PRIMARY KEY (event_id, bookmaker_key, market_key, outcome_name, outcome_point)
);

CREATE INDEX IF NOT EXISTS idx_odds_event ON odds_snapshot(event_id);

CREATE TABLE IF NOT EXISTS fetcher_status (
  key                TEXT PRIMARY KEY,
  last_fetch_at      TEXT,
  requests_used      INTEGER,
  requests_remaining INTEGER,
  last_error         TEXT
);
"""


class OddsCache:
    def __init__(self, path: Path):
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    def upsert(self, rows: Iterable[dict]) -> None:
        prepared = []
        for r in rows:
            ct = r["commence_time"]
            fa = r["fetched_at"]
            # SQLite treats NULL as distinct in UNIQUE constraints, so coerce to
            # a sentinel (0.0) when the point is absent. For h2h/moneyline the
            # column is meaningless and consumers ignore it.
            point = r.get("outcome_point")
            prepared.append({
                **r,
                "commence_time": ct.isoformat() if isinstance(ct, datetime) else ct,
                "fetched_at": fa.isoformat() if isinstance(fa, datetime) else fa,
                "outcome_point": 0.0 if point is None else float(point),
            })
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO odds_snapshot
                  (event_id, home_team, away_team, commence_time,
                   bookmaker_key, market_key, outcome_name, outcome_point,
                   price_american, fetched_at)
                VALUES
                  (:event_id, :home_team, :away_team, :commence_time,
                   :bookmaker_key, :market_key, :outcome_name, :outcome_point,
                   :price_american, :fetched_at)
                ON CONFLICT(event_id, bookmaker_key, market_key, outcome_name, outcome_point)
                DO UPDATE SET
                   price_american = excluded.price_american,
                   fetched_at     = excluded.fetched_at,
                   commence_time  = excluded.commence_time,
                   home_team      = excluded.home_team,
                   away_team      = excluded.away_team
                """,
                prepared,
            )

    def all_current(self) -> list[dict]:
        with self._conn() as c:
            rows = []
            for r in c.execute("SELECT * FROM odds_snapshot"):
                d = dict(r)
                # Reverse the sentinel for h2h markets where point is meaningless
                if d.get("market_key") == "h2h":
                    d["outcome_point"] = None
                rows.append(d)
            return rows

    def set_status(self, *, last_fetch_at: datetime | None = None,
                   requests_used: int | None = None,
                   requests_remaining: int | None = None,
                   last_error: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO fetcher_status (key, last_fetch_at, requests_used, requests_remaining, last_error)
                VALUES ('default', :lf, :ru, :rr, :le)
                ON CONFLICT(key) DO UPDATE SET
                   last_fetch_at = COALESCE(:lf, last_fetch_at),
                   requests_used = COALESCE(:ru, requests_used),
                   requests_remaining = COALESCE(:rr, requests_remaining),
                   last_error = :le
                """,
                {
                    "lf": last_fetch_at.isoformat() if last_fetch_at else None,
                    "ru": requests_used,
                    "rr": requests_remaining,
                    "le": last_error,
                },
            )

    def get_status(self) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM fetcher_status WHERE key='default'").fetchone()
            return dict(row) if row else None

    def purge_finished_games(self, now: datetime, past_hours: int = 6) -> int:
        """Delete rows for any event whose commence_time is more than `past_hours`
        behind `now`. Returns count removed."""
        cutoff = (now - timedelta(hours=past_hours)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM odds_snapshot WHERE commence_time < ?",
                (cutoff,),
            )
            return cur.rowcount
