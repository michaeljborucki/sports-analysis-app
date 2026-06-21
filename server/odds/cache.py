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

-- Closing-line snapshots used for CLV computation. One row per
-- (event, market, outcome). Captured ~5min before kickoff from the
-- sharp-book consensus in odds_snapshot, then devigged.
--
-- Survives the 10-min purge on odds_snapshot because closing prices need
-- to outlive the live cache: a bet placed on May 1 needs its closing
-- price still queryable in June.
CREATE TABLE IF NOT EXISTS closing_lines (
  event_id          TEXT NOT NULL,
  sport_key         TEXT NOT NULL,
  home_team         TEXT NOT NULL,
  away_team         TEXT NOT NULL,
  market_key        TEXT NOT NULL,
  outcome_name      TEXT NOT NULL,
  outcome_point     REAL NOT NULL DEFAULT 0.0,
  close_odds        INTEGER NOT NULL,
  close_prob_devig  REAL NOT NULL,
  commence_time     TEXT NOT NULL,
  captured_at       TEXT NOT NULL,
  source_books      TEXT,
  PRIMARY KEY (event_id, market_key, outcome_name, outcome_point)
);

CREATE INDEX IF NOT EXISTS idx_closing_event ON closing_lines(event_id);
CREATE INDEX IF NOT EXISTS idx_closing_commence ON closing_lines(commence_time);
CREATE INDEX IF NOT EXISTS idx_closing_teams
  ON closing_lines(sport_key, home_team, away_team);

