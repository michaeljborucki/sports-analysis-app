"""User-controlled overrides — which sports and market keys are active.

Layers on top of markets.<sport>.toml (defaults). TOML says what the system
*can* fetch; user_settings.json says what the user *wants* fetched. The
fetcher respects both.

Stored at server/config/user_settings.json so it persists across restarts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock


logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).resolve().parent / "config" / "user_settings.json"


@dataclass
class UserSettings:
    # Sports the user has disabled. Empty set = everything enabled.
    disabled_sports: set[str] = field(default_factory=set)
    # Per-sport disabled market keys. Anything in this set is filtered out of
    # its tier's market list before fetcher scheduling.
    disabled_markets: dict[str, set[str]] = field(default_factory=dict)
    # Globally visible sportsbook keys for the UI. `None` means "frontend's
    # default set" (preserves backwards compatibility and lets a never-saved
    # install use the client's DEFAULT_VISIBLE_BOOKS). An empty list is a
    # legitimate user choice ("show nothing") and is distinct from None.
    visible_books: list[str] | None = None

    def is_sport_enabled(self, sport_key: str) -> bool:
        return sport_key not in self.disabled_sports

    def filter_markets(self, sport_key: str, markets: list[str]) -> list[str]:
        disabled = self.disabled_markets.get(sport_key, set())
        return [m for m in markets if m not in disabled]

    def to_dict(self) -> dict:
        out: dict = {
            "disabled_sports": sorted(self.disabled_sports),
            "disabled_markets": {
                sport: sorted(keys)
                for sport, keys in self.disabled_markets.items()
                if keys
            },
        }
        if self.visible_books is not None:
            out["visible_books"] = sorted(self.visible_books)
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "UserSettings":
        raw_books = raw.get("visible_books")
        visible = sorted(raw_books) if isinstance(raw_books, list) else None
        return cls(
            disabled_sports=set(raw.get("disabled_sports") or []),
            disabled_markets={
                sport: set(keys)
                for sport, keys in (raw.get("disabled_markets") or {}).items()
                if keys
            },
            visible_books=visible,
        )


class UserSettingsStore:
    """Loads, persists, and exposes the current UserSettings.

    Serializes writes so a POST can't race with the fetcher's read.
    """

    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self._lock = Lock()
        self._settings = self._load_from_disk()

    def _load_from_disk(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        try:
            return UserSettings.from_dict(json.loads(self.path.read_text()))
        except Exception:
            logger.exception("Failed to load %s; starting with empty settings", self.path)
            return UserSettings()

    def _snapshot_locked(self) -> UserSettings:
        """Deep copy of current settings. Caller must hold self._lock."""
        return UserSettings(
            disabled_sports=set(self._settings.disabled_sports),
            disabled_markets={
                k: set(v) for k, v in self._settings.disabled_markets.items()
            },
            visible_books=(
                list(self._settings.visible_books)
                if self._settings.visible_books is not None
                else None
            ),
        )

    def get(self) -> UserSettings:
        with self._lock:
            return self._snapshot_locked()

    def set(self, new: UserSettings) -> UserSettings:
        with self._lock:
            self._settings = new
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(new.to_dict(), indent=2))
            # Must not call self.get() here — threading.Lock is non-reentrant
            # and would deadlock. Snapshot under the already-held lock.
            return self._snapshot_locked()
