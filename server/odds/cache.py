from __future__ import annotations

import asyncio
import functools
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


logger = logging.getLogger(__name__)


# Debounce window for the in-memory cache version counter. WS upserts
# (Kalshi + Polymarket) call `_bump_version()` per row, which blew up
# the scanner memos hundreds of times per minute during live games.
# Coalescing bumps inside a 200ms window means lots of WS writes
# collapse to ONE version change — the scanner memo's cache-version
# fingerprint then holds, and the 5 scanner endpoints reuse the same
# cached scan instead of re-running.
#
# 200ms is short enough that user-perceived freshness is unaffected
# (well below human-perceptible UI update latency) but long enough to
# coalesce typical WS bursts. Aligned in spirit with the SSE flush_loop
# in events.py — both batch state-change signals at the boundary
# closest to consumers.
VERSION_FLUSH_INTERVAL_S = 0.2


VALID_ODDS_SOURCES = ("native", "betting_db")

# Last value `_odds_source()` resolved, so the resolved source is logged
# ONCE (at the first odds read after startup) instead of per call — and
# again if it ever changes underneath a running process.
_logged_odds_source: str | None = None


def _odds_source() -> str:
    """Which store the READ entry points below serve rows from.

    "native" (the default, and what every deployment does today) means
    the methods on this class behave exactly as they always have. Only
    an explicit ODDS_SOURCE=betting_db diverts reads to
    `bettingdb_source`. The WRITE path — upsert, purges, the fetchers
    feeding them — is untouched in both modes.

    NOTE: in betting_db mode `distinct_events` and `event_sport_key`
    decide the PAID per-event Odds API worklist in `fetcher.py`; see
    `bettingdb_source`'s module docstring.

    An unrecognized value falls back to "native" with a loud warning
    rather than erroring or silently doing something else — a typo in
    ODDS_SOURCE must never leave the reads in an undefined state.

    Read per call rather than cached so flipping the env var takes
    effect without a restart, and so tests can toggle it with
    monkeypatch. Config.from_env() is pure os.environ reads; the cost is
    nil next to the SQLite scan that follows.
    """
    global _logged_odds_source
    from ..config import Config
    raw = (Config.from_env().odds_source or "").strip()
    source = raw if raw in VALID_ODDS_SOURCES else "native"
    if source != raw:
        logger.warning(
            "ODDS_SOURCE=%r is not one of %s — falling back to 'native'. "
            "Odds reads are served from this repo's own cache.db.",
            raw, list(VALID_ODDS_SOURCES),
        )
    if source != _logged_odds_source:
        _logged_odds_source = source
        logger.info("odds read source resolved to %r", source)
    return source


SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshot (
  event_id       TEXT NOT NULL,
  sport_key      TEXT NOT NULL DEFAULT 'mlb',
  league_key     TEXT,
  league_title   TEXT,
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
  max_stake_dollars REAL,
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

-- Unified bet ledger across every source: coral33 mirror, kalshi
-- portfolio fills, polymarket trades, and CSV imports. One row per
-- ticket / fill / position / import row. CLV is computed at query
-- time against `closing_lines` — never persisted here.
CREATE TABLE IF NOT EXISTS bets (
  source_book      TEXT NOT NULL,
  external_id      TEXT NOT NULL,
  customer_id      TEXT,
  accepted_at      TEXT NOT NULL,
  settled_at       TEXT,
  status           TEXT NOT NULL,
  wager_type       TEXT NOT NULL,
  total_picks      INTEGER NOT NULL DEFAULT 1,
  sport_key        TEXT,
  event_id         TEXT,
  home_team        TEXT,
  away_team        TEXT,
  market_key       TEXT,
  outcome_name     TEXT,
  outcome_point    REAL NOT NULL DEFAULT 0.0,
  odds_american    INTEGER,
  stake            REAL NOT NULL,
  to_win           REAL,
  settled_amount   REAL,
  is_free_play     INTEGER NOT NULL DEFAULT 0,
  raw_description  TEXT,
  imported_at      TEXT,
  PRIMARY KEY (source_book, external_id)
);

CREATE INDEX IF NOT EXISTS idx_bets_accepted ON bets(accepted_at);
CREATE INDEX IF NOT EXISTS idx_bets_event    ON bets(event_id);
CREATE INDEX IF NOT EXISTS idx_bets_book     ON bets(source_book);
CREATE INDEX IF NOT EXISTS idx_bets_status   ON bets(status);

-- Auto-bet sidecar: one row per placement attempt (live or dry-run, success
-- or refusal). Audit-grade — never deleted by code. trigger_source records
-- whether the user clicked Auto-place ('user') or the delta-tick loop fired
-- a refresh ('delta_tick').
CREATE TABLE IF NOT EXISTS sidecar_placements (
  placement_id     TEXT PRIMARY KEY,
  job_id           TEXT NOT NULL,
  created_at       INTEGER NOT NULL,
  ev_row_id        TEXT NOT NULL,
  ev_leg           TEXT NOT NULL,
  parlay_name      TEXT NOT NULL DEFAULT '10 team',
  kelly_fraction   TEXT NOT NULL,
  target_stake     REAL NOT NULL,
  stake            REAL,
  mode             TEXT NOT NULL,
  picked_account   TEXT,
  result           TEXT NOT NULL,
  ticket_number    TEXT,
  accepted_payload TEXT,
  error_message    TEXT,
  trigger_source   TEXT NOT NULL DEFAULT 'user'    -- 'user' | 'delta_tick'
);
CREATE INDEX IF NOT EXISTS sidecar_placements_job_id
  ON sidecar_placements(job_id);
CREATE INDEX IF NOT EXISTS sidecar_placements_ev_row_id
  ON sidecar_placements(ev_row_id);
CREATE INDEX IF NOT EXISTS sidecar_placements_created_at
  ON sidecar_placements(created_at DESC);

-- Auto-bet sidecar: one row per armed +EV signal currently in-flight. The
-- delta-tick loop reads this table to know which rows to revisit; rows are
-- inserted when the user arms a signal and removed when the signal expires
-- (commence_time passed) or is manually cleared.
CREATE TABLE IF NOT EXISTS sidecar_active_signals (
  ev_row_id          TEXT PRIMARY KEY,
  kelly_fraction     TEXT NOT NULL,
  bankroll_at_arm    INTEGER NOT NULL,
  commence_time      INTEGER NOT NULL,
  total_placed       REAL NOT NULL DEFAULT 0,
  first_armed_at     INTEGER NOT NULL,
  last_checked_at    INTEGER,
  last_delta_at      INTEGER,
  last_target        REAL,
  -- Pinned account for the autonomous delta-tick: when the user armed
  -- the signal via the account-first /sidecar flow, future top-ups must
  -- fire on the SAME account (not splitter-picked). NULL = pre-account-
  -- first signal; delta-tick falls back to legacy splitter for it.
  armed_customer_id  TEXT
);
CREATE INDEX IF NOT EXISTS sidecar_active_signals_commence
  ON sidecar_active_signals(commence_time);
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
    # 0.5: per-row top-of-book depth in dollars. NULL for sportsbook
    # rows (no depth data) and pre-migration rows; populated by the
    # Polymarket WS ingest path and the Kalshi orderbook poller.
    "ALTER TABLE odds_snapshot ADD COLUMN max_stake_dollars REAL",
    # 0.6: account-first sidecar — pin signals to the customer_id the
    # user picked at arm time. Existing rows (pre-account-first) keep
    # NULL and the delta-tick falls back to the legacy splitter for them.
    "ALTER TABLE sidecar_active_signals ADD COLUMN armed_customer_id TEXT",
    # 0.7: Odds API's soccer competition identifiers and names. NULL for
    # non-soccer rows and direct-book rows without provider metadata.
    "ALTER TABLE odds_snapshot ADD COLUMN league_key TEXT",
    "ALTER TABLE odds_snapshot ADD COLUMN league_title TEXT",
]


