"""Pre-game health check: validates API keys, data sources, connectivity."""
import click
import requests
from config import (
    ODDS_API_KEY, OPENROUTER_API_KEY, WEATHER_API_KEY,
    CRICKET_API_BASE, CRICKET_API_KEY, ODDS_API_BASE, WEATHER_API_BASE,
    OPENROUTER_BASE_URL,
)


def check_cricket_api() -> tuple[bool, str]:
    """Check Cricket API is reachable."""
    try:
        resp = requests.get(
            f"{CRICKET_API_BASE}/matches",
            params={"apikey": CRICKET_API_KEY},
            timeout=10,
        )
        return resp.status_code == 200, "Cricket API: OK" if resp.status_code == 200 else f"Cricket API: FAIL (status {resp.status_code})"
    except Exception as e:
        return False, f"Cricket API: FAIL ({e})"


def check_odds_api() -> tuple[bool, str]:
    """Check The Odds API key is valid."""
    if not ODDS_API_KEY:
        return False, "Odds API: NO KEY SET"
    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports",
            params={"apiKey": ODDS_API_KEY},
            timeout=10,
        )
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
        resp = requests.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            timeout=10,
        )
        if resp.status_code == 401:
            return False, "OpenRouter: INVALID KEY"
        return True, "OpenRouter: OK"
    except Exception as e:
        return False, f"OpenRouter: FAIL ({e})"


def check_weather_api() -> tuple[bool, str]:
    """Check OpenWeatherMap API key."""
    if not WEATHER_API_KEY:
        return False, "Weather API: NO KEY SET (optional — defaults will be used)"
    try:
        resp = requests.get(
            f"{WEATHER_API_BASE}/weather",
            params={"lat": 40.8296, "lon": -73.9262, "appid": WEATHER_API_KEY},
            timeout=10,
        )
        if resp.status_code == 401:
            return False, "Weather API: INVALID KEY"
        resp.raise_for_status()
        return True, "Weather API: OK"
    except Exception as e:
        return False, f"Weather API: FAIL ({e})"


def run_health_check() -> bool:
    """Run all health checks. Returns True if critical checks pass."""
    click.echo("\n=== MiroFish Health Check ===\n")

    checks = [
        ("CRITICAL", check_cricket_api),
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
    """Run pre-game health check on all API connections."""
    run_health_check()


if __name__ == "__main__":
    main()
