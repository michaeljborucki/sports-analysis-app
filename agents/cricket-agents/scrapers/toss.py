"""Toss impact analysis from historical T20 data."""
import logging
from dataclasses import dataclass

logger = logging.getLogger("cricket.scrapers.toss")


@dataclass
class TossAnalysis:
    venue: str
    bat_first_pct: float         # fraction of teams that bat first after winning toss
    chase_pct: float             # fraction of teams that field first after winning toss
    bat_first_win_rate: float    # win rate when batting first
    chase_win_rate: float        # win rate when chasing
    typical_toss_choice: str     # "bat" or "field"
    dew_assessment: str          # description of dew impact
    sample_size: int             # number of T20 matches in dataset


# Hardcoded historical data for major T20 venues.
# Sources: Cricsheet data + ESPNcricinfo venue stats.
VENUE_TOSS_DATA: dict[str, dict] = {
    # IPL venues
    "Wankhede Stadium": {
        "bat_first_pct": 0.42,
        "chase_pct": 0.58,
        "bat_first_win_rate": 0.44,
        "chase_win_rate": 0.56,
        "typical_toss_choice": "field",
        "dew_assessment": "Significant dew in evening matches; captains prefer to field",
        "sample_size": 95,
    },
    "M. A. Chidambaram Stadium": {
        "bat_first_pct": 0.45,
        "chase_pct": 0.55,
        "bat_first_win_rate": 0.46,
        "chase_win_rate": 0.54,
        "typical_toss_choice": "field",
        "dew_assessment": "Moderate dew effect in evening; slight advantage chasing",
        "sample_size": 72,
    },
    "Eden Gardens": {
        "bat_first_pct": 0.48,
        "chase_pct": 0.52,
        "bat_first_win_rate": 0.48,
        "chase_win_rate": 0.52,
        "typical_toss_choice": "field",
        "dew_assessment": "Dew can affect second innings; marginal chasing advantage",
        "sample_size": 88,
    },
    "M. Chinnaswamy Stadium": {
        "bat_first_pct": 0.55,
        "chase_pct": 0.45,
        "bat_first_win_rate": 0.55,
        "chase_win_rate": 0.45,
        "typical_toss_choice": "bat",
        "dew_assessment": "High altitude and true surface favour batting first",
        "sample_size": 80,
    },
    "Arun Jaitley Stadium": {
        "bat_first_pct": 0.46,
        "chase_pct": 0.54,
        "bat_first_win_rate": 0.45,
        "chase_win_rate": 0.55,
        "typical_toss_choice": "field",
        "dew_assessment": "Noticeable dew; captains prefer to chase",
        "sample_size": 68,
    },
    "Rajiv Gandhi Intl Cricket Stadium": {
        "bat_first_pct": 0.40,
        "chase_pct": 0.60,
        "bat_first_win_rate": 0.42,
        "chase_win_rate": 0.58,
        "typical_toss_choice": "field",
        "dew_assessment": "Heavy dew typical in evening; strong chasing advantage",
        "sample_size": 60,
    },
    "Sawai Mansingh Stadium": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.50,
        "chase_win_rate": 0.50,
        "typical_toss_choice": "bat",
        "dew_assessment": "Dry conditions in Jaipur; toss impact minimal",
        "sample_size": 55,
    },
    "Punjab Cricket Association Stadium": {
        "bat_first_pct": 0.47,
        "chase_pct": 0.53,
        "bat_first_win_rate": 0.47,
        "chase_win_rate": 0.53,
        "typical_toss_choice": "field",
        "dew_assessment": "Mild dew; slight preference to field",
        "sample_size": 50,
    },
    "Narendra Modi Stadium": {
        "bat_first_pct": 0.48,
        "chase_pct": 0.52,
        "bat_first_win_rate": 0.49,
        "chase_win_rate": 0.51,
        "typical_toss_choice": "field",
        "dew_assessment": "Minimal dew at this venue; near-neutral toss effect",
        "sample_size": 45,
    },
    "Ekana Cricket Stadium": {
        "bat_first_pct": 0.44,
        "chase_pct": 0.56,
        "bat_first_win_rate": 0.44,
        "chase_win_rate": 0.56,
        "typical_toss_choice": "field",
        "dew_assessment": "Dew factor significant in evening; captains choose to field",
        "sample_size": 38,
    },
    # BBL venues
    "Adelaide Oval": {
        "bat_first_pct": 0.52,
        "chase_pct": 0.48,
        "bat_first_win_rate": 0.53,
        "chase_win_rate": 0.47,
        "typical_toss_choice": "bat",
        "dew_assessment": "Dry Australian conditions; batting first often preferred",
        "sample_size": 65,
    },
    "The Gabba": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.50,
        "chase_win_rate": 0.50,
        "typical_toss_choice": "bat",
        "dew_assessment": "Neutral conditions; toss has minimal impact",
        "sample_size": 58,
    },
    "Bellerive Oval": {
        "bat_first_pct": 0.51,
        "chase_pct": 0.49,
        "bat_first_win_rate": 0.51,
        "chase_win_rate": 0.49,
        "typical_toss_choice": "bat",
        "dew_assessment": "Cool Hobart nights; no significant dew impact",
        "sample_size": 42,
    },
    "Melbourne Cricket Ground": {
        "bat_first_pct": 0.49,
        "chase_pct": 0.51,
        "bat_first_win_rate": 0.49,
        "chase_win_rate": 0.51,
        "typical_toss_choice": "field",
        "dew_assessment": "MCG largely neutral; slight edge for chasers",
        "sample_size": 75,
    },
    "Marvel Stadium": {
        "bat_first_pct": 0.46,
        "chase_pct": 0.54,
        "bat_first_win_rate": 0.45,
        "chase_win_rate": 0.55,
        "typical_toss_choice": "field",
        "dew_assessment": "Enclosed roof helps batting; captains prefer to field",
        "sample_size": 48,
    },
    "Perth Stadium": {
        "bat_first_pct": 0.53,
        "chase_pct": 0.47,
        "bat_first_win_rate": 0.54,
        "chase_win_rate": 0.46,
        "typical_toss_choice": "bat",
        "dew_assessment": "Fast Perth surface favours batting first",
        "sample_size": 50,
    },
    "Sydney Cricket Ground": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.51,
        "chase_win_rate": 0.49,
        "typical_toss_choice": "bat",
        "dew_assessment": "Neutral SCG surface; toss relatively balanced",
        "sample_size": 62,
    },
    "Sydney Showground Stadium": {
        "bat_first_pct": 0.48,
        "chase_pct": 0.52,
        "bat_first_win_rate": 0.47,
        "chase_win_rate": 0.53,
        "typical_toss_choice": "field",
        "dew_assessment": "Slightly favours chasing; dew minor factor",
        "sample_size": 40,
    },
    # CPL venues
    "Queen's Park Oval": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.50,
        "chase_win_rate": 0.50,
        "typical_toss_choice": "bat",
        "dew_assessment": "Tropical conditions; toss effect moderate",
        "sample_size": 35,
    },
    "Providence Stadium": {
        "bat_first_pct": 0.48,
        "chase_pct": 0.52,
        "bat_first_win_rate": 0.47,
        "chase_win_rate": 0.53,
        "typical_toss_choice": "field",
        "dew_assessment": "Humid conditions; slight advantage chasing",
        "sample_size": 32,
    },
    "Kensington Oval": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.50,
        "chase_win_rate": 0.50,
        "typical_toss_choice": "bat",
        "dew_assessment": "Neutral surface in Barbados",
        "sample_size": 40,
    },
    "Sabina Park": {
        "bat_first_pct": 0.46,
        "chase_pct": 0.54,
        "bat_first_win_rate": 0.46,
        "chase_win_rate": 0.54,
        "typical_toss_choice": "field",
        "dew_assessment": "Tropical humidity; teams tend to field first",
        "sample_size": 28,
    },
    # PSL venues
    "National Stadium Karachi": {
        "bat_first_pct": 0.47,
        "chase_pct": 0.53,
        "bat_first_win_rate": 0.46,
        "chase_win_rate": 0.54,
        "typical_toss_choice": "field",
        "dew_assessment": "Coastal humidity; evening dew gives edge to chasers",
        "sample_size": 55,
    },
    "Gaddafi Stadium": {
        "bat_first_pct": 0.51,
        "chase_pct": 0.49,
        "bat_first_win_rate": 0.51,
        "chase_win_rate": 0.49,
        "typical_toss_choice": "bat",
        "dew_assessment": "Balanced Lahore conditions",
        "sample_size": 50,
    },
    "Rawalpindi Cricket Stadium": {
        "bat_first_pct": 0.54,
        "chase_pct": 0.46,
        "bat_first_win_rate": 0.54,
        "chase_win_rate": 0.46,
        "typical_toss_choice": "bat",
        "dew_assessment": "Flat pitch; batting first advantageous",
        "sample_size": 35,
    },
    # The Hundred / county venues
    "Edgbaston": {
        "bat_first_pct": 0.48,
        "chase_pct": 0.52,
        "bat_first_win_rate": 0.47,
        "chase_win_rate": 0.53,
        "typical_toss_choice": "field",
        "dew_assessment": "English conditions; slight chasing advantage in evening",
        "sample_size": 45,
    },
    "Lord's": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.50,
        "chase_win_rate": 0.50,
        "typical_toss_choice": "bat",
        "dew_assessment": "Iconic venue; neutral toss effect",
        "sample_size": 40,
    },
    "Old Trafford": {
        "bat_first_pct": 0.46,
        "chase_pct": 0.54,
        "bat_first_win_rate": 0.46,
        "chase_win_rate": 0.54,
        "typical_toss_choice": "field",
        "dew_assessment": "Manchester moisture; teams prefer to field",
        "sample_size": 38,
    },
    "The Oval": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.51,
        "chase_win_rate": 0.49,
        "typical_toss_choice": "bat",
        "dew_assessment": "London conditions; largely neutral",
        "sample_size": 42,
    },
    "Trent Bridge": {
        "bat_first_pct": 0.52,
        "chase_pct": 0.48,
        "bat_first_win_rate": 0.53,
        "chase_win_rate": 0.47,
        "typical_toss_choice": "bat",
        "dew_assessment": "Good batting surface; teams prefer to bat",
        "sample_size": 35,
    },
    # SA20 venues
    "Kingsmead": {
        "bat_first_pct": 0.48,
        "chase_pct": 0.52,
        "bat_first_win_rate": 0.48,
        "chase_win_rate": 0.52,
        "typical_toss_choice": "field",
        "dew_assessment": "Durban humidity; slight advantage chasing",
        "sample_size": 30,
    },
    "The Wanderers": {
        "bat_first_pct": 0.52,
        "chase_pct": 0.48,
        "bat_first_win_rate": 0.53,
        "chase_win_rate": 0.47,
        "typical_toss_choice": "bat",
        "dew_assessment": "Highveld altitude boosts batting; teams bat first",
        "sample_size": 32,
    },
    "Newlands": {
        "bat_first_pct": 0.50,
        "chase_pct": 0.50,
        "bat_first_win_rate": 0.50,
        "chase_win_rate": 0.50,
        "typical_toss_choice": "bat",
        "dew_assessment": "Cape Town conditions neutral; wind the main variable",
        "sample_size": 28,
    },
    "SuperSport Park": {
        "bat_first_pct": 0.54,
        "chase_pct": 0.46,
        "bat_first_win_rate": 0.55,
        "chase_win_rate": 0.45,
        "typical_toss_choice": "bat",
        "dew_assessment": "Centurion flat pitch; strong batting first advantage",
        "sample_size": 30,
    },
}

