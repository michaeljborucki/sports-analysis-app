"""Pre-game health check: validates API keys, data sources, connectivity."""
import os

import click
import requests
from config import (
    ODDS_API_KEY, OPENROUTER_API_KEY, WEATHER_API_KEY, API_TENNIS_KEY,
    ODDS_API_BASE, WEATHER_API_BASE, API_TENNIS_BASE,
    OPENROUTER_BASE_URL, SACKMANN_LOCAL_DIR,
)


def check_player_archive() -> tuple[bool, str]:
    """Check that the local Sackmann archive has at least the 2024 baseline."""
    atp_path = os.path.join(SACKMANN_LOCAL_DIR, "atp", "atp_matches_2024.csv")
    wta_path = os.path.join(SACKMANN_LOCAL_DIR, "wta", "wta_matches_2024.csv")
    if os.path.exists(atp_path) and os.path.exists(wta_path):
        return True, f"Player Archive: OK ({SACKMANN_LOCAL_DIR})"
    missing = []
    if not os.path.exists(atp_path):
        missing.append("atp/atp_matches_2024.csv")
    if not os.path.exists(wta_path):
        missing.append("wta/wta_matches_2024.csv")
    return False, (f"Player Archive: MISSING {missing} — run scripts/bootstrap_player_data.sh")


def check_api_tennis() -> tuple[bool, str]:
    """Check API-Tennis is reachable."""
    if not API_TENNIS_KEY:
        return False, "API-Tennis: NO KEY SET"
    try:
        resp = requests.get(API_TENNIS_BASE, params={"method": "get_events", "APIkey": API_TENNIS_KEY}, timeout=10)
        resp.raise_for_status()
        return True, "API-Tennis: OK"
    except Exception as e:
        return False, f"API-Tennis: FAIL ({e})"


def check_odds_api() -> tuple[bool, str]:
    """Check The Odds API key is valid."""
    if not ODDS_API_KEY:
        return False, "Odds API: NO KEY SET"
    try:
        resp = requests.get(f"{ODDS_API_BASE}/sports", params={"apiKey": ODDS_API_KEY}, timeout=10)
        remaining = resp.headers.get("x-requests-remaining", "?")
        if resp.status_code == 401:
            return False, "Odds API: INVALID KEY"
        resp.raise_for_status()
        return True, f"Odds API: OK ({remaining} requests remaining)"
    except Exception as e:
        return False, f"Odds API: FAIL ({e})"


def check_openrouter() -> tuple[bool, str]:
    """Check OpenRouter API key is valid."""
    if not OPENROUTER_API_KEY:
        return False, "OpenRouter: NO KEY SET"
    try:
        resp = requests.get(f"{OPENROUTER_BASE_URL}/models", headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"}, timeout=10)
        if resp.status_code == 401:
            return False, "OpenRouter: INVALID KEY"
        return True, "OpenRouter: OK"
    except Exception as e:
        return False, f"OpenRouter: FAIL ({e})"


def check_weather_api() -> tuple[bool, str]:
    """Check OpenWeatherMap API key."""
    if not WEATHER_API_KEY:
        return False, "Weather API: NO KEY SET (optional)"
    try:
        resp = requests.get(f"{WEATHER_API_BASE}/weather", params={"lat": 40.7498, "lon": -73.8459, "appid": WEATHER_API_KEY}, timeout=10)
        if resp.status_code == 401:
            return False, "Weather API: INVALID KEY"
        resp.raise_for_status()
        return True, "Weather API: OK"
    except Exception as e:
        return False, f"Weather API: FAIL ({e})"


def run_health_check() -> bool:
    """Run all health checks. Returns True if critical checks pass."""
    click.echo("\n=== MiroFish Tennis Health Check ===\n")

    checks = [
        ("CRITICAL", check_api_tennis),
        ("CRITICAL", check_player_archive),
        ("CRITICAL", check_odds_api),
        ("CRITICAL", check_openrouter),
        ("OPTIONAL", check_weather_api),
    ]

    all_critical_pass = True
    for level, check_fn in checks:
        ok, msg = check_fn()
        prefix = "  [OK]" if ok else "  [FAIL]"
        click.echo(f"{prefix} {msg}")
        if not ok and level == "CRITICAL":
            all_critical_pass = False

    click.echo()
    if all_critical_pass:
        click.echo("All critical checks passed. Pipeline ready.")
    else:
        click.echo("CRITICAL checks failed. Fix before running pipeline.")

    return all_critical_pass


@click.command()
def main():
    run_health_check()

if __name__ == "__main__":
    main()
