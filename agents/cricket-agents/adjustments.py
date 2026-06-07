"""League and venue adjustments for edge detection multipliers.

The base multipliers in config.py assume a global average T20 distribution.
These adjustments scale the effective std_dev (and thus the multiplier) based
on the specific league and venue context, producing sharper edge estimates.

Usage:
    from adjustments import get_adjusted_multiplier
    multiplier = get_adjusted_multiplier("match_total_runs", league="ipl", venue="Wankhede Stadium")
"""
import math
from config import BET_TYPES

# League scoring factors relative to global T20 baseline (1.00)
# Higher factor = higher scoring = higher variance = smaller multiplier (less sensitive)
# Source: ESPNcricinfo league averages 2023-2025, CricViz analysis
# Source: ESPNcricinfo, SweepCricket, Wisden, AdvanceCricket 2023-2025 data
# IPL 2023-25 blended: 187 avg 1st inn, 363 match total, 55 PP, 16.6 6s, 29.7 4s
# BBL 2023-25: ~157, ~305, ~45, ~10, ~25
# PSL 2023-25: ~168, ~330, ~47, ~11, ~25
# CPL 2023-24: ~158, ~312, ~44, ~12, ~23
# SA20 2024-25: ~163, ~318, ~47, ~13, ~25
# Hundred 2023-24: ~149 (100-ball), ~293, ~40, ~9, ~22
LEAGUE_SCORING_FACTORS = {
    "ipl": {
        "match_total_runs": 1.21,    # 363/300 vs T20I baseline
        "team_total_runs": 1.21,     # 187/155
        "powerplay_runs": 1.20,      # 55/46, Impact Player inflates PP heavily
        "match_total_sixes": 1.66,   # 16.6/10 — IPL six-hitting is 66% above baseline
        "match_total_fours": 1.24,   # 29.7/24
        "spread": 1.10,
        "first_over_runs": 1.15,
        "fall_of_first_wicket": 1.15,
        "runs_conceded": 1.15,
    },
    "bbl": {
        "match_total_runs": 1.02,    # 305/300 — close to T20I baseline
        "team_total_runs": 1.01,     # 157/155
        "powerplay_runs": 0.98,      # 45/46, 4-over mandatory PP + Power Surge
        "match_total_sixes": 1.00,   # 10/10 — at baseline
        "match_total_fours": 1.04,   # 25/24
        "spread": 0.95,
        "first_over_runs": 0.95,
        "fall_of_first_wicket": 0.95,
        "runs_conceded": 1.00,
    },
    "psl": {
        "match_total_runs": 1.10,    # 330/300
        "team_total_runs": 1.08,     # 168/155
        "powerplay_runs": 1.02,      # 47/46
        "match_total_sixes": 1.10,   # 11/10
        "match_total_fours": 1.04,   # 25/24
        "spread": 1.00,
        "first_over_runs": 1.00,
        "fall_of_first_wicket": 1.00,
        "runs_conceded": 1.05,
    },
    "cpl": {
        "match_total_runs": 1.04,    # 312/300
        "team_total_runs": 1.02,     # 158/155
        "powerplay_runs": 0.96,      # 44/46
        "match_total_sixes": 1.20,   # 12/10 — Caribbean power-hitting
        "match_total_fours": 0.96,   # 23/24
        "spread": 1.05,
        "first_over_runs": 0.95,
        "fall_of_first_wicket": 0.98,
        "runs_conceded": 1.00,
    },
    "sa20": {
        "match_total_runs": 1.06,    # 318/300
        "team_total_runs": 1.05,     # 163/155
        "powerplay_runs": 1.02,      # 47/46
        "match_total_sixes": 1.30,   # 13/10 — altitude at Wanderers
        "match_total_fours": 1.04,   # 25/24
        "spread": 1.00,
        "first_over_runs": 1.00,
        "fall_of_first_wicket": 1.00,
        "runs_conceded": 1.03,
    },
    "hundred": {
        "match_total_runs": 0.83,    # 100-ball format ≈ 83% of T20 deliveries
        "team_total_runs": 0.83,     # 149*120/100=179 equivalent, but absolute is 149
        "powerplay_runs": 0.87,      # 40/46
        "match_total_sixes": 0.90,   # 9/10
        "match_total_fours": 0.92,   # 22/24
        "spread": 0.85,
        "first_over_runs": 0.85,     # 5-ball sets not 6
        "fall_of_first_wicket": 0.85,
        "runs_conceded": 0.85,
    },
    "bpl": {
        "match_total_runs": 0.98,
        "team_total_runs": 0.97,
        "powerplay_runs": 0.93,
        "match_total_sixes": 0.90,
        "match_total_fours": 0.92,
        "spread": 1.05,
        "first_over_runs": 0.93,
        "fall_of_first_wicket": 0.95,
        "runs_conceded": 0.97,
    },
    "ilt20": {
        "match_total_runs": 1.03,
        "team_total_runs": 1.02,
        "powerplay_runs": 0.98,
        "match_total_sixes": 1.05,
        "match_total_fours": 1.00,
        "spread": 1.00,
        "first_over_runs": 0.98,
        "fall_of_first_wicket": 1.00,
        "runs_conceded": 1.00,
    },
}