-- Point-in-time balance snapshots imported from an external scraper.
-- Used to overlay the daily-balance chart with pending values for days
-- that fall OUTSIDE the wager-log's 2-week rolling window (Coral33's
-- daily-figures endpoint only carries CURRENT pending — so without
-- this overlay, old chart days render pending=0 even when there
-- genuinely was money on open wagers).
--
-- One row per (customer_id, captured_at). A given local-date may have
-- many snapshots; consumers (e.g. the history endpoint) usually want
-- the LATEST snapshot per (customer_id, local_date), so they query
-- with ORDER BY captured_at DESC.
CREATE TABLE IF NOT EXISTS balance_snapshots (
  customer_id      TEXT NOT NULL,
  captured_at      TEXT NOT NULL,          -- ISO datetime (local naive or UTC)
  local_date       TEXT NOT NULL,          -- YYYY-MM-DD of captured_at
  current_balance  REAL NOT NULL DEFAULT 0,
  pending          REAL NOT NULL DEFAULT 0,
  available        REAL NOT NULL DEFAULT 0,
  free_play        REAL NOT NULL DEFAULT 0,
  source           TEXT,                   -- 'manual_import', 'scraper', etc.
  PRIMARY KEY (customer_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_balance_snap_date
  ON balance_snapshots(customer_id, local_date);
"""


# Schema migrations applied after CREATE IF NOT EXISTS. Each entry is a SQL
# statement that's tolerant of being re-run.
_MIGRATIONS = [
    # 0.2: add sport_key column (defaulted to 'mlb' for existing rows)
    "ALTER TABLE odds_snapshot ADD COLUMN sport_key TEXT NOT NULL DEFAULT 'mlb'",
    # 0.3: per-row coral33 wager-type tag — "straight", "parlay", "both", or
    # NULL for non-coral33 rows (the column is meaningless for Odds API books).
    "ALTER TABLE odds_snapshot ADD COLUMN wager_type TEXT",
    # 0.4: closing_lines team-name columns. Defensive — the CREATE TABLE
    # above defines them, but if an earlier dev build initialized the table
    # without these columns the migration backfills them.
    "ALTER TABLE closing_lines ADD COLUMN home_team TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE closing_lines ADD COLUMN away_team TEXT NOT NULL DEFAULT ''",
]


class OddsCache:
    def __init__(self, path: Path):
        self.path = path
        # Monotonic in-memory version counter. Bumps on every successful
        # state-changing op (upsert + the three purge methods). Scanner
        # endpoints fold this into their TTLCache keys so a quiet stretch
        # (no upserts) re-hits the memo even after the 20s TTL expires,
        # collapsing a re-scan of the 100MB+ SQLite cache into a single
        # dict lookup.
        #
        # In-memory (not persisted) is intentional: a server restart
        # legitimately invalidates every scanner memo anyway (the memo
        # itself is in-process), so persisting the counter would add a
        # write per upsert for zero gain. CPython's GIL makes the
        # `self._version += 1` increment atomic across coroutines that
        # share this instance.
        self._version: int = 0

    @property
    def version(self) -> int:
        """Monotonic counter incremented on every state-changing op.

        Stable while the cache contents are unchanged — safe to include
        in scanner TTLCache keys so unchanged-cache requests memo-hit
        across the TTL boundary.
        """
        return self._version

    def _bump_version(self) -> None:
        # GIL makes this atomic in CPython. Documented for clarity.
        self._version += 1

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
            # Ensure indexes exist after migrations. These cover the hot
            # access patterns the audit identified:
            #   - purge_stale_rows() filters on fetched_at every main-tier
            #     cycle; without this index it's a full table scan on a
            #     100MB+ table every few minutes.
            #   - all endpoint scanners filter by sport_key (existing) and
            #     usually also by market_key / is_prop_market — composite
            #     lets SQLite skip prop rows at the query stage.
            #   - purge_finished_games() and the FUTURE_WINDOW filter on
            #     commence_time run on every dashboard/odds request.
            for idx_stmt in (
                "CREATE INDEX IF NOT EXISTS idx_odds_sport ON odds_snapshot(sport_key)",
                "CREATE INDEX IF NOT EXISTS idx_odds_fetched_at ON odds_snapshot(fetched_at)",
                "CREATE INDEX IF NOT EXISTS idx_odds_sport_market ON odds_snapshot(sport_key, market_key)",
                "CREATE INDEX IF NOT EXISTS idx_odds_commence_time ON odds_snapshot(commence_time)",
            ):
                c.execute(idx_stmt)

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
        if not prepared:
            # No-op input — don't churn the version counter and pointlessly
            # invalidate the scanner memos.
            return
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
        self._bump_version()

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

    def event_sport_key(self, event_id: str) -> str | None:
        """Look up the sport_key for a single event without scanning the
        whole cache. Replaces the previous `distinct_events()` call site
        in `refresh_event`, which did a full-table GROUP BY just to map
        one event to its sport. Uses the PK's leading-column index on
        event_id, so this is O(log n)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT sport_key FROM odds_snapshot WHERE event_id = ? LIMIT 1",
                (event_id,),
            ).fetchone()
            return row["sport_key"] if row else None

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
            removed = cur.rowcount
        if removed:
            self._bump_version()
        return removed

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
            removed = cur.rowcount
        if removed:
            self._bump_version()
        return removed

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
            removed = cur.rowcount
        if removed:
            self._bump_version()
        return removed

    # ───────────────────────── Closing lines ─────────────────────────

    def upsert_closing_lines(self, rows: Iterable[dict]) -> int:
        """Persist closing-line snapshots. Each row needs:
          event_id, sport_key, home_team, away_team, market_key,
          outcome_name, outcome_point, close_odds, close_prob_devig,
          commence_time, captured_at, source_books (optional)

        Re-capture of the same key overwrites with the latest price.
        Returns count of rows upserted.
        """
        prepared = []
        for r in rows:
            ct = r["commence_time"]
            ca = r["captured_at"]
            prepared.append({
                **r,
                "outcome_point": float(r.get("outcome_point") or 0.0),
                "commence_time": ct.isoformat() if isinstance(ct, datetime) else ct,
                "captured_at": ca.isoformat() if isinstance(ca, datetime) else ca,
                "source_books": r.get("source_books"),
            })
        if not prepared:
            return 0
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO closing_lines
                  (event_id, sport_key, home_team, away_team, market_key,
                   outcome_name, outcome_point, close_odds, close_prob_devig,
                   commence_time, captured_at, source_books)
                VALUES
                  (:event_id, :sport_key, :home_team, :away_team, :market_key,
                   :outcome_name, :outcome_point, :close_odds,
                   :close_prob_devig, :commence_time, :captured_at,
                   :source_books)
                ON CONFLICT(event_id, market_key, outcome_name, outcome_point)
                DO UPDATE SET
                   close_odds       = excluded.close_odds,
                   close_prob_devig = excluded.close_prob_devig,
                   captured_at      = excluded.captured_at,
                   source_books     = excluded.source_books,
                   home_team        = excluded.home_team,
                   away_team        = excluded.away_team
                """,
                prepared,
            )
        return len(prepared)

    def find_closed_events_for_teams(
        self,
        sport_key: str,
        normalized_team_a: str,
        normalized_team_b: str,
        normalize_fn,
        accepted_at: datetime | None = None,
    ) -> list[dict]:
        """Find events in `closing_lines` whose home_team / away_team
        match the given pair (in either orientation) under the supplied
        `normalize_fn(name) -> normalized`. Returns distinct event rows
        with event_id, commence_time, home_team, away_team.

        `accepted_at` (optional): when provided, only events that started
        after `accepted_at - 30 days` are returned — keeps the search
        scoped to plausible games for an old wager and avoids
        cross-season collisions.
        """
        from datetime import timedelta as _td
        cutoff = None
        if accepted_at is not None:
            cutoff = (accepted_at - _td(days=30)).isoformat()
        with self._conn() as c:
            q = (
                "SELECT DISTINCT event_id, home_team, away_team, "
                "commence_time FROM closing_lines WHERE sport_key = ?"
            )
            args: tuple = (sport_key,)
            if cutoff is not None:
                q += " AND commence_time >= ?"
                args = (*args, cutoff)
            rows = [dict(r) for r in c.execute(q, args)]
        out: list[dict] = []
        for r in rows:
            home_n = normalize_fn(r["home_team"])
            away_n = normalize_fn(r["away_team"])
            if {home_n, away_n} == {normalized_team_a, normalized_team_b}:
                out.append(r)
        return out

    def find_closing_line(
        self,
        event_id: str,
        market_key: str,
        outcome_name: str,
        outcome_point: float | None = None,
        point_tolerance: float = 0.001,
        max_fallback_distance: float = 1.0,
    ) -> dict | None:
        """Look up a closing line.

        Match rules:
          1. Exact (event_id, market_key, outcome_name, outcome_point) match
             (within `point_tolerance`, default 0.001 for float jitter).
          2. If no exact match AND outcome_point is provided, fall back to
             the closest line for the same (event, market, outcome_name)
             — but ONLY if that closest line is within
             `max_fallback_distance` of the requested point. Larger gaps
             mean the line moved enough that the close isn't comparable
             (e.g., wager at total 7.5 vs close at 9.5 — totally
             different distributions), and the resulting "CLV" would be
             garbage.
        """
        with self._conn() as c:
            point_for_sql = 0.0 if outcome_point is None else float(outcome_point)
            row = c.execute(
                """
                SELECT * FROM closing_lines
                WHERE event_id = ? AND market_key = ? AND outcome_name = ?
                  AND ABS(outcome_point - ?) < ?
                """,
                (event_id, market_key, outcome_name, point_for_sql, point_tolerance),
            ).fetchone()
            if row is not None:
                return dict(row)
            if outcome_point is None:
                return None
            # Closest-line fallback, bounded.
            row = c.execute(
                """
                SELECT *, ABS(outcome_point - ?) AS dist FROM closing_lines
                WHERE event_id = ? AND market_key = ? AND outcome_name = ?
                  AND ABS(outcome_point - ?) <= ?
                ORDER BY dist ASC
                LIMIT 1
                """,
                (
                    point_for_sql, event_id, market_key, outcome_name,
                    point_for_sql, max_fallback_distance,
                ),
            ).fetchone()
            return dict(row) if row else None

    def events_in_close_window(
        self,
        now: datetime,
        lead_minutes: int = 15,
        trail_minutes: int = 5,
    ) -> list[dict]:
        """List distinct events whose commence_time falls in the
        [now + trail_minutes, now + lead_minutes] window — i.e. about to
        start. Each returned dict carries event_id, sport_key,
        commence_time, home_team, away_team.

        Default (5, 15) = the same T-15..T-5 capture window baseball-agents
        uses; widens to capture late line moves while leaving a small
        no-touch buffer near tip-off.
        """
        start = (now + timedelta(minutes=trail_minutes)).isoformat()
        end = (now + timedelta(minutes=lead_minutes)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT event_id,
                       MAX(sport_key)     AS sport_key,
                       MAX(commence_time) AS commence_time,
                       MAX(home_team)     AS home_team,
                       MAX(away_team)     AS away_team
                FROM odds_snapshot
                WHERE commence_time BETWEEN ? AND ?
                GROUP BY event_id
                """,
                (start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    def purge_old_closing_lines(self, now: datetime, days: int = 60) -> int:
        """Delete closing-line snapshots for games that started more than
        `days` ago. Keeps the table from growing unboundedly; 60 days is
        well past the wager-log retention window so live CLV lookups stay
        covered."""
        cutoff = (now - timedelta(days=days)).isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM closing_lines WHERE commence_time < ?",
                (cutoff,),
            )
            return cur.rowcount

    # ─────────────────────── Balance snapshots ────────────────────────

    def upsert_balance_snapshots(self, rows: Iterable[dict]) -> int:
        """Insert or overwrite point-in-time balance snapshots.

        Each row needs `customer_id, captured_at, local_date,
        current_balance, pending, available, free_play, source`.
        Idempotent on (customer_id, captured_at) — re-importing the
        same dump is a no-op.
        """
        prepared = []
        for r in rows:
            ca = r["captured_at"]
            prepared.append({
                **r,
                "captured_at": ca.isoformat() if isinstance(ca, datetime) else ca,
                "current_balance": float(r.get("current_balance") or 0.0),
                "pending": float(r.get("pending") or 0.0),
                "available": float(r.get("available") or 0.0),
                "free_play": float(r.get("free_play") or 0.0),
                "source": r.get("source"),
            })
        if not prepared:
            return 0
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO balance_snapshots
                  (customer_id, captured_at, local_date, current_balance,
                   pending, available, free_play, source)
                VALUES
                  (:customer_id, :captured_at, :local_date,
                   :current_balance, :pending, :available, :free_play,
                   :source)
                ON CONFLICT(customer_id, captured_at)
                DO UPDATE SET
                   local_date      = excluded.local_date,
                   current_balance = excluded.current_balance,
                   pending         = excluded.pending,
                   available       = excluded.available,
                   free_play       = excluded.free_play,
                   source          = excluded.source
                """,
                prepared,
            )
        return len(prepared)

    def latest_balance_snapshot_per_date(
        self,
        customer_id: str,
    ) -> dict[str, dict]:
        """Return {YYYY-MM-DD: latest_snapshot_dict} for one customer.
        Each value is the most-recent snapshot taken on that local date
        — useful for "EOD balance/pending" overlays."""
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT customer_id, captured_at, local_date,
                       current_balance, pending, available, free_play
                FROM balance_snapshots
                WHERE customer_id = ?
                ORDER BY captured_at ASC
                """,
                (customer_id,),
            ).fetchall()
        out: dict[str, dict] = {}
        for r in rows:
            d = dict(r)
            # Ascending order means the LAST row per date overwrites,
            # leaving the latest captured_at as the final value.
            out[d["local_date"]] = d
        return out

    def closing_lines_for_event(self, event_id: str) -> list[dict]:
        """All closing lines captured for one event. Used by debug / API
        introspection; the per-wager lookup uses find_closing_line()."""
        with self._conn() as c:
            return [
                dict(r) for r in c.execute(
                    "SELECT * FROM closing_lines WHERE event_id = ?",
                    (event_id,),
                )
            ]

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
