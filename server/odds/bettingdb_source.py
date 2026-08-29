"""Alternative odds READ source backed by the central betting-db SQLite.

FLAG-GATED AND INERT BY DEFAULT. Nothing in this module runs unless
``ODDS_SOURCE=betting_db`` is set in the environment; with the default
``ODDS_SOURCE=native`` every read entry point in ``cache.py`` takes the
exact code path it took before this module existed.

betting-db (``~/personal_workspace/betting-db``) is a separate poller
process that writes its own SQLite at ``data/odds.db``. We open it
READ-ONLY (``file:...?mode=ro``) — never write, never migrate.

What does NOT change in either mode
-----------------------------------
  * the fetchers themselves — this repo's Odds API / coral33 / kalshi /
    polymarket pollers keep running and keep WRITING to
    ``server/cache.db``;
  * ``cache_mode``, placement, or any Coral33 code;
  * any write path on ``odds_snapshot``.

What DOES change in betting_db mode — including a spend path
------------------------------------------------------------
``fetcher.py`` derives its PAID per-event Odds API worklist from two of
the read entry points this module replaces:

  * ``_run_per_event`` (fetcher.py:~418) calls
    ``distinct_events(within_hours_ahead=..., sport_key=...)`` and fires
    one billed per-event request per row it returns;
  * ``refresh_event`` (fetcher.py:~589) calls ``event_sport_key`` and
    bills a request unless it gets None ("unknown_event").

So in betting_db mode WHAT WE PAY TO FETCH is decided by betting-db's
data, not by this repo's cache. That is why both of those functions
apply the SAME freshness and commence-window filters as ``all_current``
here: betting-db is an archive that prunes nothing, and an event it
still remembers but this repo would long since have purged must resolve
to None / be absent rather than become a billed request. The native
"purged event -> None -> unknown_event -> no spend" behavior is
preserved deliberately, not incidentally.

Shape contract
--------------
Every function here returns rows in the EXACT shape the corresponding
``OddsCache`` method returns today (same keys, same order, same types,
same post-processing), so downstream scanners cannot tell the
difference:

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
  outcome_name   betting-db keeps the prop / team-total subject in its
                 own ``outcome_description`` column; betting-site folds
                 it into ``outcome_name``. Folded here with the very same
                 ``normalize._encode_outcome_name`` (player-name
                 canonicalization included).
  outcome_point  betting-db keeps NULL for pointless markets; the
                 ``odds_snapshot`` column is NOT NULL DEFAULT 0.0, so
                 NULL -> 0.0 — then ``all_current``'s h2h reverse-
                 sentinel (0.0 -> None for market_key == "h2h") is
                 applied on top, exactly as the native path does.
  wager_type,    NULL. Both are direct-book-only columns (coral33 wager
  max_stake_     eligibility, Kalshi/Polymarket top-of-book depth); the
  dollars        Odds API carries neither, so native-mode Odds API rows
                 carry NULL here too. Direct-book rows keep their real
                 values because they come from the native cache (below).
  timestamps     betting-db stores `...Z`; the native cache stores
                 `...+00:00`. Normalized to the native form on the way
                 out so adapter rows compare equal to native rows and so
                 the event listers' string comparisons stay consistent
                 across the union boundary.

Known gaps in betting_db mode
-----------------------------
  * ``league_title`` is always NULL. betting-db does not persist the
    Odds API's ``sport_title``, so soccer competition LABELS are
    unavailable; ``league_key`` (the competition identifier) still is.
    Accepted deliberately — nothing computes on the title, it is display
    text only.
  * Rows with a NULL ``home_team`` / ``away_team`` are dropped (count
    logged). ``odds_snapshot`` declares both NOT NULL, so a native row
    can never have them missing and downstream code dereferences them
    unguarded.

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
and prunes neither, so equivalent windows are applied as read filters —
otherwise this mode would surface lines betting-site would never show,
and (see above) would pay to refresh events that no longer exist.

The staleness window is CADENCE-AWARE rather than a flat 600s. A flat
600s is correct for betting-site's own ~5min poll but wrong for
betting-db, which deliberately polls far-out events slowly: a 7-day-out
event is refreshed hourly by design, so a flat 600s cutoff would hide
almost the entire forward book. Allowance per event is

    scale x (betting-db main-band interval for its commence distance)
      + slack

with scale=2 (one full missed cycle of grace, mirroring why
``purge_stale_rows`` uses 2x the poll interval) and slack=300s.
"""
from __future__ import annotations

