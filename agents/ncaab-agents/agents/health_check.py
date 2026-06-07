"""Pre-game health check: validates API keys, data sources, connectivity."""
import click
import requests
from config import (
    ODDS_API_KEY, OPENROUTER_API_KEY, CBBDATA_API_KEY,
    ESPN_CBB_BASE, ODDS_API_BASE, CBBDATA_BASE,
    OPENROUTER_BASE_URL,
)


def check_espn_api() -> tuple[bool, str]:
    """Check ESPN NCAAB API is reachable."""
    try:
        resp = requests.get(f"{ESPN_CBB_BASE}/scoreboard", timeout=10)
        resp.raise_for_status()
        return True, "ESPN NCAAB API: OK"
    except Exception as e:
        return False, f"ESPN NCAAB API: FAIL ({e})"


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


def check_cbbdata_api() -> tuple[bool, str]:
    """Check CBBData API key is valid."""
    if not CBBDATA_API_KEY:
        return False, "CBBData API: NO KEY SET (optional — team stats will be limited)"
    try:
        resp = requests.get(
            f"{CBBDATA_BASE}/torvik/ratings",
            params={"year": 2026, "key": CBBDATA_API_KEY},
            timeout=15,
        )
        if resp.status_code == 401:
            return False, "CBBData API: INVALID KEY"
        resp.raise_for_status()
        return True, "CBBData API: OK"
    except Exception as e:
        return False, f"CBBData API: FAIL ({e})"


def run_health_check() -> bool:
    """Run all health checks. Returns True if critical checks pass."""
    click.echo("\n=== MiroFish NCAAB Health Check ===\n")

    checks = [
        ("CRITICAL", check_espn_api),
        ("CRITICAL", check_odds_api),
        ("CRITICAL", check_openrouter),
        ("OPTIONAL", check_cbbdata_api),
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
