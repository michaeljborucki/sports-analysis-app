"""
Cache-mode state machine — three modes govern where odds data comes from and
whether fetchers are allowed to write:

  live      → cache.db         + Odds API fetcher on  + Coral33 fetcher on
  latest    → cache.db         + all fetchers off     (read-only last pull)
  snapshot  → cache.snapshot.db + all fetchers off    (frozen reference set)

The mode is persisted to disk (cache_mode.json) so it survives restarts. The
lifespan hook in main.py reads the persisted mode and applies fetcher state +
cache path at startup, then subsequent mode changes hit the POST endpoint.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Literal


class CacheMode(str, Enum):
    LIVE = "live"
    LATEST = "latest"
    SNAPSHOT = "snapshot"


ModeLiteral = Literal["live", "latest", "snapshot"]


class CacheModeStore:
    """Tiny JSON-backed persistence for the current mode."""

    def __init__(self, config_path: Path):
        self.path = config_path
        self._lock = Lock()

    def get(self) -> CacheMode:
        try:
            with open(self.path) as f:
                raw = json.load(f).get("mode")
            return CacheMode(raw) if raw in {m.value for m in CacheMode} else CacheMode.LATEST
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return CacheMode.LATEST

    def set(self, mode: CacheMode) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump({"mode": mode.value}, f)
            tmp.replace(self.path)
