"""Match conditions: surface, weather, altitude."""
import logging
import requests
from config import WEATHER_API_KEY, WEATHER_API_BASE

logger = logging.getLogger("mirofish.scrapers.conditions")


def get_match_conditions(tournament: str = "", surface: str = "hard", indoor_outdoor: str = "outdoor") -> dict:
    conditions = {
        "surface": surface,
        "indoor_outdoor": indoor_outdoor,
        "temperature": "N/A",
        "humidity": "N/A",
        "wind": "N/A",
        "altitude": _get_altitude(tournament),
        "session": "day",
    }
    if indoor_outdoor == "outdoor" and WEATHER_API_KEY:
        coords = _tournament_coords(tournament)
        if coords:
            weather = _fetch_weather(coords[0], coords[1])
            conditions.update(weather)
    return conditions


def _get_altitude(tournament: str) -> str:
    high_altitude = {"bogota": "8660ft", "quito": "9350ft", "mexico city": "7350ft"}
    for city, alt in high_altitude.items():
        if city in tournament.lower():
            return alt
    return "sea level"


def _tournament_coords(tournament: str) -> tuple[float, float] | None:
    known = {
        "australian open": (-37.8218, 144.9785), "roland garros": (48.8469, 2.2484),
        "french open": (48.8469, 2.2484), "wimbledon": (51.4341, -0.2143),
        "us open": (40.7498, -73.8459), "indian wells": (33.7238, -116.3052),
        "miami": (25.7097, -80.1576), "monte carlo": (43.7500, 7.4400),
        "madrid": (40.3726, -3.6834), "rome": (41.9318, 12.4589),
    }
    for name, coords in known.items():
        if name in tournament.lower():
            return coords
    return None


def _fetch_weather(lat: float, lon: float) -> dict:
    try:
        resp = requests.get(f"{WEATHER_API_BASE}/weather", params={"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "imperial"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {"temperature": f"{data['main']['temp']:.0f}°F", "humidity": f"{data['main']['humidity']}%", "wind": f"{data['wind']['speed']:.0f}mph"}
    except Exception as e:
        logger.warning("Weather fetch failed: %s", e)
        return {}