import functools
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from .normalize import _EXCLUDE_BOOKMAKERS, _encode_outcome_name


logger = logging.getLogger(__name__)


# Books this repo polls directly. Their rows live only in the native
# cache, so they are unioned in on every read.
DIRECT_BOOK_KEYS: frozenset[str] = frozenset({"coral33", "kalshi", "polymarket"})

# Mirror of betting-db's `[[cadence.main]]` bands — the SOURCE OF TRUTH
# is ~/personal_workspace/betting-db/config.toml, and `interval_for` in
# betting_db/cadence.py is the reference implementation of the lookup.
# Mirrored rather than imported to keep this module dependency-light (no
# sys.path surgery on the betting-site server); if betting-db's bands are
# retuned, retune these to match.
# (max_hours_to_commence, poll_interval_seconds); -1 = catch-all.
CADENCE_MAIN_BANDS: tuple[tuple[float, int], ...] = (
    (1, 60),
    (12, 300),
    (48, 1800),
    (168, 3600),      # 7d
    (720, 21600),     # 30d
    (-1, 86400),
)

# Allowance = FRESHNESS_SCALE x band interval + FRESHNESS_SLACK_SECONDS.
# scale 2 mirrors why OddsCache.purge_stale_rows uses 2x the poll
# interval: one fully missed cycle gets grace before rows are considered
# dead. Slack absorbs scheduler jitter and quota stretch.
DEFAULT_FRESHNESS_SCALE = 2
DEFAULT_FRESHNESS_SLACK_SECONDS = 300

# Mirrors OddsCache.purge_finished_games' default (6h past commence).
DEFAULT_PAST_HOURS = 6

# Short-TTL memo on the betting-db scan. betting-db's own writes never
# bump this repo's cache version counter, so the version-keyed lru in
# cache.py cannot serve this mode (see `all_current_cached`). A few
# seconds is enough to collapse the Edges page's 5 concurrent scanner
# endpoints onto ONE scan while staying well inside betting-db's
# tightest 60s poll band.
MEMO_TTL_SECONDS = 5


