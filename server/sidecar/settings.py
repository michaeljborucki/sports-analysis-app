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


def kelly_to_fraction(
    fraction: KellyFraction, full_kelly_pct: float
) -> float:
    """Convert the EV scanner's `kelly_full_pct` (a percentage value
    like 4.6 meaning 4.6%) into a **decimal fraction of bankroll** the
    caller can multiply against the bankroll dollar amount.

    Examples:
      kelly_full_pct=4.6, fraction=HALF  → 0.023 (= 2.3% of bankroll)
      kelly_full_pct=4.6, fraction=QUARTER → 0.0115 (= 1.15%)

    The /100 conversion is critical: kelly_full_pct comes off the
    EVOpportunity response in percentage form (the same /api/ev field
    the UI renders as "X.YZ%"), so dollar math needs the divisor or you
    end up 100× over-bet.
    """
    multiplier = {
        KellyFraction.FULL: 1.0,
        KellyFraction.HALF: 0.5,
        KellyFraction.QUARTER: 0.25,
    }[fraction]
    return (full_kelly_pct / 100.0) * multiplier


# Backwards-compat alias for existing call sites. New code should use
# kelly_to_fraction for clarity — the old name is misleading because the
# return value is a fraction, not a percentage.
kelly_to_pct = kelly_to_fraction


STAKE_INCREMENT = 5   # All sidecar stakes are rounded to the nearest $5.


def round_stake_to_5(dollars: float) -> int:
    """Round a dollar amount to the nearest $5.

    Used at the boundary between "Kelly says X" and "splitter targets X"
    so every individual parlay the orchestrator places lands on a clean
    $5 multiple. The splitter's peel-back math preserves this — given a
    $5-multiple target, every resulting assignment is also a $5 multiple
    (verified by inspection: caps $100/$150 are $5-multiples, FLOOR $30
    is a $5-multiple, peel-back deficit $30 - residual_in_5s is a
    $5-multiple)."""
    return int(round(dollars / STAKE_INCREMENT) * STAKE_INCREMENT)


def compute_kelly_target(
    fraction: KellyFraction,
    full_kelly_pct: float,
    bankroll: int,
) -> int:
    """Combined helper: Kelly fraction × bankroll, rounded to $5.

    The canonical place to compute the splitter target from settings.
    Both the orchestrator (user-triggered placements) and the delta-tick
    (autonomous re-fires) go through this so behavior is consistent."""
    fraction_of_bankroll = kelly_to_fraction(fraction, full_kelly_pct)
    return round_stake_to_5(fraction_of_bankroll * bankroll)
