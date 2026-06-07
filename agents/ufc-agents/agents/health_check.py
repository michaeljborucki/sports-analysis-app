"""Pre-game health check: validates API keys, data sources, connectivity."""
import click
import requests
from config import (
    ODDS_API_KEY, OPENROUTER_API_KEY,
    ODDS_API_BASE,
    OPENROUTER_BASE_URL,
)


def check_ufc_stats():
    """Validate UFCStats.com is reachable."""
    try:
        resp = requests.get("http://ufcstats.com/statistics/events/completed", timeout=10)
        return {"status": "ok", "source": "UFCStats.com"} if resp.status_code == 200 else {"status": "error"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


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


def run_health_check() -> bool:
    """Run all health checks. Returns True if critical checks pass."""
    click.echo("\n=== MiroFish Health Check ===\n")

    checks = [
        ("CRITICAL", check_ufc_stats),
        ("CRITICAL", check_odds_api),
        ("CRITICAL", check_openrouter),
    ]

    all_critical_pass = True
    for level, check_fn in checks:
        result = check_fn()
        # check_ufc_stats returns a dict, others return tuple
        if isinstance(result, dict):
            ok = result.get("status") == "ok"
            msg = f"UFCStats.com: {'OK' if ok else 'FAIL'}"
        else:
            ok, msg = result
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