def _init_schema(conn: sqlite3.Connection) -> None:
    """Apply SCHEMA, idempotent migrations, and post-migration indexes.

    Module-level so tests can spin up a temp DB with the full schema
    without instantiating ``OddsCache`` (and without polluting the global
    ``server/cache.db``). Called by both ``OddsCache.init`` and
    ``init_schema_on_path``.
    """
    conn.executescript(SCHEMA)
    # Apply idempotent migrations — tolerate "duplicate column" errors
    # if an older schema has already been bumped.
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
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
        # Composite covering index for distinct_events() / events_in_close_window().
        # Even with the HAVING pushdown those queries still SCAN odds_snapshot
        # to satisfy the GROUP BY event_id and the MAX(...) selects on the
        # other event-identity columns. This index orders rows so SQLite can
        # walk it once in event_id order — the leading column drives the
        # GROUP BY, the rest cover the MAX(...) projections so SQLite never
        # needs to revisit the table heap.
        "CREATE INDEX IF NOT EXISTS idx_odds_event_commence "
        "ON odds_snapshot(event_id, commence_time, sport_key, home_team, away_team)",
    ):
        conn.execute(idx_stmt)


def init_schema_on_path(path) -> None:
    """Initialize the cache schema at a given path.

    Used by tests so each test gets a clean DB without touching the
    global ``server/cache.db``. Accepts anything ``sqlite3.connect``
    accepts (str or pathlib.Path).
    """
    conn = sqlite3.connect(str(path))
    try:
        _init_schema(conn)
        conn.commit()
    finally:
        conn.close()


