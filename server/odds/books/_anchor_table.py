"""Per-sport candidate game-start anchors for date-only matching (M3).

When a venue ticker / slug carries only a date (no HHMM), we try
matching against multiple US-Eastern start-time anchors before
falling back to the wider noon-ET single-anchor window.

Each entry is a list of (hour, minute) tuples in US/Eastern.
"""
from __future__ import annotations


_DEFAULT_ANCHORS_ET: list[tuple[int, int]] = [
    (12, 0),   # noon — day games
    (19, 0),   # primetime
    (22, 0),   # late West Coast
]


# Per-sport overrides; absent sports use DEFAULT.
_ANCHORS_BY_SPORT_ET: dict[str, list[tuple[int, int]]] = {
    # NBA / NHL / WNBA are mostly evening + late.
    "nba":  [(19, 0), (22, 0)],
    "nhl":  [(19, 0), (22, 0)],
    "wnba": [(19, 0), (21, 0)],
}


# Tight window per anchor, in minutes.
TIGHT_WINDOW_MIN = 180


def anchors_for_sport(sport_key: str) -> list[tuple[int, int]]:
    """Return the candidate (hour, minute) ET anchors for this sport."""
    return _ANCHORS_BY_SPORT_ET.get(sport_key, _DEFAULT_ANCHORS_ET)
