"""Patch notes fetcher with LLM-powered summarization."""
import json
import logging
import os
from datetime import datetime

import requests

from config import DATA_DIR

log = logging.getLogger(__name__)

PATCH_URLS = {
    "cs2": "https://blog.counter-strike.net/index.php/category/updates/",
    "lol": "https://www.leagueoflegends.com/en-us/news/tags/patch-notes/",
}

_patch_cache: dict = {}  # {game_key: {patch_version: data}}
PATCH_CACHE_FILE = os.path.join(DATA_DIR, "patch_cache.json")


def fetch_patch_context(game_key: str) -> dict:
    """Fetch current patch info and summarize key changes.

    Returns:
        dict with: patch_version, days_since_patch, key_changes, impact_rating, raw_url
    """
    # Check in-memory cache
    if game_key in _patch_cache:
        return _patch_cache[game_key]

    # Check disk cache
    disk_cache = _load_disk_cache()
    if game_key in disk_cache:
        cached = disk_cache[game_key]
        # Use cached if less than 24 hours old
        cached_time = cached.get("cached_at", "")
        if cached_time:
            try:
                age = (datetime.now() - datetime.fromisoformat(cached_time)).total_seconds()
                if age < 86400:
                    _patch_cache[game_key] = cached
                    return cached
            except ValueError:
                pass

    # Fetch fresh data
    url = PATCH_URLS.get(game_key, "")
    result = {
        "patch_version": "unknown",
        "days_since_patch": 0,
        "key_changes": [],
        "impact_rating": "unknown",
        "raw_url": url,
    }

    if not url:
        log.warning(f"[meta] No patch URL for {game_key}")
        return result

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "MiroFish/1.0"})
        resp.raise_for_status()
        # Basic extraction — in production, this would use LLM summarization
        result["patch_version"] = _extract_patch_version(resp.text, game_key)
        result["key_changes"] = _extract_changes(resp.text, game_key)
        result["impact_rating"] = "minor"
    except Exception as e:
        log.warning(f"[meta] Failed to fetch patch notes for {game_key}: {e}")

    result["cached_at"] = datetime.now().isoformat()
    _patch_cache[game_key] = result
    _save_disk_cache(game_key, result)
    return result


def _extract_patch_version(html: str, game_key: str) -> str:
    """Extract patch version from page content."""
    import re
    if game_key == "cs2":
        match = re.search(r"Release Notes for (\d+/\d+/\d+)", html)
        if match:
            return match.group(1)
    elif game_key == "lol":
        match = re.search(r"Patch (\d+\.\d+)", html)
        if match:
            return match.group(1)
    return "unknown"


def _extract_changes(html: str, game_key: str) -> list[str]:
    """Extract key balance changes. Stub — production uses LLM summarization."""
    return ["Patch notes fetched — LLM summarization pending"]


def _load_disk_cache() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(PATCH_CACHE_FILE):
        try:
            with open(PATCH_CACHE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_disk_cache(game_key: str, data: dict):
    cache = _load_disk_cache()
    cache[game_key] = data
    try:
        with open(PATCH_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except OSError as e:
        log.warning(f"[meta] Failed to save cache: {e}")