def _env_int(name: str, default: int) -> int:
    """int() an env var, falling back loudly rather than crashing the
    read path on a typo."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.error(
            "%s=%r is not an integer; falling back to %d", name, raw, default,
        )
        return default


def _freshness_scale() -> int:
    return _env_int("BETTING_DB_FRESHNESS_SCALE", DEFAULT_FRESHNESS_SCALE)


def _freshness_slack_seconds() -> int:
    return _env_int(
        "BETTING_DB_FRESHNESS_SLACK_SECONDS", DEFAULT_FRESHNESS_SLACK_SECONDS,
    )


def _past_hours() -> int:
    return _env_int("BETTING_DB_PAST_HOURS", DEFAULT_PAST_HOURS)


def _db_path() -> str:
    from ..config import Config
    return str(Config.from_env().betting_db_path)


def _connect() -> sqlite3.Connection:
    """Open betting-db READ-ONLY. Safe alongside its live writer (WAL).

    Fails LOUD: a missing / unreadable betting-db in this mode means the
    scanners would otherwise silently see zero odds, which looks exactly
    like "no edges today". Log, then re-raise.
    """
    path = _db_path()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error:
        logger.error(
            "ODDS_SOURCE=betting_db but betting-db could not be opened "
            "read-only at %s — odds reads are FAILING, not degrading. "
            "Check BETTING_DB_PATH and that the betting-db poller has "
            "created the file.",
            path,
        )
        raise
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


def _sport_filter_sql(app_sport: str | None) -> tuple[str, list]:
    """SQL fragment restricting `latest_odds.sport_key` to one app sport.

    Pushed into SQL rather than filtered in Python: an unfiltered scan of
    the live betting-db is ~1M rows, and betting-db indexes
    latest_odds(sport_key). GLOB (not LIKE) for the prefix sports —
    LIKE's `_` is a single-char wildcard, which would make
    "tennis_atp_%" match far more than intended, and GLOB's
    case-sensitivity lets SQLite use the index for a prefix pattern.
    """
    if app_sport is None:
        return "", []
    if _SPORT_BY_ODDS_KEY is None:
        _build_sport_index()
    assert _SPORT_BY_ODDS_KEY is not None and _SPORT_PREFIXES is not None
    exact = [k for k, v in _SPORT_BY_ODDS_KEY.items() if v == app_sport]
    prefixes = [p for p, v in _SPORT_PREFIXES if v == app_sport]
    terms: list[str] = []
    params: list = []
    if exact:
        terms.append(f"sport_key IN ({','.join('?' for _ in exact)})")
        params.extend(exact)
    for p in prefixes:
        terms.append("sport_key GLOB ?")
        params.append(f"{p}*")
    if not terms:
        # Unknown app sport — match nothing, the same empty result the
        # native path's `WHERE sport_key = ?` would give.
        return " AND 0", []
    return " AND (" + " OR ".join(terms) + ")", params


# ───────────────────────── freshness windows ─────────────────────────

def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _iso_z(dt: datetime) -> str:
    """betting-db's on-disk timestamp form (Z-suffixed UTC)."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@functools.lru_cache(maxsize=65536)
def _norm_ts(value: str | None) -> str | None:
    """betting-db's `...Z` timestamps -> the `...+00:00` form the native
    cache stores (`datetime.isoformat()` on a tz-aware value).

    Memoized: this runs twice per row over a six-figure scan, but the
    distinct values are only a few thousand (one commence_time per event,
    one fetched_at per poll batch), so the parse/format round trip is
    almost always a cache hit.
    """
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:  # pragma: no cover — defensive; pass through
        return value


def allowed_age_seconds(hours_to_commence: float) -> int:
    """Staleness allowance for an event this far from commencing.

    Mirrors betting_db.cadence.interval_for's band walk, including its
    "already commenced -> tightest band" rule, then applies
    scale x interval + slack.
    """
    scale = _freshness_scale()
    slack = _freshness_slack_seconds()
    interval = CADENCE_MAIN_BANDS[-1][1]
    if hours_to_commence <= 0:
        interval = CADENCE_MAIN_BANDS[0][1]
    else:
        for max_hours, band_interval in CADENCE_MAIN_BANDS:
            if max_hours == -1:
                interval = band_interval
                break
            if hours_to_commence <= max_hours:
                interval = band_interval
                break
    return scale * interval + slack


def _freshness_sql(now: datetime) -> tuple[str, list]:
    """`WHERE` fragment implementing the commence window AND the
    cadence-aware `fetched_at` allowance.

    The allowance is expressed as a CASE over `commence_time` so the
    whole filter runs in SQLite instead of materializing the archive in
    Python. Each band contributes one (commence horizon, fetched_at
    cutoff) pair.
    """
    params: list = [_iso_z(now - timedelta(hours=_past_hours()))]
    whens: list[str] = []
    for max_hours, _interval in CADENCE_MAIN_BANDS:
        if max_hours == -1:
            continue
        horizon = _iso_z(now + timedelta(hours=max_hours))
        cutoff = _iso_z(now - timedelta(seconds=allowed_age_seconds(max_hours)))
        whens.append("WHEN commence_time <= ? THEN ?")
        params.extend([horizon, cutoff])
    # Catch-all band (beyond the last horizon).
    catch_all = _iso_z(
        now - timedelta(seconds=allowed_age_seconds(float("inf")))
    )
    params.append(catch_all)
    case = "CASE " + " ".join(whens) + " ELSE ? END"
    return f" AND commence_time >= ? AND fetched_at >= {case}", params


