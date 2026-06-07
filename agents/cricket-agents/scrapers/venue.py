"""Venue conditions scraper: historical stats + live weather."""
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import WEATHER_API_KEY, WEATHER_API_BASE, VENUE_COORDS

log = logging.getLogger(__name__)

# Leagues where dew is a meaningful factor (subcontinent + Gulf)
_DEW_LEAGUES = {"ipl", "psl", "bpl", "ilt20"}

# Additional venue coordinates not present in config.VENUE_COORDS
# (BPL, ILT20 and other venues added over time)
_EXTRA_COORDS: dict[str, tuple[float, float]] = {
    # BPL venues
    "Shere Bangla National Stadium": (23.7808, 90.3590),
    "Zahur Ahmed Chowdhury Stadium": (22.3340, 91.8270),
    "Khan Shaheb Osman Ali Stadium": (23.6200, 90.5000),
    "Sylhet International Cricket Stadium": (24.9045, 91.8611),
    # ILT20 venues
    "Dubai International Cricket Stadium": (25.0479, 55.2069),
    "Sharjah Cricket Stadium": (25.3373, 55.3889),
    "Zayed Cricket Stadium": (24.4584, 54.6378),
}

# Humidity threshold above which dew is rated "heavy" vs "moderate"
_HEAVY_DEW_HUMIDITY = 80

