"""Sync finished api-tennis matches into the local Sackmann-shaped archive.

Three public functions:
  - ``sync_matches_day(date, tour)`` — fetch finished fixtures, append as rows
  - ``sync_rankings(tour)`` — refresh the rankings CSV
  - ``_ensure_player(key, tour)`` — lazy player metadata lookup

Writes conform to Sackmann's 46-column CSV schema plus 12 additional
percentage columns (``w_1stSvPct``, ``w_1stWonPct``, etc.) for the stats
api-tennis exposes as percentages rather than raw counts. Existing
2020-2024 rows don't carry those columns; ``scrapers/players.py`` handles
both shapes transparently.

All writes are idempotent by ``(tourney_id, match_num)`` — safe to rerun.
"""
import csv
import logging
import os
import time
from datetime import date, datetime
from typing import Optional

import requests

from config import API_TENNIS_KEY, API_TENNIS_BASE, SACKMANN_LOCAL_DIR

logger = logging.getLogger("mirofish.scrapers.sackmann_sync")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Canonical Sackmann match column order (46 cols). Kept identical to historical
# files so readers treat old + new rows uniformly.
SACKMANN_MATCH_COLS = [
    "tourney_id", "tourney_name", "surface", "draw_size", "tourney_level",
    "tourney_date", "match_num",
    "winner_id", "winner_seed", "winner_entry", "winner_name", "winner_hand",
    "winner_ht", "winner_ioc", "winner_age",
    "loser_id", "loser_seed", "loser_entry", "loser_name", "loser_hand",
    "loser_ht", "loser_ioc", "loser_age",
    "score", "best_of", "round", "minutes",
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon",
    "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon",
    "l_SvGms", "l_bpSaved", "l_bpFaced",
    "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points",
]

# Extended percentage columns populated from api-tennis stats. These live
# alongside (not replacing) the raw-count columns so 2025+ rows carry both
# conventions when possible. Readers (players.py) prefer the pct columns
# for 2025+ rows and fall back to raw counts for 2020-2024 rows.
EXTENDED_PCT_COLS = [
    "w_1stSvPct", "w_1stWonPct", "w_2ndWonPct", "w_bpSavedPct",
    "w_retPtsWonPct", "w_bpConvPct",
    "l_1stSvPct", "l_1stWonPct", "l_2ndWonPct", "l_bpSavedPct",
    "l_retPtsWonPct", "l_bpConvPct",
]

ALL_COLS = SACKMANN_MATCH_COLS + EXTENDED_PCT_COLS


RANKING_COLS = ["ranking_date", "rank", "player", "points"]


PLAYER_COLS = [
    "player_id", "name_first", "name_last", "hand", "dob", "ioc", "height",
    "wikidata_id",
]


# ---------------------------------------------------------------------------
# api-tennis client helpers
# ---------------------------------------------------------------------------


def _api_call(method: str, params: dict = None, timeout: int = 30,
              max_retries: int = 3) -> dict:
    """Thin wrapper with exponential backoff on 429s and transient errors."""
    call_params = {"method": method, "APIkey": API_TENNIS_KEY, **(params or {})}
    delay = 5
    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(API_TENNIS_BASE, params=call_params, timeout=timeout)
            if resp.status_code == 429:
                logger.warning("api-tennis rate-limited (%s), sleeping %ds", method, delay)
                time.sleep(delay)
                delay *= 3
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 3
    logger.error("api-tennis %s failed after %d retries: %s", method, max_retries, last_err)
    return {}


# ---------------------------------------------------------------------------
# Statistics aggregation
# ---------------------------------------------------------------------------