class OddsCache:
    def __init__(self, path: Path):
        self.path = path
        # Monotonic in-memory version counter. Bumped at most once per
        # VERSION_FLUSH_INTERVAL_S window by `_version_flush_loop`.
        # Scanner endpoints fold this into their TTLCache keys so a
        # quiet stretch (no upserts) re-hits the memo even after the
        # 20s TTL expires, collapsing a re-scan of the 100MB+ SQLite
        # cache into a single dict lookup.
        #
        # In-memory (not persisted) is intentional: a server restart
        # legitimately invalidates every scanner memo anyway (the memo
        # itself is in-process), so persisting the counter would add a
        # write per upsert for zero gain.
        self._version: int = 0
        # Debounce flag — set synchronously by `_bump_version()`, read
        # and cleared by the background flush loop. Read/write of a
        # Python bool is atomic under the GIL; a write between the
        # loop's read and clear is captured on the next iteration.
        self._version_dirty: bool = False

    @property
    def version(self) -> int:
        """Monotonic counter incremented at most once per
        VERSION_FLUSH_INTERVAL_S window when any state-changing op
        has occurred since the previous flush.

        Stable while the cache contents are unchanged — safe to include
        in scanner TTLCache keys so unchanged-cache requests memo-hit
        across the TTL boundary. Lags behind individual writes by up
        to one flush interval, which is the whole point: bursts of WS
        upserts (Kalshi/Polymarket fire per row) collapse to a single
        memo invalidation instead of hundreds.
        """
        return self._version

    def _bump_version(self) -> None:
        """Mark the cache version as dirty. The actual counter
        increment is deferred to the next `_version_flush_loop` tick,
        which coalesces bursts of bumps into one version change per
        VERSION_FLUSH_INTERVAL_S window.

        Sync flag-set — safe to call from any context (no running
        event loop required, no awaits). Mirrors the pattern in
        `server/odds/events.py`'s `mark_dirty()` / `flush_loop()`.
        """
        self._version_dirty = True
        # Notify the SSE event broadcaster that cache state changed.
        # Sync flag-set — safe to call from any context (no running
        # event loop required, no awaits). The SSE flush_loop coalesces
        # bursts of bumps into one outbound tick per 1s window.
        # Lazy import keeps `cache.py` standalone for tests that
        # instantiate OddsCache without the rest of the server stack.
        try:
            from . import events as _events
            _events.mark_dirty()
        except Exception:  # pragma: no cover — never let SSE break upserts
            pass

    def _flush_version_now(self) -> bool:
        """Apply a pending version bump immediately, if any.

        Returns True if the counter was incremented, False if no
        bump was pending. Used by `_version_flush_loop` (production
        path) and by tests that want the synchronous pre-debounce
        behavior without spinning up the flush task.
        """
        if self._version_dirty:
            # Clear before increment so any concurrent _bump_version
            # during this call is captured on the next flush tick.
            self._version_dirty = False
            self._version += 1
            # Bust the per-version memo so the next all_current_cached()
            # call rebuilds against the new version.
            try:
                self._all_current_for_version.cache_clear()
            except Exception:  # pragma: no cover — defensive
                pass
            return True
        return False

    async def version_flush_loop(self) -> None:
        """Background task: every VERSION_FLUSH_INTERVAL_S, increment
        the version counter ONCE if any `_bump_version()` calls have
        occurred since the previous tick. Multiple bumps in the window
        coalesce to a single version change — that's the whole point.

        Started from FastAPI's lifespan context next to the SSE
        flush_loop; cancelled on shutdown. Exceptions during a single
        tick are logged so a transient failure doesn't kill the loop.
        """
        logger.info(
            "OddsCache version_flush_loop starting (interval=%.2fs)",
            VERSION_FLUSH_INTERVAL_S,
        )
        while True:
            try:
                await asyncio.sleep(VERSION_FLUSH_INTERVAL_S)
                self._flush_version_now()
            except asyncio.CancelledError:
                logger.info("OddsCache version_flush_loop cancelled")
                raise
            except Exception:
                logger.exception(
                    "OddsCache version_flush_loop iteration failed; continuing"
                )

    # `lru_cache` on an instance method holds `self` in the cache key, so
    # the cache survives across instances. In practice OddsCache is a
    # process-wide singleton, so the leak is bounded to one entry — the
    # latest version's materialized rows — and is GC'd on every bump via
    # `_flush_version_now`'s `cache_clear()`.
    @functools.lru_cache(maxsize=1)
    def _all_current_for_version(self, version: int) -> list[dict]:
        """Materialized rows for a specific cache version. lru_cache=1
        means only the latest version is held; the previous gets GC'd as
        soon as a new bump lands (and `_flush_version_now` clears the
        cache eagerly on every version change for promptness)."""
        return self.all_current()

    def all_current_cached(self) -> list[dict]:
        """Cache-version-aware wrapper around `all_current()`.

        All callers in one tick (e.g. the Edges page firing arb + lh +
        ev + free_bet + profit_boost on the same SWR revalidation)
        share the same materialized row list — second-and-later callers
        get an O(1) lookup returning the SAME list object by identity.
        Memoization invalidates on the next version bump.
        """
        if _odds_source() == "betting_db":
            # The version counter only advances on THIS repo's upserts;
            # betting-db's poller writes into its own DB and never bumps
            # it, so a version-keyed memo would pin the first scan
            # forever. `bettingdb_source` carries its own short-TTL memo
            # that gives the same one-scan-per-tick sharing.
            return self.all_current()
        return self._all_current_for_version(self.version)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            # 10s busy timeout (default is 5s). With WAL the contention
            # window is much smaller but readers can still wait during
            # the brief commit/checkpoint windows; 10s is plenty.
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        # Per-connection PRAGMAs. journal_mode=WAL is persistent across
        # connections (it's a database property, not per-connection), but
        # setting it here guarantees it on a fresh DB. The rest are
        # per-connection and must be set every time.
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")          # readers never block writers
        cur.execute("PRAGMA synchronous=NORMAL")        # safe under WAL; 2-3× faster commits
        cur.execute("PRAGMA cache_size=-65536")         # 64 MB page cache (was 8 MB)
        cur.execute("PRAGMA mmap_size=268435456")       # 256 MB mmap window
        cur.execute("PRAGMA temp_store=MEMORY")         # closest-line ORDER BY uses temp btrees
        cur.execute("PRAGMA wal_autocheckpoint=1000")   # checkpoint every 1000 pages (~4MB)
        cur.close()
        return conn

    def init(self) -> None:
        with self._conn() as c:
            _init_schema(c)

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
                "league_key": r.get("league_key"),
                "league_title": r.get("league_title"),
                "commence_time": ct.isoformat() if isinstance(ct, datetime) else ct,
                "fetched_at": fa.isoformat() if isinstance(fa, datetime) else fa,
                "outcome_point": 0.0 if point is None else float(point),
                "wager_type": r.get("wager_type"),
                "max_stake_dollars": r.get("max_stake_dollars"),
            })
        if not prepared:
            # No-op input — don't churn the version counter and pointlessly
            # invalidate the scanner memos.
            return
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO odds_snapshot
                  (event_id, sport_key, league_key, league_title, home_team, away_team, commence_time,
                   bookmaker_key, market_key, outcome_name, outcome_point,
                   price_american, fetched_at, wager_type, max_stake_dollars)
                VALUES
                  (:event_id, :sport_key, :league_key, :league_title, :home_team, :away_team, :commence_time,
                   :bookmaker_key, :market_key, :outcome_name, :outcome_point,
                   :price_american, :fetched_at, :wager_type, :max_stake_dollars)
                ON CONFLICT(event_id, bookmaker_key, market_key, outcome_name, outcome_point)
                DO UPDATE SET
                   price_american = excluded.price_american,
                   fetched_at     = excluded.fetched_at,
                   commence_time  = excluded.commence_time,
                   home_team      = excluded.home_team,
                   away_team      = excluded.away_team,
                   sport_key      = excluded.sport_key,
                   league_key     = COALESCE(NULLIF(TRIM(excluded.league_key), ''), odds_snapshot.league_key),
                   league_title   = COALESCE(NULLIF(TRIM(excluded.league_title), ''), odds_snapshot.league_title),
                   wager_type     = excluded.wager_type,
                   max_stake_dollars = COALESCE(excluded.max_stake_dollars, max_stake_dollars)
                """,
                prepared,
            )
        self._bump_version()

    def all_current(self, sport_key: str | None = None) -> list[dict]:
        """All cached rows, optionally filtered to a single sport."""
        if _odds_source() == "betting_db":
            from . import bettingdb_source
            return bettingdb_source.all_current(self, sport_key)
        return self._all_current_native(sport_key)

    def _all_current_native(self, sport_key: str | None = None) -> list[dict]:
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
        if _odds_source() == "betting_db":
            from . import bettingdb_source
            return bettingdb_source.event_sport_key(self, event_id)
        return self._event_sport_key_native(event_id)

    def _event_sport_key_native(self, event_id: str) -> str | None:
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

    def purge_live_rows_for_book(
        self, bookmaker_key: str, now: datetime,
        grace_seconds: int = 0,
    ) -> int:
        """Delete rows from a specific book whose game has been live
        for more than `grace_seconds`. Default 0 — any row whose
        commence_time <= now gets purged. Used for coral33 with
        grace_seconds=1800 (30 minutes) so delayed / soft-start games
        don't lose their pre-game lines while actual kickoff is still
        pending.
        """
        # Guard against clock skew / negative input — never expand the
        # purge window past `now`.
        grace = max(int(grace_seconds), 0)
        cutoff_dt = now - timedelta(seconds=grace)
        cutoff = cutoff_dt.isoformat()
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

    def find_closing_lines_bulk(
        self,
        addresses: list[tuple[str, str, str, float | None]],
    ) -> dict[tuple[str, str, str, float | None], dict]:
        """Batched exact-match version of `find_closing_line`.

        Address tuple: (event_id, market_key, outcome_name, outcome_point).
        Returns a dict keyed by the input tuple. Addresses with no
        matching closing line are simply absent from the result —
        callers should check `address in result`.

        Trades the closest-line fallback for ONE query instead of N. The
        /api/bets path fires ~150 individual lookups per page load
        (~1.4s warm cost); batching collapses that to a single round
        trip. Callers needing the closest-line fallback (e.g. backfill
        scripts) keep using `find_closing_line` per-row.
        """
        if not addresses:
            return {}
        # Normalize NULL outcome_point to the sentinel (0.0) used at
        # write time so the row-value match lines up with the stored
        # PK column.
        normalized: list[tuple[str, str, str, float]] = []
        for ev, mk, on, pt in addresses:
            normalized.append((ev, mk, on, 0.0 if pt is None else float(pt)))
        # Build `IN (VALUES (?,?,?,?), (?,?,?,?), ...)` parameter
        # expansion. SQLite supports row-value IN with a VALUES list —
        # verified on 3.51 (and back to 3.15 where row-value comparison
        # was added).
        placeholders = ", ".join(["(?,?,?,?)"] * len(normalized))
        params: list = []
        for tup in normalized:
            params.extend(tup)
        q = (
            "SELECT * FROM closing_lines "
            "WHERE (event_id, market_key, outcome_name, outcome_point) "
            f"IN (VALUES {placeholders})"
        )
        with self._conn() as c:
            rows = c.execute(q, params).fetchall()
        out: dict[tuple[str, str, str, float | None], dict] = {}
        # Map results back onto the caller's original address tuples
        # (so a caller that passed outcome_point=None gets None back in
        # the key, not the 0.0 sentinel).
        addr_by_normalized = {n: a for n, a in zip(normalized, addresses)}
        for r in rows:
            d = dict(r)
            norm_key = (
                d["event_id"], d["market_key"],
                d["outcome_name"], float(d["outcome_point"]),
            )
            orig = addr_by_normalized.get(norm_key)
            if orig is not None:
                out[orig] = d
        return out

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
        if _odds_source() == "betting_db":
            from . import bettingdb_source
            return bettingdb_source.events_in_close_window(
                self, now, lead_minutes, trail_minutes,
            )
        return self._events_in_close_window_native(
            now, lead_minutes, trail_minutes,
        )

    def _events_in_close_window_native(
        self,
        now: datetime,
        lead_minutes: int = 15,
        trail_minutes: int = 5,
    ) -> list[dict]:
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

    def purge_closing_lines_older_than(self, days: int = 90) -> int:
        """Delete `closing_lines` rows whose commence_time is older
        than `days` ago. Returns number of rows deleted. Idempotent.

        Scheduled to run daily in `server/main.py` because
        closing_lines was the dominant cache.db consumer (140 MB / 62%
        with no expiry mechanism). 90 days keeps recent CLV analysis
        intact — older bets in the `bets` table simply report "CLV
        unavailable" once their closing lines drop out, which is fine.

        Sibling to `purge_old_closing_lines(now, days=60)`: this one
        takes only a duration and uses `datetime.utcnow()` internally
        so apscheduler can call it via a no-arg lambda. The other is
        invoked from `_capture_tick` with the same `now` it uses for
        capture, to keep tick semantics tight.
        """
        from datetime import datetime as _dt, timezone as _tz
        cutoff = (_dt.now(_tz.utc) - timedelta(days=days)).isoformat()
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
        now: datetime | None = None,
    ) -> list[dict]:
        """List distinct (event_id, sport_key, commence_time, home, away)
        known to the cache, optionally filtering by sport + time window.

        When `within_hours_ahead` is set, the time filter is applied as
        `HAVING MAX(commence_time) BETWEEN ? AND ?` on the GROUP BY —
        preserves the historical Python-filter semantics (filter on the
        per-event MAX, not on raw rows that may disagree on
        commence_time). `now` is injected for testability.
        """
        if _odds_source() == "betting_db":
            from . import bettingdb_source
            return bettingdb_source.distinct_events(
                self, within_hours_ahead, sport_key, now,
            )
        return self._distinct_events_native(
            within_hours_ahead, sport_key, now,
        )

    def _distinct_events_native(
        self,
        within_hours_ahead: int | None = None,
        sport_key: str | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        from datetime import datetime as _dt, timezone as _tz
        q_parts: list[str] = ["""
            SELECT event_id, MAX(sport_key) AS sport_key,
                   MAX(commence_time) AS commence_time,
                   MAX(home_team) AS home_team, MAX(away_team) AS away_team
            FROM odds_snapshot
        """]
        args: list = []
        if sport_key:
            q_parts.append("WHERE sport_key = ?")
            args.append(sport_key)
        q_parts.append("GROUP BY event_id")
        if within_hours_ahead is not None:
            ts_now = now if now is not None else _dt.now(_tz.utc)
            horizon = ts_now + timedelta(hours=within_hours_ahead)
            q_parts.append(
                "HAVING MAX(commence_time) >= ? AND MAX(commence_time) <= ?"
            )
            args.extend([ts_now.isoformat(), horizon.isoformat()])
        q = " ".join(q_parts)
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(q, args)]
        if within_hours_ahead is None:
            return rows
        # Parse commence_time → datetime for callers (preserves the v1
        # API: returned commence_time is datetime when within_hours_ahead
        # is set, raw string otherwise).
        out: list[dict] = []
        for r in rows:
            ct = _dt.fromisoformat(r["commence_time"])
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=_tz.utc)
            out.append({**r, "commence_time": ct})
        return out