_DEFAULT_ANALYSIS = {
    "bat_first_pct": 0.5,
    "chase_pct": 0.5,
    "bat_first_win_rate": 0.5,
    "chase_win_rate": 0.5,
    "typical_toss_choice": "bat",
    "dew_assessment": "No historical data available for this venue",
    "sample_size": 0,
}


# Generic words that appear in many venue names and should not alone trigger a match
_VENUE_STOP_WORDS = {
    "stadium", "ground", "oval", "park", "cricket", "field", "sports",
    "international", "national", "arena", "centre", "center",
}


def _fuzzy_match(venue: str) -> str | None:
    """Return best matching key from VENUE_TOSS_DATA or None.

    Matches on:
    1. Bidirectional substring containment (venue inside key or key inside venue)
    2. Token overlap — but only on non-generic tokens (> 4 chars, not in stop-words)
       and requires at least 2 matching tokens to avoid false positives.
    """
    venue_lower = venue.lower().strip()
    if not venue_lower:
        return None

    def meaningful_tokens(s: str) -> set[str]:
        return {t for t in s.split() if len(t) > 4 and t not in _VENUE_STOP_WORDS}

    best = None
    best_len = 0
    venue_tokens = meaningful_tokens(venue_lower)

    for key in VENUE_TOSS_DATA:
        key_lower = key.lower()

        # Bidirectional substring containment
        if venue_lower in key_lower or key_lower in venue_lower:
            if len(key) > best_len:
                best = key
                best_len = len(key)
            continue

        # Token overlap: require >= 2 matching meaningful tokens
        key_tokens = meaningful_tokens(key_lower)
        overlap = venue_tokens & key_tokens
        if len(overlap) >= 2:
            if len(key) > best_len:
                best = key
                best_len = len(key)

    return best


def get_toss_analysis(venue: str) -> TossAnalysis:
    """Return TossAnalysis for a venue.

    Priority:
    1. Exact match in VENUE_TOSS_DATA
    2. Fuzzy match (substring / token overlap)
    3. Default 50/50 values
    """
    # 1. Exact match
    if venue in VENUE_TOSS_DATA:
        data = VENUE_TOSS_DATA[venue]
        return TossAnalysis(venue=venue, **data)

    # 2. Fuzzy match
    matched_key = _fuzzy_match(venue)
    if matched_key:
        logger.debug("Toss fuzzy match: '%s' -> '%s'", venue, matched_key)
        data = VENUE_TOSS_DATA[matched_key]
        return TossAnalysis(venue=venue, **data)

    # 3. Default
    logger.debug("Toss: no data for venue '%s', using defaults", venue)
    return TossAnalysis(venue=venue, **_DEFAULT_ANALYSIS)
