"""Alternative odds READ source backed by the central betting-db SQLite.

FLAG-GATED AND INERT BY DEFAULT. Nothing in this module runs unless
``ODDS_SOURCE=betting_db`` is set in the environment; with the default
``ODDS_SOURCE=native`` every read entry point in ``cache.py`` takes the
exact code path it took before this module existed.

What this does NOT change, in either mode:
  * the fetchers — this repo's Odds API / coral33 / kalshi / polymarket
    pollers keep running and keep WRITING to ``server/cache.db``;
  * ``cache_mode``, placement, or any Coral33 code;
  * any write path on ``odds_snapshot``.

betting-db (``~/personal_workspace/betting-db``) is a separate poller
process that writes its own SQLite at ``data/odds.db``. We open it
READ-ONLY (``file:...?mode=ro``) — never write, never migrate.

Shape contract
--------------
Every function here returns rows in the EXACT shape the corresponding
``OddsCache`` method returns today (same keys, same types, same
post-processing), so downstream scanners cannot tell the difference:

  event_id, sport_key, league_key, league_title, home_team, away_team,
  commence_time, bookmaker_key, market_key, outcome_name, outcome_point,
  price_american, fetched_at, wager_type, max_stake_dollars

Mapping decisions from betting-db's ``latest_odds`` to that shape:

  sport_key      betting-db's ``sport_key`` is the Odds API key
                 ("baseball_mlb"); betting-site's is the app-level sport
                 ("mlb"). Resolved through ``server.sports.SPORTS``
                 (prefix-aware, so "tennis_atp_us_open" -> "tennis" and
                 "basketball_nba_summer_league" -> "nba", matching how
                 betting-site folds Summer League into the NBA tab).
                 Rows whose Odds API key maps to no betting-site sport
                 (betting-db covers ncaab / esports, betting-site does
                 not) are dropped rather than invented.
  league_key     Mirrors ``normalize_odds_response``: the Odds API sport
                 key for soccer only, NULL for every other sport.
  league_title   NULL. betting-db does not persist the Odds API's
                 ``sport_title``, so soccer competition LABELS are
                 unavailable in this mode (``league_key`` still is).
  outcome_name   betting-db keeps the prop / team-total subject in its
                 own ``outcome_description`` column; betting-site folds
                 it into ``outcome_name``. Folded here with the very same
                 ``normalize._encode_outcome_name`` (player-name
                 canonicalization included).
  outcome_point  betting-db keeps NULL for pointless markets; the
                 ``odds_snapshot`` column is NOT NULL DEFAULT 0.0, so
                 NULL -> 0.0 — then ``all_current``'s h2h reverse-
                 sentinel (0.0 -> None for market_key == "h2h") is
                 re-applied on top, exactly as the native path does.
  wager_type,    NULL. Both are direct-book-only columns (coral33 wager
  max_stake_     eligibility, Kalshi/Polymarket top-of-book depth); the
  dollars        Odds API carries neither, so native-mode Odds API rows
                 carry NULL here too. Direct-book rows keep their real
                 values because they come from the native cache (below).

Direct books
------------
betting-db polls the Odds API only. This repo's coral33 / kalshi /
polymarket fetchers write straight into ``odds_snapshot`` and have no
betting-db equivalent, so every read here UNIONS betting-db's Odds API
rows with the native cache's direct-book rows. Without that union the
EV / arb / low-hold scanners would lose the coral33 side of every
opportunity and silently go quiet.

``kalshi`` rows coming FROM betting-db are dropped, mirroring
``normalize._EXCLUDE_BOOKMAKERS``: the direct kalshi poller's quotes own
that cache slot and the Odds API copy is minutes stale.

Freshness
---------
The native cache is continuously pruned (``purge_stale_rows`` at 600s,
``purge_finished_games`` at 6h past commence). betting-db is an archive
and prunes neither, so the same two windows are applied as read filters
here — otherwise this mode would surface lines betting-site would never
show. Both are env-tunable for debugging but default to the native
purge defaults.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from .normalize import _EXCLUDE_BOOKMAKERS, _encode_outcome_name


logger = logging.getLogger(__name__)


# Books this repo polls directly. Their rows live only in the native
# cache, so they are unioned in on every read.
DIRECT_BOOK_KEYS: frozenset[str] = frozenset({"coral33", "kalshi", "polymarket"})

# Mirrors OddsCache.purge_stale_rows' default (600s = 2x the Odds API
# poll interval) and purge_finished_games' default (6h).
DEFAULT_MAX_AGE_SECONDS = 600
DEFAULT_PAST_HOURS = 6

# Column order of `odds_snapshot`, i.e. the key order `SELECT *` yields
# in the native path. Kept explicit so adapter rows compare equal to
# native rows key-for-key.
_SNAPSHOT_COLUMNS = (
    "event_id", "sport_key", "league_key", "league_title",
    "home_team", "away_team", "commence_time", "bookmaker_key",
    "market_key", "outcome_name", "outcome_point", "price_american",
    "fetched_at", "wager_type", "max_stake_dollars",
)


def _max_age_seconds() -> int:
    return int(os.environ.get("BETTING_DB_MAX_AGE_SECONDS", DEFAULT_MAX_AGE_SECONDS))


def _past_hours() -> int:
    return int(os.environ.get("BETTING_DB_PAST_HOURS", DEFAULT_PAST_HOURS))


def _db_path() -> str:
    from ..config import Config
    return str(Config.from_env().betting_db_path)


def _connect() -> sqlite3.Connection:
    """Open betting-db READ-ONLY. Safe alongside its live writer (WAL)."""
    path = _db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────── sport mapping ───────────────────────────

_SPORT_BY_ODDS_KEY: dict[str, str] | None = None
_SPORT_PREFIXES: list[tuple[str, str]] | None = None


def _build_sport_index() -> None:
    global _SPORT_BY_ODDS_KEY, _SPORT_PREFIXES
    from ..sports import SPORTS
    exact: dict[str, str] = {}
    prefixes: list[tuple[str, str]] = []
    for app_key, sport in SPORTS.items():
        for oak in sport.odds_api_sport_keys:
            if oak.endswith("*"):
                prefixes.append((oak[:-1], app_key))
            else:
                exact[oak] = app_key
    _SPORT_BY_ODDS_KEY = exact
    _SPORT_PREFIXES = prefixes


def app_sport_for(odds_api_sport_key: str) -> str | None:
    """Map an Odds API sport key to betting-site's app-level sport key.

    Uses `server/sports.py` as the single source of truth, including its
    prefix entries ("tennis_atp_*"). Returns None for sports betting-db
    covers but betting-site does not.
    """
    if _SPORT_BY_ODDS_KEY is None:
        _build_sport_index()
    assert _SPORT_BY_ODDS_KEY is not None and _SPORT_PREFIXES is not None
    hit = _SPORT_BY_ODDS_KEY.get(odds_api_sport_key)
    if hit:
        return hit
    for prefix, app_key in _SPORT_PREFIXES:
        if odds_api_sport_key.startswith(prefix):
            return app_key
    return None


# ─────────────────────────── row mapping ─────────────────────────────

def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _iso_z(dt: datetime) -> str:
    """betting-db's on-disk timestamp form (Z-suffixed UTC)."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm_ts(value: str | None) -> str | None:
    """betting-db's `...Z` timestamps -> the `...+00:00` form the native
    cache stores (`datetime.isoformat()` on a tz-aware value).

    Parity matters twice over: adapter rows must compare equal to native
    rows field-for-field, and the unioned direct-book rows are compared
    against these as raw strings by the event listers — mixed `Z` /
    `+00:00` forms would sort inconsistently at the boundary.
    """
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:  # pragma: no cover — defensive; pass through
        return value


