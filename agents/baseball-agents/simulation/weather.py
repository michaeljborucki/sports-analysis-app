"""Weather → HR-rate multiplier for the Monte Carlo simulator.

Closed/dome roofs zero out the weather effect entirely. Outdoor games:
  - Temperature: ~+0.5%/°F over a 70°F neutral baseline (Statcast carry).
  - Wind: only matters above ~8 mph; "out" boosts, "in" suppresses, cross
    is neutral.

The function returns a single multiplier that should compound with
`park_factor_hr` before being applied inside `_build_matchup_probs`.
"""
from __future__ import annotations


_NEUTRAL_TEMP_F = 70.0
_TEMP_COEFF = 0.005          # +0.5% HR per +1°F (Statcast carry data)
_WIND_DEAD_ZONE_MPH = 5.0
_WIND_COEFF = 0.007          # ±0.7% HR per mph beyond the dead zone
_WIND_CAP_MPH = 25.0         # ignore the tail above this
_HR_MULT_FLOOR = 0.70
_HR_MULT_CEIL = 1.30


def weather_hr_multiplier(weather: dict | None, roof: str = "open") -> float:
    """Return the HR-rate multiplier implied by weather + roof.

    Indoors (closed/dome), or with no weather data, returns 1.0.
    """
    if roof in ("closed", "dome"):
        return 1.0
    if not weather:
        return 1.0

    temp_f = weather.get("temp_f")
    temp_mult = 1.0
    if temp_f is not None:
        temp_mult = 1.0 + (temp_f - _NEUTRAL_TEMP_F) * _TEMP_COEFF

    wind_mph = float(weather.get("wind_mph", 0) or 0)
    wind_dir = (weather.get("wind_direction") or "").lower()
    wind_mult = 1.0
    if wind_mph > _WIND_DEAD_ZONE_MPH and wind_dir in ("out", "in"):
        effective_mph = min(wind_mph, _WIND_CAP_MPH) - _WIND_DEAD_ZONE_MPH
        delta = effective_mph * _WIND_COEFF
        wind_mult = 1.0 + delta if wind_dir == "out" else 1.0 - delta

    combined = temp_mult * wind_mult
    return max(_HR_MULT_FLOOR, min(_HR_MULT_CEIL, combined))