def _parse_pct(val) -> Optional[float]:
    """Parse '51%' → 0.51, '51' → 51, empty → None."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        num = float(s)
    except ValueError:
        return None
    # Heuristic: if it came with a %, it's 0-100; otherwise assume raw count.
    # Percentages normalized to 0.0-1.0 range.
    return num / 100.0 if num > 1.0 else num


def _aggregate_statistics(stats: list[dict]) -> dict:
    """Collapse api-tennis per-match + per-set stats into one row per player.

    api-tennis returns each stat multiple times: the FIRST entry is the
    match total, followed by per-set values.

    Verified 2026-04-22 against three ATP matches — for every stat checked
    (Aces, 1st serve %), sum-of-set-values equals the first entry. So we
    take the FIRST occurrence of each ``(player_key, stat_type, stat_name)``
    as the match-final value.

    Returns ``{player_key: {stat_name_slug: value}}``.
    """
    first_seen: dict[tuple, dict] = {}
    for s in stats or []:
        key = (s.get("player_key"), s.get("stat_type", ""), s.get("stat_name", ""))
        if key not in first_seen:
            first_seen[key] = s

    by_player: dict = {}
    for (pk, stype, sname), entry in first_seen.items():
        bucket = by_player.setdefault(pk, {})
        bucket[f"{stype}:{sname}"] = entry.get("stat_value")
    return by_player


def _extract_player_stats(player_stats: dict) -> dict:
    """Map aggregated stats to Sackmann-column values.

    Input: ``{"Service:Aces": "3", "Service:1st serve percentage": "56%", ...}``
    Output: dict of ``{"ace": 3, "df": 0, "1stSvPct": 0.56, ...}`` (no w_/l_ prefix).
    """
    def _cnt(key):
        val = player_stats.get(key, "")
        if val is None or val == "":
            return ""
        try:
            return int(float(str(val).rstrip("%")))
        except ValueError:
            return ""

    def _pct(key):
        p = _parse_pct(player_stats.get(key))
        return round(p, 4) if p is not None else ""

    return {
        "ace": _cnt("Service:Aces"),
        "df": _cnt("Service:Double Faults"),
        "1stSvPct": _pct("Service:1st serve percentage"),
        "1stWonPct": _pct("Service:1st serve points won"),
        "2ndWonPct": _pct("Service:2nd serve points won"),
        "bpSavedPct": _pct("Service:Break Points Saved"),
        "retPtsWonPct": _pct("Points:Return Points Won"),
        "bpConvPct": _pct("Return:Break Points Converted"),
    }


# ---------------------------------------------------------------------------
# Fixture → Sackmann row
# ---------------------------------------------------------------------------


def _parse_event_date(s: str) -> str:
    """api-tennis 'YYYY-MM-DD' → Sackmann 'YYYYMMDD'."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y%m%d")
    except (ValueError, TypeError):
        return ""


def _infer_tourney_level(event_type_type: str, tournament_name: str) -> str:
    """Sackmann tourney level single-letter codes.

    G = Grand Slam, M = Masters 1000, A = ATP 500/250, C = Challenger,
    S = ITF, F = Tour Finals. Best-effort mapping from api-tennis context.
    """
    name = (tournament_name or "").lower()
    if any(gs in name for gs in ("australian open", "roland garros", "french open",
                                  "wimbledon", "us open")):
        return "G"
    if "masters" in name or "atp 1000" in name:
        return "M"
    etype = (event_type_type or "").lower()
    if "challenger" in etype:
        return "C"
    if "itf" in etype:
        return "S"
    return "A"