# Venue scoring factors relative to league average (1.00)
# Captures venue-specific pitch, ground size, altitude, and conditions
# Source: ESPNcricinfo venue records, last 3 years of T20 data
VENUE_SCORING_FACTORS = {
    # IPL — High scoring (researched from AdvanceCricket/ESPNcricinfo 2023-2025)
    "Wankhede Stadium": 1.12,           # Avg 1st inn: 182, small ground, pace+bounce
    "M. Chinnaswamy Stadium": 1.10,     # Avg 1st inn: 179, smallest boundaries, altitude
    "Rajiv Gandhi Intl Cricket Stadium": 1.09,  # Avg 1st inn: 178, flat track
    "Sawai Mansingh Stadium": 1.02,     # Avg 1st inn: 166, balanced
    "Ekana Cricket Stadium": 1.04,      # Avg 1st inn: 170, flat deck

    # IPL — Medium scoring
    "Eden Gardens": 1.07,               # Avg 1st inn: 175, good for chasing, heavy dew
    "Punjab Cricket Association Stadium": 1.07,  # Avg 1st inn: 174, pace+carry
    "Arun Jaitley Stadium": 1.05,       # Avg 1st inn: 171, evening dew
    "Narendra Modi Stadium": 1.04,      # Avg 1st inn: 170, large ground

    # IPL — Lower scoring
    "M. A. Chidambaram Stadium": 1.03,  # Avg 1st inn: 168, spin-friendly, slow turn

    # BBL venues
    "Adelaide Oval": 1.05,
    "Melbourne Cricket Ground": 0.95,   # Large ground
    "Sydney Cricket Ground": 1.00,
    "Perth Stadium": 0.92,             # Pace and bounce
    "The Gabba": 1.00,
    "Bellerive Oval": 1.02,
    "Marvel Stadium": 1.05,            # Roofed, consistent
    "Sydney Showground Stadium": 1.02,

    # PSL venues
    "National Stadium Karachi": 0.95,
    "Gaddafi Stadium": 1.00,
    "Rawalpindi Cricket Stadium": 0.98,
    "Multan Cricket Stadium": 0.95,

    # SA20 venues
    "Newlands": 1.05,                  # Small ground, flat
    "The Wanderers": 1.08,             # Altitude, fast outfield
    "SuperSport Park": 1.00,
    "Kingsmead": 0.98,
    "St George's Park": 0.95,
    "Boland Park": 1.00,

    # CPL venues
    "Queen's Park Oval": 0.98,
    "Providence Stadium": 0.95,
    "Kensington Oval": 1.00,
    "Warner Park": 1.02,
    "Daren Sammy Cricket Ground": 0.95,

    # The Hundred venues
    "Edgbaston": 1.02,
    "Lord's": 0.95,
    "Old Trafford": 1.00,
    "Headingley": 1.05,
    "The Oval": 1.00,
    "The Ageas Bowl": 0.98,
    "Trent Bridge": 1.08,              # Historically high-scoring
    "Sophia Gardens": 0.95,
}

# Innings-specific adjustments
# Second innings has higher variance due to chase dynamics (bimodal)
INNINGS_VARIANCE_FACTOR = {
    "first_innings": 0.93,   # Slightly lower variance (more predictable)
    "second_innings": 1.12,  # Higher variance (chase dynamics, dew)
}

# Dew factor scoring adjustments for second innings
DEW_SCORING_BOOST = {
    "none": 1.00,
    "light": 1.03,
    "moderate": 1.06,
    "heavy": 1.10,     # Heavy dew can add 10% to second innings scoring
}


def get_league_factor(league: str, bet_type: str) -> float:
    """Get the league-specific scaling factor for a bet type.

    Returns 1.0 if league or bet_type not found (no adjustment).
    """
    league_factors = LEAGUE_SCORING_FACTORS.get(league, {})
    return league_factors.get(bet_type, 1.0)


def get_venue_factor(venue: str) -> float:
    """Get the venue-specific scoring factor.

    Returns 1.0 if venue not found (no adjustment).
    Uses fuzzy matching: checks if any known venue name is contained
    in the input string.
    """
    if not venue:
        return 1.0

    # Exact match
    if venue in VENUE_SCORING_FACTORS:
        return VENUE_SCORING_FACTORS[venue]

    # Fuzzy match: check if venue name contains a known key (or vice versa)
    venue_lower = venue.lower()
    for known_venue, factor in VENUE_SCORING_FACTORS.items():
        if known_venue.lower() in venue_lower or venue_lower in known_venue.lower():
            return factor

    return 1.0


def get_adjusted_std_dev(
    bet_type: str,
    league: str | None = None,
    venue: str | None = None,
) -> float | None:
    """Get the adjusted standard deviation for a bet type, accounting for
    league and venue context.

    The base std_dev from BET_TYPES is scaled by:
      adjusted_std_dev = base_std_dev * league_factor * venue_factor

    Higher scoring environments have proportionally higher variance.

    Returns None for non-linear engine bet types (they don't use std_dev).
    """
    cfg = BET_TYPES.get(bet_type, {})
    base_std_dev = cfg.get("std_dev")
    if base_std_dev is None:
        return None

    league_factor = get_league_factor(league, bet_type) if league else 1.0
    venue_factor = get_venue_factor(venue) if venue else 1.0

    return base_std_dev * league_factor * venue_factor


def get_adjusted_multiplier(
    bet_type: str,
    league: str | None = None,
    venue: str | None = None,
) -> float | None:
    """Get the adjusted multiplier for a linear-engine bet type.

    multiplier = 1 / (2 * adjusted_std_dev)

    Returns None for non-linear bet types.
    """
    adjusted_std_dev = get_adjusted_std_dev(bet_type, league, venue)
    if adjusted_std_dev is None or adjusted_std_dev <= 0:
        return None
    return 1.0 / (2.0 * adjusted_std_dev)
