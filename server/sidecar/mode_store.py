"""Three-state mode gate for the auto-bet sidecar.

Mirrors server/odds/cache_mode.py — own JSON file, own lock, default to
the safest value (off) on missing file. The user must explicitly POST to
flip to dry-run or live; the system never auto-flips.

  off      → no new placements (user-triggered or delta-tick).
             In-flight BackgroundTasks finish; no successors run.
  dry-run  → placements halt before the actual insertWagerParlay call;
             delta tick still runs and fires dry-run placements
             through the same path.
  live     → real placements via insertWagerParlay."""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Literal


class SidecarMode(str, Enum):
    OFF = "off"
    DRY_RUN = "dry-run"
    LIVE = "live"


SidecarModeLiteral = Literal["off", "dry-run", "live"]


class SidecarModeStore:
    def __init__(self, config_path: Path):
        self.path = config_path
        self._lock = Lock()

    def get(self) -> SidecarMode:
        try:
            with open(self.path) as f:
                data = json.load(f)
            return SidecarMode(data["mode"])
        except (FileNotFoundError, KeyError, ValueError):
            return SidecarMode.OFF

    def set(self, mode: SidecarMode | SidecarModeLiteral) -> None:
        if isinstance(mode, str):
            mode = SidecarMode(mode)  # raises ValueError on bogus input
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"mode": mode.value}))
            tmp.replace(self.path)
