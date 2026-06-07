"""Per-day cache for completed ensemble simulation results.

Each ensemble call costs ~$0.20-0.30 in OpenRouter spend (Phase 1 + 2 +
challenger). When ``main.py daily`` is run multiple times in a single day —
which is normal as new odds come in or the user re-checks the slate — the
same matches were being re-simmed end-to-end every run. Across 3 runs of a
15-match slate that's ~$10-15 of duplicate spend.

This module caches the ensemble's prediction dict per ``(date, match_key)``.
``_simulate_one_match`` checks the cache before calling ``run_mirofish``;
on hit, the cached prediction dict is reused for edge analysis. Edge
detection runs against the LIVE odds every time, so if odds moved the bet
side / size still updates — only the (expensive) ensemble probability
estimates are cached.

Cache layout: ``data/sim_cache/<YYYY-MM-DD>.json`` is a flat dict
``{match_key: prediction_dict}``. Per-date files keep the cache from
growing unbounded and make it trivial to wipe a single day's results
(``rm data/sim_cache/2026-04-24.json`` forces re-sim of that day).
"""
import json
import logging
import os
import threading
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger("mirofish.sim_cache")

CACHE_DIR = os.path.join(DATA_DIR, "sim_cache")

# CSV-style guard: multiple match threads may finish simultaneously and race
# the read-modify-write on the per-day cache file.
_cache_lock = threading.Lock()


def _cache_path(game_date: str) -> str:
    return os.path.join(CACHE_DIR, f"{game_date}.json")


def get_cached_sim(game_date: str, match_key: str) -> Optional[dict]:
    """Return the cached ensemble prediction dict for this match, or None.

    A return of None means ``run_mirofish`` should be invoked for this match.
    """
    path = _cache_path(game_date)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
        return cache.get(match_key)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("sim cache read failed for %s/%s: %s", game_date, match_key, e)
        return None


def save_cached_sim(game_date: str, match_key: str, result: dict) -> None:
    """Persist a successful ensemble result to the per-day cache."""
    if not result or not isinstance(result, dict):
        return
    path = _cache_path(game_date)
    with _cache_lock:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache: dict = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    cache = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                cache = {}
        cache[match_key] = result
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2, default=str)
        except OSError as e:
            logger.error("sim cache write failed for %s/%s: %s", game_date, match_key, e)


def clear_cache(game_date: Optional[str] = None) -> int:
    """Remove cached sims. Returns number of files deleted.

    If ``game_date`` is None, removes all dates; otherwise just that day.
    Use to force-resim when ensemble logic or briefing format changes.
    """
    if not os.path.exists(CACHE_DIR):
        return 0
    if game_date:
        path = _cache_path(game_date)
        if os.path.exists(path):
            os.remove(path)
            return 1
        return 0
    count = 0
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".json"):
            os.remove(os.path.join(CACHE_DIR, fname))
            count += 1
    return count