def _mapped_rows(sport_key: str | None = None) -> list[dict]:
    """betting-db `latest_odds` -> `odds_snapshot`-shaped rows.

    `sport_key` is betting-site's APP sport ("mlb"), matching the native
    `all_current(sport_key=...)` parameter — not betting-db's column of
    the same name.
    """
    now = datetime.now(timezone.utc)
    # Cutoffs are compared lexicographically against betting-db's stored
    # strings, so they must be in betting-db's `...Z` form.
    fetched_cutoff = _iso_z(now - timedelta(seconds=_max_age_seconds()))
    commence_cutoff = _iso_z(now - timedelta(hours=_past_hours()))

    q = (
        "SELECT sport_key, league_key, event_id, commence_time, home_team, "
        "away_team, bookmaker_key, market_key, outcome_name, "
        "outcome_description, outcome_point, price_american, fetched_at "
        "FROM latest_odds WHERE fetched_at >= ? AND commence_time >= ?"
    )
    args: list = [fetched_cutoff, commence_cutoff]

    conn = _connect()
    try:
        raw = conn.execute(q, args).fetchall()
    finally:
        conn.close()

    # Keyed by odds_snapshot's PK so post-fold collisions resolve
    # last-write-wins, exactly as OddsCache.upsert's ON CONFLICT does.
    out: dict[tuple, dict] = {}
    for r in raw:
        book = r["bookmaker_key"]
        if book in _EXCLUDE_BOOKMAKERS:
            continue
        app_sport = app_sport_for(r["sport_key"])
        if app_sport is None:
            continue
        if sport_key is not None and app_sport != sport_key:
            continue
        market_key = r["market_key"]
        point = r["outcome_point"]
        point = 0.0 if point is None else float(point)
        name = _encode_outcome_name(
            market_key, r["outcome_name"], r["outcome_description"],
            sport_key=app_sport,
        )
        row = {
            "event_id": r["event_id"],
            "sport_key": app_sport,
            # normalize_odds_response only sets league_key/title for soccer.
            "league_key": r["sport_key"] if app_sport == "soccer" else None,
            # betting-db does not persist the Odds API's sport_title.
            "league_title": None,
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "commence_time": _norm_ts(r["commence_time"]),
            "bookmaker_key": book,
            "market_key": market_key,
            "outcome_name": name,
            "outcome_point": point,
            "price_american": int(r["price_american"]),
            "fetched_at": _norm_ts(r["fetched_at"]),
            "wager_type": None,
            "max_stake_dollars": None,
        }
        out[(row["event_id"], book, market_key, name, point)] = row

        # NRFI bridge — same synthesis normalize_odds_response performs,
        # so coral33's `nrfi` market still has Odds API prices to pair
        # against in this mode.
        if market_key in (
            "totals_1st_1_innings", "alternate_totals_1st_1_innings",
        ) and point == 0.5:
            nrfi_outcome = {"Over": "Yes", "Under": "No"}.get(r["outcome_name"])
            if nrfi_outcome is not None:
                nrfi_row = {
                    **row,
                    "market_key": "nrfi",
                    "outcome_name": nrfi_outcome,
                    "outcome_point": 0.0,
                }
                out[(row["event_id"], book, "nrfi", nrfi_outcome, 0.0)] = nrfi_row

    return list(out.values())


