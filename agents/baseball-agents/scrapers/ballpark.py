import requests
from config import PARK_FACTORS, PARK_COORDS, WEATHER_API_KEY, WEATHER_API_BASE


def _classify_wind_impact(wind_mph: float, direction: str) -> str:
    if wind_mph < 8:
        return "neutral"
    if direction == "out":
        return "hitter_boost"
    if direction == "in":
        return "pitcher_boost"
    return "neutral"


def _wind_direction_label(degrees: float) -> str:
    """Simplify wind direction to ballpark-relevant label.
    This is approximate — a real implementation would need park orientation."""
    if 135 <= degrees <= 225:
        return "out"  # blowing toward outfield (south wind at most parks)
    elif 315 <= degrees or degrees <= 45:
        return "in"
    return "cross"


def get_game_environment(home_team: str, game_date: str, game_time: str = "") -> dict:
    """Get ballpark + weather environment for a game."""
    park = PARK_FACTORS.get(home_team, {})
    coords = PARK_COORDS.get(home_team)

    weather = {}
    if coords and WEATHER_API_KEY:
        try:
            lat, lon = coords
            url = f"{WEATHER_API_BASE}/weather"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": WEATHER_API_KEY,
                "units": "imperial",
            }
            resp = requests.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            wind_mph = round(data.get("wind", {}).get("speed", 0), 1)  # imperial = mph
            wind_deg = data.get("wind", {}).get("deg", 0)
            wind_dir = _wind_direction_label(wind_deg)

            weather = {
                "temp_f": round(data["main"]["temp"]),
                "humidity": data["main"].get("humidity", 0),
                "wind_mph": wind_mph,
                "wind_direction": wind_dir,
                "condition": data.get("weather", [{}])[0].get("main", ""),
            }
        except Exception:
            # If weather API fails, use empty weather — non-critical
            weather = {
                "temp_f": 72,
                "humidity": 50,
                "wind_mph": 0,
                "wind_direction": "calm",
                "condition": "Unknown",
            }
    elif coords:
        # No API key — use defaults
        weather = {
            "temp_f": 72,
            "humidity": 50,
            "wind_mph": 0,
            "wind_direction": "calm",
            "condition": "Unknown",
        }

    roof = park.get("roof", "open")
    wind_impact = "neutral"
    if roof == "open" and weather:
        wind_impact = _classify_wind_impact(
            weather.get("wind_mph", 0),
            weather.get("wind_direction", "calm"),
        )

    return {
        "ballpark": park.get("name", "Unknown"),
        "park_factor_runs": park.get("runs", 1.0),
        "park_factor_hr": park.get("hr", 1.0),
        "roof": roof,
        "weather": weather,
        "day_night": "night" if game_time and int(game_time.split(":")[0]) >= 17 else "day",
        "wind_impact": wind_impact,
    }
