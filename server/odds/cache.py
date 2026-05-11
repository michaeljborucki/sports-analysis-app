from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshot (
  event_id       TEXT NOT NULL,
  sport_key      TEXT NOT NULL DEFAULT 'mlb',
  home_team      TEXT NOT NULL,
  away_team      TEXT NOT NULL,
  commence_time  TEXT NOT NULL,
  bookmaker_key  TEXT NOT NULL,
  market_key     TEXT NOT NULL,
  outcome_name   TEXT NOT NULL,
  outcome_point  REAL NOT NULL DEFAULT 0.0,
  price_american INTEGER NOT NULL,
  fetched_at     TEXT NOT NULL,
  wager_type     TEXT,
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


# Schema migrations applied after CREATE IF NOT EXISTS. Each entry is a SQL
# statement that's tolerant of being re-run.
_MIGRATIONS = [
    # 0.2: add sport_key column (defaulted to 'mlb' for existing rows)
    "ALTER TABLE odds_snapshot ADD COLUMN sport_key TEXT NOT NULL DEFAULT 'mlb'",
    # 0.3: per-row coral33 wager-type tag — "straight", "parlay", "both", or
    # NULL for non-coral33 rows (the column is meaningless for Odds API books).
    "ALTER TABLE odds_snapshot ADD COLUMN wager_type TEXT",
]


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
            # Apply idempotent migrations — tolerate "duplicate column" errors
            # if an older schema has already been bumped.
            for stmt in _MIGRATIONS:
                try:
                    c.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            # Ensure the index exists after migrations
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_odds_sport ON odds_snapshot(sport_key)"
            )

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
                "sport_key": r.get("sport_key", "mlb"),
                "commence_time": ct.isoformat() if isinstance(ct, datetime) else ct,
                "fetched_at": fa.isoformat() if isinstance(fa, datetime) else fa,
                "outcome_point": 0.0 if point is None else float(point),
                "wager_type": r.get("wager_type"),
            })
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO odds_snapshot
                  (event_id, sport_key, home_team, away_team, commence_time,
                   bookmaker_key, market_key, outcome_name, outcome_point,
                   price_american, fetched_at, wager_type)
                VALUES
                  (:event_id, :sport_key, :home_team, :away_team, :commence_time,
                   :bookmaker_key, :market_key, :outcome_name, :outcome_point,
                   :price_american, :fetched_at, :wager_type)
                ON CONFLICT(event_id, bookmaker_key, market_key, outcome_name, outcome_point)
                DO UPDATE SET
                   price_american = excluded.price_american,
                   fetched_at     = excluded.fetched_at,
                   commence_time  = excluded.commence_time,
                   home_team      = excluded.home_team,
                   away_team      = excluded.away_team,
                   sport_key      = excluded.sport_key,
                   wager_type     = excluded.wager_type
                """,
                prepared,
            )

    def all_current(self, sport_key: str | None = None) -> list[dict]:
        """All cached rows, optionally filtered to a single sport."""
        q = "SELECT * FROM odds_snapshot"
        args: tuple = ()
        if sport_key:
            q += " WHERE sport_key = ?"
            args = (sport_key,)
        with self._conn() as c:
            rows = []
            for r in c.execute(q, args):
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

    def purge_live_rows_for_book(self, bookmaker_key: str, now: datetime) -> int:
        """Delete rows from a specific book whose game has already started.
        Used for coral33: its in-play prices aren't trusted by the sharp devig
        model so we keep them out of every scanner's universe."""
        cutoff = now.isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM odds_snapshot WHERE bookmaker_key = ? AND commence_time <= ?",
                (bookmaker_key, cutoff),
            )
            return cur.rowcount

    def purge_stale_rows(self, now: datetime, max_age_seconds: int = 600) -> int:
        """Delete rows whose `fetched_at` is older than `max_age_seconds`.

        UPSERTs only touch rows the fetcher re-sees on each cycle — any row
        for a (event, book, market, outcome, point) tuple that the book
        STOPPED offering stays in the DB with a frozen `fetched_at` until a
        sweep like this clears it. Without this, the UI shows "coral33 still
        has this line at +350" for hours after coral actually dropped it.

        Default 600s (10 min) = 2× the Odds API poll interval (300s). A
        single missed / timed-out / rate-limited poll cycle has one full
        cycle of grace before its rows get purged. Coral33's 240s cycle
        fits inside this easily. Tight alignment with poll cadence also
        means the cache shows roughly "everything the book posted within
        the last two polls" — no older, no younger.
        """
        cutoff = (now - timedelta(seconds=max_age_seconds)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM odds_snapshot WHERE fetched_at < ?",
                (cutoff,),
            )
            return cur.rowcount

    def distinct_events(
        self,
        within_hours_ahead: int | None = None,
        sport_key: str | None = None,
    ) -> list[dict]:
        """List distinct (event_id, sport_key, commence_time, home, away)
        known to the cache, optionally filtering by sport + time window."""
        from datetime import datetime, timezone
        q = """
            SELECT event_id, MAX(sport_key) AS sport_key,
                   MAX(commence_time) AS commence_time,
                   MAX(home_team) AS home_team, MAX(away_team) AS away_team
            FROM odds_snapshot
        """
        args: tuple = ()
        if sport_key:
            q += " WHERE sport_key = ?"
            args = (sport_key,)
        q += " GROUP BY event_id"
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(q, args)]
        if within_hours_ahead is None:
            return rows
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=within_hours_ahead)
        out = []
        for r in rows:
            ct = datetime.fromisoformat(r["commence_time"])
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            if now <= ct <= horizon:
                out.append({**r, "commence_time": ct})
        return out
