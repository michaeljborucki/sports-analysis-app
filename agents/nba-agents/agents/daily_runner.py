"""Daily runner agent: orchestrates the full pipeline with retries and scheduling."""
import asyncio
import click
import time
from datetime import date, datetime

from agents.health_check import run_health_check
from agents.bet_card import format_bet_card


def run_pipeline(game_date: str, max_retries: int = 2) -> bool:
    """Run the daily pipeline with retry logic."""
    from main import run_daily_pipeline

    for attempt in range(max_retries + 1):
        if attempt > 0:
            click.echo(f"\n  Retry {attempt}/{max_retries}...")
            time.sleep(10)
        try:
            total_bets = asyncio.run(run_daily_pipeline(game_date))
            click.echo(f"  Pipeline complete: {total_bets} bets logged")
            return True
        except Exception as e:
            click.echo(f"  Pipeline error: {e}")

    return False


def run_results(game_date: str) -> None:
    """Run the results grader for a given date."""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "agents.results_grader", "--date", game_date],
            capture_output=True,
            text=True,
            timeout=120,
        )
        click.echo(result.stdout)
        if result.stderr:
            click.echo(result.stderr)
    except Exception as e:
        click.echo(f"  Results grader error: {e}")


@click.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--skip-health", is_flag=True, help="Skip health check")
@click.option("--grade-yesterday", is_flag=True, help="Also grade yesterday's results")
def main(game_date, skip_health, grade_yesterday):
    """Full daily workflow: health check -> grade yesterday -> run pipeline -> bet card."""
    if game_date is None:
        game_date = date.today().isoformat()

    now = datetime.now().strftime("%I:%M %p")
    click.echo(f"\n{'='*60}")
    click.echo(f"  MIROFISH DAILY RUNNER — {game_date} ({now})")
    click.echo(f"{'='*60}\n")

    # Step 1: Health check
    if not skip_health:
        click.echo("[1] Running health check...")
        healthy = run_health_check()
        if not healthy:
            click.echo("\nAborting — fix critical issues first.")
            return
        click.echo()

    # Step 2: Grade yesterday's results (optional)
    if grade_yesterday:
        from datetime import timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        click.echo(f"[2] Grading yesterday's results ({yesterday})...")
        run_results(yesterday)
        click.echo()

    # Step 3: Run pipeline
    click.echo(f"[3] Running prediction pipeline for {game_date}...")
    success = run_pipeline(game_date)

    if not success:
        click.echo("\nPipeline failed after retries. Check logs.")
        return

    # Step 4: Print bet card
    click.echo(f"\n[4] Generating bet card...")
    click.echo(format_bet_card(game_date))

    click.echo("Done. Good luck today.")


if __name__ == "__main__":
    main()