def _direct_book_rows(cache, sport_key: str | None = None) -> list[dict]:
    """Native-cache rows for books betting-db does not poll.

    Calls `_all_current_native` rather than `all_current` — the latter
    dispatches straight back here in this mode.
    """
    return [
        r for r in cache._all_current_native(sport_key)
        if r.get("bookmaker_key") in DIRECT_BOOK_KEYS
    ]


# ───────────────────── read entry points (mirrors) ────────────────────

def _pk(row: dict) -> tuple:
    """`odds_snapshot`'s primary key for one row, with the h2h reverse-
    sentinel undone so a None point and a 0.0 point address the same slot
    (exactly what the native table's NOT NULL DEFAULT 0.0 column does)."""
    point = row.get("outcome_point")
    return (
        row["event_id"], row["bookmaker_key"], row["market_key"],
        row["outcome_name"], 0.0 if point is None else float(point),
    )


def all_current(cache, sport_key: str | None = None) -> list[dict]:
    """Drop-in for `OddsCache.all_current`."""
    rows = _mapped_rows(sport_key)
    for d in rows:
        # Reverse the sentinel for h2h markets where point is meaningless
        # — verbatim from the native all_current().
        if d.get("market_key") == "h2h":
            d["outcome_point"] = None
    merged = {_pk(r): r for r in rows}
    # Direct-book rows WIN on a PK collision. betting-db carries the Odds
    # API's own `polymarket` quotes, which in native mode land in the very
    # same `odds_snapshot` PK slot as the direct WS feed's rows — so
    # emitting both here would double-count a book that the native path
    # only ever shows once. The direct row is the one to keep: it's
    # fresher and it's the only one carrying `max_stake_dollars` /
    # `wager_type`.
    for r in _direct_book_rows(cache, sport_key):
        merged[_pk(r)] = r
    return list(merged.values())


def event_sport_key(cache, event_id: str) -> str | None:
    """Drop-in for `OddsCache.event_sport_key`."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT sport_key FROM latest_odds WHERE event_id = ? LIMIT 1",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        mapped = app_sport_for(row["sport_key"])
        if mapped is not None:
            return mapped
    # Direct-book events (coral33/kalshi/polymarket-only) never reach
    # betting-db; fall back to the native cache for them.
    return cache._event_sport_key_native(event_id)


def _group_events(rows: list[dict]) -> list[dict]:
    """GROUP BY event_id with MAX() on the projected columns — the
    Python equivalent of the SQL both event listers run."""
    by_event: dict[str, dict] = {}
    for r in rows:
        ev = by_event.get(r["event_id"])
        if ev is None:
            by_event[r["event_id"]] = {
                "event_id": r["event_id"],
                "sport_key": r["sport_key"],
                "commence_time": r["commence_time"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
            }
            continue
        for col in ("sport_key", "commence_time", "home_team", "away_team"):
            val = r[col]
            cur = ev[col]
            if cur is None or (val is not None and val > cur):
                ev[col] = val
    return list(by_event.values())


def distinct_events(
    cache,
    within_hours_ahead: int | None = None,
    sport_key: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Drop-in for `OddsCache.distinct_events`."""
    rows = _mapped_rows(sport_key) + _direct_book_rows(cache, sport_key)
    events = _group_events(rows)
    if within_hours_ahead is None:
        return events
    ts_now = now if now is not None else datetime.now(timezone.utc)
    horizon = ts_now + timedelta(hours=within_hours_ahead)
    lo, hi = _iso(ts_now), _iso(horizon)
    out: list[dict] = []
    for e in events:
        if not (lo <= e["commence_time"] <= hi):
            continue
        ct = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        out.append({**e, "commence_time": ct})
    return out


def events_in_close_window(
    cache,
    now: datetime,
    lead_minutes: int = 15,
    trail_minutes: int = 5,
) -> list[dict]:
    """Drop-in for `OddsCache.events_in_close_window`."""
    start = _iso(now + timedelta(minutes=trail_minutes))
    end = _iso(now + timedelta(minutes=lead_minutes))
    rows = _mapped_rows() + _direct_book_rows(cache)
    return [
        e for e in _group_events(rows)
        if start <= e["commence_time"] <= end
    ]