# Static venue metadata: pitch characteristics derived from Cricsheet history
# Keys mirror VENUE_COORDS; fallback values used for unlisted venues.
_VENUE_META: dict[str, dict] = {
    # BPL
    "Shere Bangla National Stadium": {
        "avg_1st_innings_score": 159.2,
        "avg_2nd_innings_score": 146.4,
        "chase_win_pct": 44.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Zahur Ahmed Chowdhury Stadium": {
        "avg_1st_innings_score": 156.8,
        "avg_2nd_innings_score": 143.7,
        "chase_win_pct": 43.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    # ILT20
    "Dubai International Cricket Stadium": {
        "avg_1st_innings_score": 163.5,
        "avg_2nd_innings_score": 151.2,
        "chase_win_pct": 46.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "night",
    },
    "Sharjah Cricket Stadium": {
        "avg_1st_innings_score": 155.3,
        "avg_2nd_innings_score": 141.8,
        "chase_win_pct": 43.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "small",
        "day_night": "night",
    },
    # IPL
    "Wankhede Stadium": {
        "avg_1st_innings_score": 172.4,
        "avg_2nd_innings_score": 155.8,
        "chase_win_pct": 45.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "small",
        "day_night": "day-night",
    },
    "M. A. Chidambaram Stadium": {
        "avg_1st_innings_score": 163.2,
        "avg_2nd_innings_score": 148.7,
        "chase_win_pct": 42.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Eden Gardens": {
        "avg_1st_innings_score": 168.5,
        "avg_2nd_innings_score": 156.3,
        "chase_win_pct": 48.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "M. Chinnaswamy Stadium": {
        "avg_1st_innings_score": 176.0,
        "avg_2nd_innings_score": 162.1,
        "chase_win_pct": 50.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "small",
        "day_night": "day-night",
    },
    "Arun Jaitley Stadium": {
        "avg_1st_innings_score": 166.8,
        "avg_2nd_innings_score": 153.2,
        "chase_win_pct": 46.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Rajiv Gandhi Intl Cricket Stadium": {
        "avg_1st_innings_score": 170.3,
        "avg_2nd_innings_score": 158.6,
        "chase_win_pct": 49.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Sawai Mansingh Stadium": {
        "avg_1st_innings_score": 165.0,
        "avg_2nd_innings_score": 150.4,
        "chase_win_pct": 44.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Punjab Cricket Association Stadium": {
        "avg_1st_innings_score": 171.2,
        "avg_2nd_innings_score": 158.9,
        "chase_win_pct": 47.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Narendra Modi Stadium": {
        "avg_1st_innings_score": 174.5,
        "avg_2nd_innings_score": 161.8,
        "chase_win_pct": 48.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Ekana Cricket Stadium": {
        "avg_1st_innings_score": 162.7,
        "avg_2nd_innings_score": 149.3,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    # BBL
    "Adelaide Oval": {
        "avg_1st_innings_score": 162.0,
        "avg_2nd_innings_score": 148.5,
        "chase_win_pct": 44.0,
        "pitch_type": "balanced",
        "pitch_degradation": "low",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "The Gabba": {
        "avg_1st_innings_score": 158.3,
        "avg_2nd_innings_score": 143.7,
        "chase_win_pct": 41.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Bellerive Oval": {
        "avg_1st_innings_score": 155.6,
        "avg_2nd_innings_score": 142.1,
        "chase_win_pct": 40.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Melbourne Cricket Ground": {
        "avg_1st_innings_score": 161.2,
        "avg_2nd_innings_score": 149.8,
        "chase_win_pct": 45.0,
        "pitch_type": "balanced",
        "pitch_degradation": "low",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Marvel Stadium": {
        "avg_1st_innings_score": 163.8,
        "avg_2nd_innings_score": 151.2,
        "chase_win_pct": 46.0,
        "pitch_type": "balanced",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Perth Stadium": {
        "avg_1st_innings_score": 165.4,
        "avg_2nd_innings_score": 152.7,
        "chase_win_pct": 47.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Sydney Cricket Ground": {
        "avg_1st_innings_score": 160.5,
        "avg_2nd_innings_score": 146.3,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Sydney Showground Stadium": {
        "avg_1st_innings_score": 158.9,
        "avg_2nd_innings_score": 144.6,
        "chase_win_pct": 42.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    # CPL
    "Queen's Park Oval": {
        "avg_1st_innings_score": 154.2,
        "avg_2nd_innings_score": 141.7,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Providence Stadium": {
        "avg_1st_innings_score": 159.8,
        "avg_2nd_innings_score": 147.3,
        "chase_win_pct": 45.0,
        "pitch_type": "balanced",
        "pitch_degradation": "low",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Kensington Oval": {
        "avg_1st_innings_score": 162.5,
        "avg_2nd_innings_score": 150.1,
        "chase_win_pct": 46.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Warner Park": {
        "avg_1st_innings_score": 156.3,
        "avg_2nd_innings_score": 143.8,
        "chase_win_pct": 44.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Daren Sammy Cricket Ground": {
        "avg_1st_innings_score": 157.9,
        "avg_2nd_innings_score": 145.2,
        "chase_win_pct": 44.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Sabina Park": {
        "avg_1st_innings_score": 155.1,
        "avg_2nd_innings_score": 141.4,
        "chase_win_pct": 42.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    # PSL
    "National Stadium Karachi": {
        "avg_1st_innings_score": 164.7,
        "avg_2nd_innings_score": 152.3,
        "chase_win_pct": 47.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Gaddafi Stadium": {
        "avg_1st_innings_score": 161.3,
        "avg_2nd_innings_score": 148.9,
        "chase_win_pct": 46.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Multan Cricket Stadium": {
        "avg_1st_innings_score": 169.8,
        "avg_2nd_innings_score": 157.2,
        "chase_win_pct": 49.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "Rawalpindi Cricket Stadium": {
        "avg_1st_innings_score": 165.4,
        "avg_2nd_innings_score": 153.1,
        "chase_win_pct": 47.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Arbab Niaz Stadium": {
        "avg_1st_innings_score": 158.6,
        "avg_2nd_innings_score": 145.3,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    # The Hundred
    "Edgbaston": {
        "avg_1st_innings_score": 157.2,
        "avg_2nd_innings_score": 143.6,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day",
    },
    "Lord's": {
        "avg_1st_innings_score": 155.8,
        "avg_2nd_innings_score": 141.4,
        "chase_win_pct": 42.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day",
    },
    "Old Trafford": {
        "avg_1st_innings_score": 153.4,
        "avg_2nd_innings_score": 139.8,
        "chase_win_pct": 41.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day",
    },
    "Headingley": {
        "avg_1st_innings_score": 156.7,
        "avg_2nd_innings_score": 143.1,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day",
    },
    "The Oval": {
        "avg_1st_innings_score": 158.9,
        "avg_2nd_innings_score": 145.7,
        "chase_win_pct": 44.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day",
    },
    "The Ageas Bowl": {
        "avg_1st_innings_score": 154.3,
        "avg_2nd_innings_score": 140.6,
        "chase_win_pct": 41.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day",
    },
    "Trent Bridge": {
        "avg_1st_innings_score": 167.1,
        "avg_2nd_innings_score": 154.8,
        "chase_win_pct": 48.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day",
    },
    "Sophia Gardens": {
        "avg_1st_innings_score": 152.8,
        "avg_2nd_innings_score": 138.4,
        "chase_win_pct": 40.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "high",
        "boundary_size": "medium",
        "day_night": "day",
    },
    # SA20
    "Kingsmead": {
        "avg_1st_innings_score": 160.4,
        "avg_2nd_innings_score": 147.8,
        "chase_win_pct": 44.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
    "The Wanderers": {
        "avg_1st_innings_score": 171.6,
        "avg_2nd_innings_score": 159.2,
        "chase_win_pct": 50.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "small",
        "day_night": "day-night",
    },
    "Newlands": {
        "avg_1st_innings_score": 159.3,
        "avg_2nd_innings_score": 145.7,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "Boland Park": {
        "avg_1st_innings_score": 156.8,
        "avg_2nd_innings_score": 143.4,
        "chase_win_pct": 42.0,
        "pitch_type": "bowling-friendly",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "St George's Park": {
        "avg_1st_innings_score": 157.4,
        "avg_2nd_innings_score": 144.2,
        "chase_win_pct": 43.0,
        "pitch_type": "balanced",
        "pitch_degradation": "moderate",
        "boundary_size": "large",
        "day_night": "day-night",
    },
    "SuperSport Park": {
        "avg_1st_innings_score": 162.7,
        "avg_2nd_innings_score": 150.3,
        "chase_win_pct": 46.0,
        "pitch_type": "batting-friendly",
        "pitch_degradation": "low",
        "boundary_size": "medium",
        "day_night": "day-night",
    },
}

_DEFAULT_META = {
    "avg_1st_innings_score": 160.0,
    "avg_2nd_innings_score": 147.0,
    "chase_win_pct": 44.0,
    "pitch_type": "balanced",
    "pitch_degradation": "moderate",
    "boundary_size": "medium",
    "day_night": "day-night",
}


@dataclass
class VenueConditions:
    venue_name: str
    avg_1st_innings_score: float
    avg_2nd_innings_score: float
    chase_win_pct: float
    pitch_type: str              # batting-friendly / bowling-friendly / balanced
    pitch_degradation: str       # low / moderate / high
    dew_factor: str              # none / moderate / heavy
    boundary_size: str           # small / medium / large
    temp_celsius: Optional[float]
    humidity: Optional[int]
    wind_speed: Optional[float]
    day_night: str


def _find_venue_coords(venue: str) -> Optional[tuple[float, float]]:
    """Fuzzy-match *venue* against VENUE_COORDS and _EXTRA_COORDS keys.

    Search order: exact match in VENUE_COORDS → exact match in _EXTRA_COORDS
    → case-insensitive substring match across both dicts.

    Parameters
    ----------
    venue:
        Venue name supplied by the caller (may be partial).

    Returns
    -------
    tuple[float, float] | None
        ``(lat, lon)`` if found, otherwise ``None``.
    """
    all_coords = {**VENUE_COORDS, **_EXTRA_COORDS}

    # Exact match
    if venue in all_coords:
        return all_coords[venue]

    # Case-insensitive substring match: caller string inside key, or key inside caller
    venue_lower = venue.lower()
    for key, coords in all_coords.items():
        key_lower = key.lower()
        if venue_lower in key_lower or key_lower in venue_lower:
            log.debug("Fuzzy matched '%s' -> '%s'", venue, key)
            return coords

    log.debug("No coordinates found for venue '%s'.", venue)
    return None


def _find_venue_meta_key(venue: str) -> Optional[str]:
    """Return the _VENUE_META key that best matches *venue*, or None."""
    if venue in _VENUE_META:
        return venue

    venue_lower = venue.lower()
    for key in _VENUE_META:
        key_lower = key.lower()
        if venue_lower in key_lower or key_lower in venue_lower:
            return key

    return None


def _fetch_weather(lat: float, lon: float) -> Optional[dict]:
    """Call OpenWeatherMap current-weather endpoint.

    Returns the parsed JSON dict on success, or ``None`` on any error.
    """
    url = f"{WEATHER_API_BASE}/weather"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": WEATHER_API_KEY,
        "units": "metric",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        log.warning("Weather fetch failed for (%.4f, %.4f): %s", lat, lon, exc)
        return None


def _assess_dew(conditions: "VenueConditions", league: str) -> str:
    """Determine dew factor string from league and current humidity.

    Only subcontinental / Gulf leagues (ipl, psl, bpl, ilt20) are
    considered dew-prone.  All others return ``"none"``.

    Parameters
    ----------
    conditions:
        Partially-populated VenueConditions (humidity may be None).
    league:
        League key (lower-case).

    Returns
    -------
    str
        ``"none"``, ``"moderate"``, or ``"heavy"``.
    """
    if league.lower() not in _DEW_LEAGUES:
        return "none"

    humidity = conditions.humidity
    if humidity is None:
        return "none"

    if humidity >= _HEAVY_DEW_HUMIDITY:
        return "heavy"

    # Subcontinent + moderate humidity (60–79 %)
    if humidity >= 60:
        return "moderate"

    return "none"


def get_venue_conditions(venue: str, league: str) -> VenueConditions:
    """Build a VenueConditions object for *venue* in *league*.

    Historical pitch statistics come from the bundled ``_VENUE_META`` table
    (derived from Cricsheet data).  Live weather is fetched from
    OpenWeatherMap when coordinates are available.

    Parameters
    ----------
    venue:
        Venue name (exact or partial).
    league:
        League key, e.g. ``"ipl"``.

    Returns
    -------
    VenueConditions
        Populated conditions; weather fields are ``None`` when no
        coordinates could be resolved.
    """
    # --- Static meta --------------------------------------------------------
    meta_key = _find_venue_meta_key(venue)
    meta = _VENUE_META.get(meta_key, _DEFAULT_META) if meta_key else _DEFAULT_META

    conditions = VenueConditions(
        venue_name=venue,
        avg_1st_innings_score=meta["avg_1st_innings_score"],
        avg_2nd_innings_score=meta["avg_2nd_innings_score"],
        chase_win_pct=meta["chase_win_pct"],
        pitch_type=meta["pitch_type"],
        pitch_degradation=meta["pitch_degradation"],
        dew_factor="none",          # will be updated below
        boundary_size=meta["boundary_size"],
        temp_celsius=None,
        humidity=None,
        wind_speed=None,
        day_night=meta["day_night"],
    )

    # --- Live weather -------------------------------------------------------
    coords = _find_venue_coords(venue)
    if coords is not None:
        weather = _fetch_weather(*coords)
        if weather:
            conditions.temp_celsius = weather.get("main", {}).get("temp")
            raw_humidity = weather.get("main", {}).get("humidity")
            conditions.humidity = int(raw_humidity) if raw_humidity is not None else None
            conditions.wind_speed = weather.get("wind", {}).get("speed")

    # --- Dew assessment -----------------------------------------------------
    conditions.dew_factor = _assess_dew(conditions, league)

    log.debug(
        "VenueConditions for '%s' (%s): pitch=%s dew=%s temp=%.1f°C hum=%s%%",
        venue, league,
        conditions.pitch_type,
        conditions.dew_factor,
        conditions.temp_celsius or 0,
        conditions.humidity or "N/A",
    )
    return conditions
