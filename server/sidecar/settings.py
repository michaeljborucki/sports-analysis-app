"""Typed accessors over user_settings.json for sidecar-routine settings.

The mode toggle (live vs dry-run) lives in its own sidecar_mode.json file
(see mode_store.py). Bankroll and default Kelly are routine values that ride
on the existing user-settings store as opaque extra keys — the existing
UserSettings dataclass ignores unknown fields, so we read them directly via
json.load without depending on its strict schema."""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from server.user_settings import SETTINGS_PATH as _DEFAULT_SETTINGS_PATH


class KellyFraction(str, Enum):
    FULL = "full"
    HALF = "half"
    QUARTER = "quarter"


_FRACTION_VALUES = {f.value for f in KellyFraction}


def _settings_path() -> Path:
    """Indirection seam so tests can patch this without touching the store."""
    return _DEFAULT_SETTINGS_PATH


def _load_raw() -> dict:
    try:
        return json.loads(_settings_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_bankroll() -> int:
    """Static bankroll used by the splitter. Default $10,000."""
    raw = _load_raw()
    val = raw.get("sidecar_bankroll", 10000)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 10000


def get_default_kelly() -> KellyFraction:
    """Default Kelly fraction shown in the confirm modal. Default half."""
    raw = _load_raw()
    val = raw.get("sidecar_default_kelly", "half")
    if isinstance(val, str) and val in _FRACTION_VALUES:
        return KellyFraction(val)
    return KellyFraction.HALF


def kelly_to_pct(fraction: KellyFraction, full_kelly_pct: float) -> float:
    if fraction is KellyFraction.FULL:
        return full_kelly_pct
    if fraction is KellyFraction.HALF:
        return full_kelly_pct * 0.5
    return full_kelly_pct * 0.25
