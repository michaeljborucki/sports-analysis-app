"""Tests for scrapers/venue.py — Venue conditions scraper."""
from unittest.mock import patch, MagicMock

import pytest

from scrapers.venue import get_venue_conditions, VenueConditions


# ---------------------------------------------------------------------------
# Sample weather API response (OpenWeatherMap /weather)
# ---------------------------------------------------------------------------

SAMPLE_WEATHER_RESPONSE = {
    "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
    "main": {
        "temp": 32.5,
        "humidity": 68,
    },
    "wind": {"speed": 4.2},
    "name": "Mumbai",
}

HUMID_WEATHER_RESPONSE = {
    "weather": [{"id": 801, "main": "Clouds", "description": "few clouds"}],
    "main": {
        "temp": 28.0,
        "humidity": 85,
    },
    "wind": {"speed": 2.1},
    "name": "Karachi",
}

VERY_HUMID_WEATHER_RESPONSE = {
    "weather": [{"id": 801, "main": "Clouds", "description": "scattered clouds"}],
    "main": {
        "temp": 26.0,
        "humidity": 92,
    },
    "wind": {"speed": 1.5},
    "name": "Dhaka",
}


# ---------------------------------------------------------------------------
# get_venue_conditions — known venue with weather data
# ---------------------------------------------------------------------------


@patch("scrapers.venue.requests.get")
def test_get_venue_conditions_returns_venue_conditions(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    assert isinstance(conditions, VenueConditions)
    assert conditions.venue_name == "Wankhede Stadium"


@patch("scrapers.venue.requests.get")
def test_get_venue_conditions_populates_weather_fields(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    assert conditions.temp_celsius == 32.5
    assert conditions.humidity == 68
    assert conditions.wind_speed == 4.2


@patch("scrapers.venue.requests.get")
def test_get_venue_conditions_has_expected_fields(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    # All required dataclass fields must be present
    assert hasattr(conditions, "avg_1st_innings_score")
    assert hasattr(conditions, "avg_2nd_innings_score")
    assert hasattr(conditions, "chase_win_pct")
    assert hasattr(conditions, "pitch_type")
    assert hasattr(conditions, "pitch_degradation")
    assert hasattr(conditions, "dew_factor")
    assert hasattr(conditions, "boundary_size")
    assert hasattr(conditions, "day_night")


# ---------------------------------------------------------------------------
# get_venue_conditions — dew factor assessment for subcontinental leagues
# ---------------------------------------------------------------------------


@patch("scrapers.venue.requests.get")
def test_dew_factor_moderate_for_ipl_with_moderate_humidity(mock_get):
    """IPL + humidity around 68% → moderate dew."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE  # humidity=68
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    assert conditions.dew_factor in ("none", "moderate", "heavy")


@patch("scrapers.venue.requests.get")
def test_dew_factor_heavy_for_psl_with_high_humidity(mock_get):
    """PSL + humidity ≥ 80% → heavy dew."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = HUMID_WEATHER_RESPONSE  # humidity=85
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("National Stadium Karachi", "psl")

    assert conditions.dew_factor == "heavy"


@patch("scrapers.venue.requests.get")
def test_dew_factor_heavy_for_bpl_very_high_humidity(mock_get):
    """BPL + humidity ≥ 80% → heavy dew."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = VERY_HUMID_WEATHER_RESPONSE  # humidity=92
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    # Use a known venue; fallback to default coords if not found
    conditions = get_venue_conditions("Shere Bangla National Stadium", "bpl")

    assert conditions.dew_factor == "heavy"


@patch("scrapers.venue.requests.get")
def test_dew_factor_none_for_non_subcontinental_league(mock_get):
    """BBL (Australia) → dew_factor should be 'none' regardless of humidity."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = HUMID_WEATHER_RESPONSE  # humidity=85
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Adelaide Oval", "bbl")

    assert conditions.dew_factor == "none"


# ---------------------------------------------------------------------------
# get_venue_conditions — unknown venue (no coords)
# ---------------------------------------------------------------------------


@patch("scrapers.venue.requests.get")
def test_unknown_venue_returns_conditions_with_none_weather(mock_get):
    """When no coordinates are found, weather fields remain None."""
    mock_get.return_value = MagicMock()  # Should not be called

    conditions = get_venue_conditions("Totally Unknown Ground XYZ", "ipl")

    assert isinstance(conditions, VenueConditions)
    assert conditions.temp_celsius is None
    assert conditions.humidity is None
    assert conditions.wind_speed is None


@patch("scrapers.venue.requests.get")
def test_unknown_venue_does_not_call_weather_api(mock_get):
    """No HTTP call should be made when no coords are found."""
    get_venue_conditions("Unknown Venue 999", "bbl")

    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# get_venue_conditions — fuzzy venue matching
# ---------------------------------------------------------------------------


@patch("scrapers.venue.requests.get")
def test_fuzzy_match_partial_venue_name(mock_get):
    """Partial venue name 'Wankhede' should match 'Wankhede Stadium'."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede", "ipl")

    # Should have resolved coords and fetched weather
    assert conditions.temp_celsius == 32.5


# ---------------------------------------------------------------------------
# get_venue_conditions — pitch type and boundary size have valid values
# ---------------------------------------------------------------------------


@patch("scrapers.venue.requests.get")
def test_pitch_type_is_valid_value(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    assert conditions.pitch_type in ("batting-friendly", "bowling-friendly", "balanced")


@patch("scrapers.venue.requests.get")
def test_boundary_size_is_non_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    conditions = get_venue_conditions("Wankhede Stadium", "ipl")

    assert conditions.boundary_size  # non-empty string
