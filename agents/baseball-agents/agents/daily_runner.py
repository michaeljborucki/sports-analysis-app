"""Daily runner agent: orchestrates the full pipeline with retries and scheduling."""
import logging
import os
import click
import time
import subprocess
import sys
from datetime import date, datetime

import pandas as pd

from agents.health_check import run_health_check
from agents.bet_card import format_bet_card, write_mainline_bet_card_files

logger = logging.getLogger("mirofish.daily_runner")


def _today() -> date:
    """Indirection for tests to pin the current date."""
    return date.today()


def _pending_past_dates() -> list[str]:
    """Return sorted list of past dates that still have ungraded bets.

    'Past' means strictly before today — same-day bets are deliberately excluded
    (their games may not have finished yet). Results are sorted ascending so the
    grader processes oldest-first.
    """
    from tracker import BETS_CSV
    if not os.path.exists(BETS_CSV):
        return []
    df = pd.read_csv(BETS_CSV)
    if df.empty:
        return []
    today_iso = _today().isoformat()
    pending = df[(~df["result"].isin(["W", "L", "P"])) & (df["date"] < today_iso)]
    return sorted(pending["date"].dropna().unique().tolist())


def run_pipeline(game_date: str, max_retries: int = 2) -> bool:
    """Run the daily pipeline with retry logic."""
    logger.info("Starting pipeline for %s (max_retries=%d)", game_date, max_retries)
    for attempt in range(max_retries + 1):
        if attempt > 0:
            click.echo(f"\n  Retry {attempt}/{max_retries}...")
            logger.info("Pipeline retry %d/%d for %s", attempt, max_retries, game_date)
            time.sleep(10)

        try:
            t0 = time.time()
            result = subprocess.run(
                [sys.executable, "main.py", "daily", "--date", game_date],
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hr outer timeout (per-game timeouts handle hangs)
            )
            elapsed = time.time() - t0
            click.echo(result.stdout)
            if result.stderr:
                click.echo(result.stderr)

            if result.returncode == 0:
                logger.info("Pipeline succeeded in %.0fs (attempt %d)", elapsed, attempt + 1)
                return True
            else:
                click.echo(f"  Pipeline exited with code {result.returncode}")
                logger.warning("Pipeline exited with code %d after %.0fs", result.returncode, elapsed)

        except subprocess.TimeoutExpired:
            click.echo("  Pipeline timed out (20 min)")
            logger.error("Pipeline timed out after 3600s")
        except Exception as e:
            click.echo(f"  Pipeline error: {e}")
            logger.exception("Pipeline error")

    logger.error("Pipeline failed after %d attempts", max_retries + 1)
    return False


def run_results(game_date: str) -> None:
    """Run the results grader for a given date.

    Timeout is a generous upper bound (15 min) meant to catch a true hang, not
    to cap legitimate work. Heavy prop days with historical CLV backfill can
    legitimately take 3-5 minutes.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "agents.results_grader", "--date", game_date],
            capture_output=True,
            text=True,
            timeout=900,
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
    """Full daily workflow: health check → grade yesterday → run pipeline → bet card."""
    if game_date is None:
        game_date = date.today().isoformat()

    now = datetime.now().strftime("%I:%M %p")
    click.echo(f"\n{'='*60}")
    click.echo(f"  DAILY RUNNER — {game_date} ({now})")
    click.echo(f"{'='*60}\n")

    # Step 1: Health check
    if not skip_health:
        click.echo("[1] Running health check...")
        healthy = run_health_check()
        if not healthy:
            click.echo("\nAborting — fix critical issues first.")
            return
        click.echo()

    # Step 2: Grade yesterday's results + sweep any past dates still pending.
    # This catches bets that got stuck because a previous grader run timed out
    # or was never scheduled (e.g., we missed a day).
    if grade_yesterday:
        from datetime import timedelta
        yesterday = (_today() - timedelta(days=1)).isoformat()
        past_pending = _pending_past_dates()
        to_grade = sorted(set(past_pending) | {yesterday})
        click.echo(f"[2] Grading {len(to_grade)} past date(s): {', '.join(to_grade)}")
        for d in to_grade:
            click.echo(f"  → {d}")
            run_results(d)
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

    try:
        txt_path, json_path = write_mainline_bet_card_files(game_date)
        click.echo(f"  Mainline bet card written to {txt_path} and {json_path}")
    except Exception as e:
        click.echo(f"  Failed to write mainline bet card files: {e}")
        logger.exception("write_mainline_bet_card_files failed")

    click.echo("Done. Good luck today.")


if __name__ == "__main__":
    main()
