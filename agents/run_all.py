"""MiroFish unified orchestrator: run all sport pipelines in parallel."""
import os
import re
import sys
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

import click

SPORTS = [
    {"name": "NBA", "dir": "nba-agents", "filter": "nba"},
    {"name": "NCAAB", "dir": "ncaab-agents", "filter": "ncaab"},
    {"name": "MLB", "dir": "baseball-agents", "filter": "mlb"},
    {"name": "Soccer", "dir": "soccer-agents", "filter": "soccer"},
    {"name": "Tennis", "dir": "tennis-agents", "filter": "tennis"},
    {"name": "Cricket", "dir": "cricket-agents", "filter": "cricket"},
    {"name": "UFC", "dir": "ufc-agents", "filter": "ufc"},
    {"name": "Esports", "dir": "esports-agents", "filter": "esports"},
]

NO_GAMES_PATTERNS = [
    r"No games found",
    r"No matches found",
    r"No tier 1-2 matches",
    r"No events found",
    r"No fights found",
]

BETS_PATTERN = re.compile(r"(\d+)\s+bets?\s+logged", re.IGNORECASE)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run_sport(sport, game_date, skip_health, grade, timeout=3600):
    """Run a single sport's daily pipeline. Returns a result dict."""
    sport_dir = os.path.join(BASE_DIR, sport["dir"])
    if not os.path.isdir(sport_dir):
        return {
            "sport": sport["name"],
            "status": "missing",
            "bets": 0,
            "duration": 0,
            "output": "",
            "error": f"Directory not found: {sport_dir}",
        }

    cmd = [sys.executable, "-m", "agents.daily_runner"]
    if game_date:
        cmd.extend(["--date", game_date])
    if skip_health:
        cmd.append("--skip-health")
    if grade:
        cmd.append("--grade-yesterday")

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=sport_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        output = result.stdout + result.stderr

        # Detect no-games
        for pattern in NO_GAMES_PATTERNS:
            if re.search(pattern, output, re.IGNORECASE):
                return {
                    "sport": sport["name"],
                    "status": "no_games",
                    "bets": 0,
                    "duration": elapsed,
                    "output": output,
                    "error": "",
                }

        # Detect bet count
        bets = 0
        for m in BETS_PATTERN.finditer(output):
            bets += int(m.group(1))

        if result.returncode != 0:
            return {
                "sport": sport["name"],
                "status": "failed",
                "bets": 0,
                "duration": elapsed,
                "output": output,
                "error": f"Exit code {result.returncode}",
            }

        return {
            "sport": sport["name"],
            "status": "success",
            "bets": bets,
            "duration": elapsed,
            "output": output,
            "error": "",
        }

    except subprocess.TimeoutExpired:
        return {
            "sport": sport["name"],
            "status": "timeout",
            "bets": 0,
            "duration": time.time() - t0,
            "output": "",
            "error": f"Timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "sport": sport["name"],
            "status": "failed",
            "bets": 0,
            "duration": time.time() - t0,
            "output": "",
            "error": str(e),
        }


def _fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def _status_display(result):
    status = result["status"]
    if status == "success":
        n = result["bets"]
        return f"{n} bet{'s' if n != 1 else ''}" if n > 0 else "0 bets"
    if status == "no_games":
        return "No games"
    if status == "timeout":
        return "TIMEOUT"
    if status == "missing":
        return "MISSING"
    return "FAILED"


def _print_summary(results, game_date):
    sep = "=" * 60
    dash = "\u2500"
    click.echo(f"\n{sep}")
    click.echo(f"  MIROFISH DAILY SUMMARY \u2014 {game_date}")
    click.echo(sep)
    click.echo(f"  {'Sport':<12} {'Status':<14} {'Bets':<8} {'Time'}")
    click.echo(f"  {dash * 12} {dash * 14} {dash * 8} {dash * 8}")

    for r in results:
        bets_col = str(r["bets"]) if r["bets"] > 0 else "\u2014"
        click.echo(
            f"  {r['sport']:<12} {_status_display(r):<14} {bets_col:<8} {_fmt_duration(r['duration'])}"
        )

    click.echo(f"  {dash * 44}")
    total_bets = sum(r["bets"] for r in results)
    active_sports = sum(1 for r in results if r["status"] == "success" and r["bets"] > 0)
    click.echo(f"  Total: {total_bets} bets across {active_sports} sports")
    click.echo(f"{'=' * 60}\n")


@click.command()
@click.option("--date", "game_date", default=None, help="Override game date (YYYY-MM-DD)")
@click.option("--sports", default=None, help="Comma-separated sport filter (e.g. nba,mlb,soccer)")
@click.option("--parallel", default=3, help="Max concurrent sports (default 3)")
@click.option("--skip-health", is_flag=True, help="Skip API health checks")
@click.option("--no-grade", is_flag=True, help="Skip grading yesterday's results")
@click.option("--verbose", is_flag=True, help="Show full output from each sport")
def main(game_date, sports, parallel, skip_health, no_grade, verbose):
    """Run MiroFish prediction pipelines for all sports."""
    if game_date is None:
        game_date = date.today().isoformat()

    now = datetime.now().strftime("%I:%M %p")
    click.echo(f"\n{'=' * 60}")
    click.echo(f"  MIROFISH DAILY ORCHESTRATOR \u2014 {game_date} ({now})")
    click.echo(f"{'=' * 60}\n")

    # Filter sports if requested
    active_sports = SPORTS
    if sports:
        requested = {s.strip().lower() for s in sports.split(",")}
        active_sports = [s for s in SPORTS if s["filter"] in requested]
        if not active_sports:
            click.echo(f"No matching sports for: {sports}")
            click.echo(f"Available: {', '.join(s['filter'] for s in SPORTS)}")
            sys.exit(1)

    click.echo(f"  Sports: {', '.join(s['name'] for s in active_sports)}")
    click.echo(f"  Parallel: {parallel}")
    click.echo(f"  Grade yesterday: {'no' if no_grade else 'yes'}")
    click.echo(f"  Health checks: {'skip' if skip_health else 'yes'}")
    click.echo()

    grade = not no_grade
    results = []

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {
            pool.submit(_run_sport, sport, game_date, skip_health, grade): sport
            for sport in active_sports
        }

        for future in as_completed(futures):
            sport = futures[future]
            result = future.result()
            results.append(result)

            # Stream progress
            icon = "\u2713" if result["status"] in ("success", "no_games") else "\u2717"
            click.echo(
                f"  [{icon}] {result['sport']:<12} {_status_display(result):<14} ({_fmt_duration(result['duration'])})"
            )

            if verbose and result["output"]:
                click.echo(f"\n--- {result['sport']} output ---")
                click.echo(result["output"])
                click.echo(f"--- end {result['sport']} ---\n")

            if result["error"] and result["status"] not in ("no_games",):
                click.echo(f"    Error: {result['error']}")

    # Sort results by sport registry order
    sport_order = {s["name"]: i for i, s in enumerate(SPORTS)}
    results.sort(key=lambda r: sport_order.get(r["sport"], 99))

    _print_summary(results, game_date)

    # Exit 1 if any sport failed
    if any(r["status"] in ("failed", "timeout") for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