# ─────────────────────────── row mapping ─────────────────────────────

_BASE_SELECT = (
    "SELECT sport_key, event_id, commence_time, home_team, away_team, "
    "bookmaker_key, market_key, outcome_name, outcome_description, "
    "outcome_point, price_american, fetched_at FROM latest_odds WHERE 1"
)


@functools.lru_cache(maxsize=131072)
def _encode_outcome_name_cached(
    market_key: str, name: str, description: str | None, sport_key: str,
) -> str:
    """Memoized `normalize._encode_outcome_name`.

    Pure function of its arguments (the player-alias tables it consults
    are static), and the same (market, player) pair recurs once per book
    — ~30 times over on a busy prop market. Dominated the per-row cost of
    a full betting-db scan before caching.
    """
    return _encode_outcome_name(market_key, name, description, sport_key)


def _mapped_rows_uncached(sport_key: str | None = None) -> list[dict]:
    """betting-db `latest_odds` -> `odds_snapshot`-shaped rows.

    `sport_key` is betting-site's APP sport ("mlb"), matching the native
    `all_current(sport_key=...)` parameter — not betting-db's column of
    the same name.
    """
    now = datetime.now(timezone.utc)
    fresh_sql, fresh_params = _freshness_sql(now)
    sport_sql, sport_params = _sport_filter_sql(sport_key)
    q = _BASE_SELECT + fresh_sql + sport_sql

    conn = _connect()
    try:
        raw = conn.execute(q, [*fresh_params, *sport_params]).fetchall()
    finally:
        conn.close()

    # Keyed by odds_snapshot's PK so post-fold collisions resolve
    # last-write-wins, exactly as OddsCache.upsert's ON CONFLICT does.
    out: dict[tuple, dict] = {}
    dropped_teamless = 0
    for r in raw:
        book = r["bookmaker_key"]
        if book in _EXCLUDE_BOOKMAKERS:
            continue
        odds_api_sport = r["sport_key"]
        app_sport = app_sport_for(odds_api_sport)
        if app_sport is None:
            continue
        # odds_snapshot declares home_team / away_team NOT NULL and every
        # consumer dereferences them unguarded; betting-db allows NULL
        # (an odds row that arrived before its event was discovered).
        if r["home_team"] is None or r["away_team"] is None:
            dropped_teamless += 1
            continue
        market_key = r["market_key"]
        point = r["outcome_point"]
        point = 0.0 if point is None else float(point)
        name = _encode_outcome_name_cached(
            market_key, r["outcome_name"], r["outcome_description"],
            app_sport,
        )
        row = {
            "event_id": r["event_id"],
            "sport_key": app_sport,
            # normalize_odds_response only sets league_key/title for soccer.
            "league_key": odds_api_sport if app_sport == "soccer" else None,
            # betting-db does not persist the Odds API's sport_title.
            "league_title": None,
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "commence_time": _norm_ts(r["commence_time"]),
            "bookmaker_key": book,
            "market_key": market_key,
            "outcome_name": name,
            # h2h's point is meaningless — the native all_current()
            # reverses the 0.0 sentinel to None. Done here rather than by
            # mutating rows afterwards, because the memo below hands the
            # SAME dicts to every caller.
            "outcome_point": None if market_key == "h2h" else point,
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

    if dropped_teamless:
        logger.warning(
            "betting-db: dropped %d row(s) with NULL home/away team "
            "(odds_snapshot requires both)", dropped_teamless,
        )
    return list(out.values())


@functools.lru_cache(maxsize=16)
def _mapped_rows_memo(sport_key: str | None, bucket: int) -> list[dict]:
    return _mapped_rows_uncached(sport_key)


def _mapped_rows(sport_key: str | None = None) -> list[dict]:
    """Short-TTL memoized `_mapped_rows_uncached`.

    Time-bucketed so all callers inside one MEMO_TTL_SECONDS window share
    one scan. The returned list and its dicts are shared — treat as
    read-only (nothing downstream mutates cache rows; `rows_to_games`
    only reads).
    """
    return _mapped_rows_memo(sport_key, int(time.time() // MEMO_TTL_SECONDS))


def _reset_memo_for_tests() -> None:
    """Clear the TTL memo. Tests only — they swap BETTING_DB_PATH between
    cases faster than the bucket rolls over."""
    _mapped_rows_memo.cache_clear()


def _direct_book_rows(cache, sport_key: str | None = None) -> list[dict]:
    """Native-cache rows for books betting-db does not poll.

    Queries `odds_snapshot` directly rather than filtering
    `_all_current_native`'s output: the direct books are ~2.5k of the
    cache's ~100k rows, and materializing every row into a dict just to
    throw 97% away cost more than the betting-db scan itself.

    Deliberately NOT `cache.all_current` — that dispatches straight back
    here in this mode.
    """
    books = sorted(DIRECT_BOOK_KEYS)
    q = (
        "SELECT * FROM odds_snapshot WHERE bookmaker_key IN "
        f"({','.join('?' for _ in books)})"
    )
    args: list = list(books)
    if sport_key:
        q += " AND sport_key = ?"
        args.append(sport_key)
    with cache._conn() as c:
        rows = []
        for r in c.execute(q, args):
            d = dict(r)
            # Same h2h reverse-sentinel `_all_current_native` applies.
            if d.get("market_key") == "h2h":
                d["outcome_point"] = None
            rows.append(d)
        return rows


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
    # Direct-book rows WIN on a PK collision. betting-db carries the Odds
    # API's own `polymarket` quotes, which in native mode land in the very
    # same `odds_snapshot` PK slot as the direct WS feed's rows — so
    # emitting both here would double-count a book that the native path
    # only ever shows once. The direct row is the one to keep: it's
    # fresher and it's the only one carrying `max_stake_dollars` /
    # `wager_type`.
    #
    # Only betting-db rows FROM a direct book can collide (bookmaker_key
    # is part of the PK), and those are a rounding error of the scan — so
    # the frozenset test short-circuits ~99% of rows before any tuple gets
    # built. Re-keying the whole scan into a dict instead cost ~1.7s on
    # the live DB, which the memo could not amortize because it happened
    # per call rather than per scan.
    direct = _direct_book_rows(cache, sport_key)
    direct_pks = {_pk(r) for r in direct}
    rows = [
        r for r in _mapped_rows(sport_key)
        if r["bookmaker_key"] not in DIRECT_BOOK_KEYS
        or _pk(r) not in direct_pks
    ]
    rows.extend(direct)
    return rows


def event_sport_key(cache, event_id: str) -> str | None:
    """Drop-in for `OddsCache.event_sport_key`.

    SPEND PATH: `fetcher.refresh_event` bills a per-event Odds API
    request for any event_id this resolves, and returns "unknown_event"
    without spending when it gets None. The same freshness + commence
    filters as `all_current` are applied so an event betting-db still
    archives, but this repo would have purged, resolves to None — a dead
    event must never become a paid refresh.
    """
    now = datetime.now(timezone.utc)
    fresh_sql, fresh_params = _freshness_sql(now)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT sport_key FROM latest_odds WHERE event_id = ?"
            + fresh_sql + " LIMIT 1",
            [event_id, *fresh_params],
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        mapped = app_sport_for(row["sport_key"])
        if mapped is not None:
            return mapped
    # Direct-book events (coral33/kalshi/polymarket-only) never reach
    # betting-db; fall back to the native cache for them. That fallback is
    # itself purge-bounded, since the native cache is actively pruned.
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
    """Drop-in for `OddsCache.distinct_events`.

    SPEND PATH: `fetcher._run_per_event` fires one billed per-event Odds
    API request per row returned here. The rows come from `_mapped_rows`,
    which is freshness- and commence-window-filtered, so a stale archived
    event cannot enter the worklist.
    """
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