def _build_match_row(fixture: dict, tour: str, player_cache: dict) -> Optional[dict]:
    """Convert a finished api-tennis fixture into a Sackmann-shaped dict.

    Returns None if the fixture is unusable (missing winner, no players, etc.).
    """
    winner_side = fixture.get("event_winner", "")
    if winner_side not in ("First Player", "Second Player"):
        return None
    first_key = fixture.get("first_player_key")
    second_key = fixture.get("second_player_key")
    first_name = fixture.get("event_first_player", "").strip()
    second_name = fixture.get("event_second_player", "").strip()
    if not first_name or not second_name:
        return None

    winner_first = winner_side == "First Player"
    winner_key = first_key if winner_first else second_key
    loser_key = second_key if winner_first else first_key
    abbrev_winner = first_name if winner_first else second_name
    abbrev_loser = second_name if winner_first else first_name

    # Lookup (or lazily fetch) player metadata — we need this BEFORE writing
    # the row so winner_name / loser_name use full names consistent with the
    # historical Sackmann 2020-2024 data ("Carlos Alcaraz", not "C. Alcaraz").
    # If the lookup fails, fall back to the api-tennis abbreviated name —
    # Elo for that row will be isolated, but the row is still valid.
    w_meta = _ensure_player(winner_key, tour, player_cache) if winner_key else {}
    l_meta = _ensure_player(loser_key, tour, player_cache) if loser_key else {}
    winner_name = _full_name(w_meta, abbrev_winner)
    loser_name = _full_name(l_meta, abbrev_loser)

    # Statistics
    agg = _aggregate_statistics(fixture.get("statistics", []))
    w_stats = _extract_player_stats(agg.get(winner_key, {})) if winner_key in agg else {}
    l_stats = _extract_player_stats(agg.get(loser_key, {})) if loser_key in agg else {}

    # Score from the per-set scores array
    score = _build_score_string(fixture.get("scores", []), winner_first)

    row = {c: "" for c in ALL_COLS}
    row["tourney_id"] = fixture.get("tournament_key", "")
    row["tourney_name"] = fixture.get("tournament_name", "")
    row["surface"] = fixture.get("tournament_surface", "")  # may be blank; populated later if available
    row["tourney_level"] = _infer_tourney_level(
        fixture.get("event_type_type", ""), fixture.get("tournament_name", ""),
    )
    row["tourney_date"] = _parse_event_date(fixture.get("event_date", ""))
    row["match_num"] = fixture.get("event_key", "")

    row["winner_id"] = winner_key or ""
    row["winner_name"] = winner_name
    row["winner_hand"] = w_meta.get("hand", "")
    row["winner_ht"] = w_meta.get("height", "")
    row["winner_ioc"] = w_meta.get("ioc", "")
    row["winner_age"] = _age_at(w_meta.get("dob", ""), row["tourney_date"])

    row["loser_id"] = loser_key or ""
    row["loser_name"] = loser_name
    row["loser_hand"] = l_meta.get("hand", "")
    row["loser_ht"] = l_meta.get("height", "")
    row["loser_ioc"] = l_meta.get("ioc", "")
    row["loser_age"] = _age_at(l_meta.get("dob", ""), row["tourney_date"])

    row["score"] = score
    row["best_of"] = _infer_best_of(fixture.get("scores", []))
    row["round"] = fixture.get("tournament_round", "")

    # Raw counts (where api-tennis provides them)
    for k, val in w_stats.items():
        col = f"w_{k}"
        if col in row:
            row[col] = val
    for k, val in l_stats.items():
        col = f"l_{k}"
        if col in row:
            row[col] = val

    return row


def _build_score_string(scores: list[dict], winner_first: bool) -> str:
    """Reconstruct Sackmann-style score from per-set scores.

    Sackmann convention: winner's games first, loser's second.
    api-tennis gives us ``score_first`` (player 1) and ``score_second`` (player 2).
    """
    parts = []
    for s in scores or []:
        first = str(s.get("score_first", "")).strip()
        second = str(s.get("score_second", "")).strip()
        if not first or not second:
            continue
        w, l = (first, second) if winner_first else (second, first)
        parts.append(f"{w}-{l}")
    return " ".join(parts)


def _infer_best_of(scores: list[dict]) -> int:
    """≥3 sets on the scoreline → best of 5, else best of 3."""
    return 5 if len(scores or []) >= 3 else 3


def _age_at(dob: str, tourney_date: str) -> str:
    """Compute age at tournament date from YYYYMMDD strings."""
    if not dob or len(str(dob)) < 8 or not tourney_date or len(tourney_date) < 8:
        return ""
    try:
        born = datetime.strptime(str(dob)[:8], "%Y%m%d")
        when = datetime.strptime(tourney_date[:8], "%Y%m%d")
        years = when.year - born.year - ((when.month, when.day) < (born.month, born.day))
        return str(years)
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Player cache
# ---------------------------------------------------------------------------


