"""Per-day JSON cache of screening + full-ensemble LLM results.

Keyed by (game_pk, starters_hash). A cache hit lets us skip re-running the
ensemble (and its screening) for a game whose starters (9 batters + SP, both
sides) have not changed. Fresh odds are still applied at edge-check time, so
edge/Kelly updates on every pipeline run even when the probability is cached.
"""
import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal

from config import DATA_DIR

logger = logging.getLogger("mirofish.cache")

CACHE_DIR = os.path.join(DATA_DIR, "ensemble_cache")
_file_lock = threading.Lock()

EntryKind = Literal["screening", "ensemble"]


def _cache_path(game_date: str) -> str:
    return os.path.join(CACHE_DIR, f"{game_date}.json")


def _load_day(game_date: str) -> dict:
    path = _cache_path(game_date)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Cache file %s unreadable (%s) — treating as empty", path, e)
        return {}


def _save_day(game_date: str, data: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(game_date)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def compute_starters_hash(lineup_data: dict) -> str:
    """Hash of the 9 starting batters + SP on each side (order-independent).

    Returns a short hex digest. Returns "" if lineup_data is missing the
    required fields — callers should treat this as "cannot cache".
    """
    if not lineup_data:
        return ""

    home = lineup_data.get("home") or []
    away = lineup_data.get("away") or []
    home_sp = lineup_data.get("home_pitcher")
    away_sp = lineup_data.get("away_pitcher")

    if not home or not away or home_sp is None or away_sp is None:
        return ""

    key = {
        "home_batters": sorted(int(p) for p in home[:9]),
        "away_batters": sorted(int(p) for p in away[:9]),
        "home_sp": int(home_sp),
        "away_sp": int(away_sp),
    }
    raw = json.dumps(key, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _entry_key(game_pk: int, starters_hash: str) -> str:
    return f"{game_pk}:{starters_hash}"


def get_cache_entry(game_pk: int, starters_hash: str, game_date: str) -> dict | None:
    """Return the cached entry for (game_pk, starters_hash) on game_date, or None."""
    if not starters_hash or game_pk is None:
        return None
    with _file_lock:
        day = _load_day(game_date)
    return day.get(_entry_key(game_pk, starters_hash))


def set_cache_entry(
    game_pk: int,
    starters_hash: str,
    game_date: str,
    kind: EntryKind,
    payload: dict,
) -> None:
    """Write the `screening` or `ensemble` payload into the day's cache.

    Merges into any existing entry for the same (game_pk, starters_hash).
    """
    if not starters_hash or game_pk is None or payload is None:
        return
    if kind not in ("screening", "ensemble"):
        raise ValueError(f"kind must be 'screening' or 'ensemble', got {kind}")

    ek = _entry_key(game_pk, starters_hash)
    now = datetime.now(timezone.utc).isoformat()
    with _file_lock:
        day = _load_day(game_date)
        entry = day.get(ek, {
            "starters_hash": starters_hash,
            "game_pk": game_pk,
        })
        entry[kind] = payload
        entry["cached_at"] = now
        day[ek] = entry
        _save_day(game_date, day)
    logger.debug("Cache write: %s on %s kind=%s", ek, game_date, kind)


def rotate_old_cache(keep_days: int = 30) -> int:
    """Delete cache files older than `keep_days`. Returns deletion count."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=keep_days)
    deleted = 0
    for name in os.listdir(CACHE_DIR):
        if not name.endswith(".json"):
            continue
        stem = name[:-5]
        try:
            file_date = datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                os.remove(os.path.join(CACHE_DIR, name))
                deleted += 1
            except OSError as e:
                logger.warning("Could not delete stale cache %s: %s", name, e)
    if deleted:
        logger.info("Rotated %d cache files older than %d days", deleted, keep_days)
    return deleted
