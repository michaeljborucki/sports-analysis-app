"""Canonicalize spread-market outcome orientation (M4).

Some books emit `(outcome_name="Boston Celtics", outcome_point=-2.5)`;
others emit `(outcome_name="Miami Heat", outcome_point=+2.5)` for the
same line. Both describe the same bet, but they hash to distinct cache
keys and the resulting duplicate rows confuse flat-outcome queries.

Canonical form: favored team (negative point). This module is venue-
agnostic — the sportsbook normalizer, Kalshi normalizer, and
Polymarket normalizer all apply it at ingest time.

The pickem case (point = 0) has no orientation; pass through.
Out-of-roster outcome names (typos, unresolved aliases) also pass
through unchanged so we never silently swap to the wrong team.
"""
from __future__ import annotations


def is_spread_market(market_key: str) -> bool:
    """True iff this market_key is a spread-family market (main or
    alternate, base or period-suffixed). Examples: 'spreads',
    'alternate_spreads', 'spreads_h1', 'alternate_spreads_1st_5_innings'.
    """
    if not market_key:
        return False
    return (
        market_key.startswith("spreads")
        or market_key.startswith("alternate_spreads")
    )


def canonicalize_spread_outcome(
    outcome_name: str,
    outcome_point: float,
    home_team: str,
    away_team: str,
) -> tuple[str, float]:
    """Return the canonical (outcome_name, outcome_point) where the
    point is always <= 0 (favored team's view).

    Behavior:
      - point < 0: pass through (already canonical).
      - point > 0 and outcome_name matches home or away: flip to the
        OTHER team with the point negated.
      - point > 0 and outcome_name matches neither: pass through
        (defensive — don't guess).
      - point == 0: pass through (pickem; no orientation).

    Idempotent.
    """
    if outcome_point <= 0:
        return outcome_name, outcome_point
    # outcome_point > 0 — try to flip.
    if outcome_name == home_team:
        return away_team, -outcome_point
    if outcome_name == away_team:
        return home_team, -outcome_point
    # Unknown team — don't guess; pass through.
    return outcome_name, outcome_point