def _players_csv_path(tour: str) -> str:
    prefix = "atp" if tour == "atp" else "wta"
    return os.path.join(SACKMANN_LOCAL_DIR, tour, f"{prefix}_players.csv")


def _load_players(tour: str) -> dict[int, dict]:
    """Load players CSV into a dict keyed by player_id (int)."""
    path = _players_csv_path(tour)
    if not os.path.exists(path):
        return {}
    players: dict[int, dict] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = row.get("player_id", "").strip()
            if pid:
                try:
                    players[int(pid)] = row
                except ValueError:
                    continue
    return players


def _append_player(tour: str, row: dict) -> None:
    path = _players_csv_path(tour)
    exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAYER_COLS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerow(row)


def _ensure_player(player_key, tour: str, cache: dict) -> dict:
    """Return player metadata, fetching + appending lazily if unknown.

    Cache is populated on first call; subsequent calls within the same
    pipeline run hit memory only.
    """
    if "_loaded" not in cache:
        cache.update(_load_players(tour))
        cache["_loaded"] = True
    try:
        pk_int = int(player_key)
    except (TypeError, ValueError):
        return {}
    if pk_int in cache:
        return cache[pk_int]

    # Lazy api-tennis lookup
    data = _api_call("get_players", {"player_key": pk_int})
    results = data.get("result", []) if isinstance(data, dict) else []
    if not results:
        return {}
    raw = results[0]
    # Prefer ``player_full_name`` ("Tamara Korpatsch") over ``player_name`` ("T. Korpatsch")
    # so Sackmann-schema winner_name/loser_name columns use the same full-name format
    # as the historical 2020-2024 data — essential for Elo + H2H to merge across eras.
    full = (raw.get("player_full_name") or raw.get("player_name") or "").strip()
    first, last = _split_name(full)
    row = {
        "player_id": pk_int,
        "name_first": first,
        "name_last": last,
        "hand": raw.get("player_hand", ""),
        "dob": _parse_dob(raw.get("player_bday", "")),
        "ioc": raw.get("player_country", "")[:3].upper() if raw.get("player_country") else "",
        "height": "",
        "wikidata_id": "",
    }
    cache[pk_int] = row
    _append_player(tour, row)
    return row


def _full_name(meta: dict, fallback: str) -> str:
    """Reconstruct 'First Last' from player metadata.

    Used in match-row construction so ``winner_name`` / ``loser_name`` match
    Sackmann's historical full-name format. Falls back to the api-tennis
    abbreviated name (e.g. ``"A. Zverev"``) if metadata is empty — that
    match will stand alone in the Elo graph but the row is still valid.
    """
    first = (meta.get("name_first") or "").strip()
    last = (meta.get("name_last") or "").strip()
    full = f"{first} {last}".strip()
    return full if full else fallback


def _split_name(full: str) -> tuple[str, str]:
    """'Alcaraz, Carlos' → ('Carlos', 'Alcaraz'); 'Carlos Alcaraz' → ('Carlos', 'Alcaraz')."""
    if not full:
        return "", ""
    if "," in full:
        last, _, first = full.partition(",")
        return first.strip(), last.strip()
    parts = full.split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return full, ""


def _parse_dob(s: str) -> str:
    """Various api-tennis date formats → Sackmann YYYYMMDD."""
    if not s:
        return ""
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return ""


# ---------------------------------------------------------------------------
# Public: sync_matches_day
# ---------------------------------------------------------------------------


def _matches_csv_path(tour: str, year: int) -> str:
    prefix = "atp" if tour == "atp" else "wta"
    return os.path.join(SACKMANN_LOCAL_DIR, tour, f"{prefix}_matches_{year}.csv")


def _load_dedup_keys(tour: str, year: int) -> set[tuple]:
    """Set of existing (tourney_id, match_num) keys for the given year's CSV."""
    path = _matches_csv_path(tour, year)
    if not os.path.exists(path):
        return set()
    keys: set[tuple] = set()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            keys.add((str(row.get("tourney_id", "")), str(row.get("match_num", ""))))
    return keys


def _append_match_rows(tour: str, year: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    path = _matches_csv_path(tour, year)
    exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        # Use ALL_COLS for new files; existing files may have only SACKMANN_MATCH_COLS
        # but DictWriter with extrasaction='ignore' + restval='' handles either shape.
        fieldnames = ALL_COLS if not exists else _read_header(path) or ALL_COLS
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for row in rows:
            w.writerow(row)
    return len(rows)


def _read_header(path: str) -> list[str] | None:
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f)
            return next(reader, None)
    except Exception:
        return None


def _tour_event_prefix(tour: str) -> str:
    """Match the api-tennis event_type_type field for singles filtering."""
    return "Atp" if tour == "atp" else "Wta"


def sync_matches_day(game_date: str, tour: str) -> int:
    """Fetch finished matches for one date, append to the local archive.

    Idempotent — existing ``(tourney_id, match_num)`` keys are skipped.
    Returns count of NEW rows written.
    """
    data = _api_call("get_fixtures", {
        "date_start": game_date,
        "date_stop": game_date,
    })
    fixtures = data.get("result", []) if isinstance(data, dict) else []

    tour_prefix = _tour_event_prefix(tour)
    finished = [
        f for f in fixtures
        if f.get("event_status") == "Finished"
        and str(f.get("event_type_type", "")).startswith(tour_prefix)
        and "Doubles" not in str(f.get("event_type_type", ""))
    ]
    if not finished:
        logger.info("sync_matches_day %s %s: no finished singles matches", game_date, tour.upper())
        return 0

    # Group by year for dedup + append
    by_year: dict[int, list[dict]] = {}
    player_cache: dict = {}

    for fx in finished:
        row = _build_match_row(fx, tour, player_cache)
        if not row or not row.get("tourney_date"):
            continue
        try:
            year = int(row["tourney_date"][:4])
        except (ValueError, KeyError):
            continue
        by_year.setdefault(year, []).append(row)

    total_new = 0
    for year, rows in by_year.items():
        existing = _load_dedup_keys(tour, year)
        new_rows = [
            r for r in rows
            if (str(r.get("tourney_id", "")), str(r.get("match_num", ""))) not in existing
        ]
        written = _append_match_rows(tour, year, new_rows)
        total_new += written

    logger.info(
        "sync_matches_day %s %s: %d fixtures, %d new rows appended",
        game_date, tour.upper(), len(finished), total_new,
    )
    return total_new


# ---------------------------------------------------------------------------
# Public: sync_rankings
# ---------------------------------------------------------------------------


def _rankings_csv_path(tour: str) -> str:
    prefix = "atp" if tour == "atp" else "wta"
    return os.path.join(SACKMANN_LOCAL_DIR, tour, f"{prefix}_rankings_current.csv")


def sync_rankings(tour: str) -> int:
    """Overwrite the rankings CSV with today's standings.

    Returns count of rows written (excluding header).
    """
    event_type = "ATP" if tour == "atp" else "WTA"
    data = _api_call("get_standings", {"event_type": event_type})
    results = data.get("result", []) if isinstance(data, dict) else []
    if not results:
        logger.warning("sync_rankings %s: no standings returned", event_type)
        return 0

    today = date.today().strftime("%Y%m%d")
    rows = []
    for r in results:
        pid = r.get("player_key", "")
        rank = r.get("place", "")
        points = r.get("points", "")
        if not pid:
            continue
        rows.append({
            "ranking_date": today,
            "rank": rank,
            "player": pid,
            "points": points,
        })

    path = _rankings_csv_path(tour)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RANKING_COLS)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    logger.info("sync_rankings %s: wrote %d rows to %s", event_type, len(rows), path)
    return len(rows)
