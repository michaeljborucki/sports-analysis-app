"""Daily runner agent: orchestrates the full pipeline with retries."""
import logging
import click
import time
import subprocess
import sys
from datetime import date, datetime

from agents.health_check import run_health_check
from agents.bet_card import (
    format_bet_card,
    format_bet_card_window,
    save_bet_card,
    save_bet_card_window,
)

logger = logging.getLogger("mirofish.daily_runner")


PIPELINE_TIMEOUT_SECONDS = 7200  # 2h. Safety net only — per-match timeout inside ``main.py daily`` is the
                                  # real gate. With that working correctly (see ensemble/orchestrator.py
                                  # cancel_futures fix), a 10-match slate at GAME_TIMEOUT=300 is bounded at
                                  # ~50 min; 2h gives comfortable headroom for rare multi-retry scenarios.


def _rankings_refresh_due(tours: list[str]) -> bool:
    """True if today is Monday OR any tour's rankings file is > 7 days old OR missing."""
    import os
    from config import SACKMANN_LOCAL_DIR
    if date.today().weekday() == 0:  # Monday
        return True
    for tour in tours:
        prefix = "atp" if tour == "atp" else "wta"
        path = os.path.join(SACKMANN_LOCAL_DIR, tour, f"{prefix}_rankings_current.csv")
        if not os.path.exists(path):
            return True
        age_days = (time.time() - os.path.getmtime(path)) / 86400
        if age_days > 7:
            return True
    return False


def run_pipeline(game_date: str | None, tour: str = "atp", max_retries: int = 2,
                 force_resim: bool = False) -> bool:
    """Run the daily pipeline with retry logic. Streams stdout so hangs are visible.

    Uses `-u` to force unbuffered Python output and streams line-by-line rather than
    capturing. If the subprocess doesn't exit within PIPELINE_TIMEOUT_SECONDS, it's killed.
    """
    scope = game_date if game_date else "next 24h"
    logger.info("Starting pipeline for %s %s (max_retries=%d, force_resim=%s)",
                tour.upper(), scope, max_retries, force_resim)
    cmd = [sys.executable, "-u", "main.py", "daily", "--tour", tour]
    if game_date:
        cmd.extend(["--date", game_date])
    if force_resim:
        cmd.append("--force-resim")

    for attempt in range(max_retries + 1):
        if attempt > 0:
            click.echo(f"\n  Retry {attempt}/{max_retries}...")
            time.sleep(10)
        t0 = time.time()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        timed_out = False
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if time.time() - t0 > PIPELINE_TIMEOUT_SECONDS:
                    timed_out = True
                    break
                click.echo(line.rstrip("\n"))
            if timed_out:
                proc.kill()
                proc.wait(timeout=10)
                click.echo(f"  Pipeline timed out after {PIPELINE_TIMEOUT_SECONDS}s (killed)")
                continue
            proc.wait(timeout=30)
        except Exception as e:
            click.echo(f"  Pipeline error: {e}")
            try:
                proc.kill()
            except Exception:
                pass
            continue
        elapsed = time.time() - t0
        if proc.returncode == 0:
            logger.info("Pipeline succeeded in %.0fs (attempt %d)", elapsed, attempt + 1)
            return True
        click.echo(f"  Pipeline exited with code {proc.returncode}")
    return False


def run_results(game_date: str, tour: str = "atp") -> None:
    """Run the results grader via `main.py results` so Discord grade + season notifies fire."""
    try:
        result = subprocess.run(
            [sys.executable, "main.py", "results", "--date", game_date, "--tour", tour],
            capture_output=True, text=True, timeout=180,
        )
        click.echo(result.stdout)
        if result.stderr:
            click.echo(result.stderr)
    except Exception as e:
        click.echo(f"  Results grader error: {e}")


@click.command()
@click.option("--date", "game_date", default=None, help="Calendar date (YYYY-MM-DD). Omit to use next 24h window.")
@click.option("--tour", default="both", type=click.Choice(["atp", "wta", "both"]))
@click.option("--skip-health", is_flag=True)
@click.option("--grade-yesterday", is_flag=True)
@click.option("--force-resim", is_flag=True,
              help="Bypass the per-day sim cache and re-run the full ensemble. "
                   "Use when briefings now include fresh round results that the "
                   "cached predictions don't reflect (e.g. tournament rounds rolling).")
def main(game_date, tour, skip_health, grade_yesterday, force_resim):
    """Full daily workflow: health check -> grade yesterday -> run pipeline -> bet card."""
    scope_label = game_date if game_date else "next 24h"

    now = datetime.now().strftime("%I:%M %p")
    click.echo(f"\n{'='*60}")
    click.echo(f"  MIROFISH TENNIS DAILY RUNNER — {scope_label} ({now})")
    click.echo(f"{'='*60}\n")

    if not skip_health:
        click.echo("[1] Running health check...")
        healthy = run_health_check()
        if not healthy:
            click.echo("\nAborting — fix critical issues first.")
            return
        click.echo()

    # Sync yesterday's finished matches into the local Sackmann archive so
    # today's Elo + records + form are fresh. Idempotent — safe to rerun.
    # Also refresh rankings once a week (or if stale > 7d).
    from datetime import timedelta
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    click.echo(f"[1.5] Syncing yesterday's matches ({yesterday_iso}) to local archive...")
    try:
        from scrapers.sackmann_sync import sync_matches_day, sync_rankings
        sync_tours = ["atp", "wta"] if tour == "both" else [tour]
        for t in sync_tours:
            try:
                n = sync_matches_day(yesterday_iso, t)
                click.echo(f"  {t.upper()}: {n} new rows appended")
            except Exception as e:
                click.echo(f"  {t.upper()}: sync failed ({e}), continuing")

        # Rankings refresh on Monday or when stale > 7 days
        if _rankings_refresh_due(sync_tours):
            for t in sync_tours:
                try:
                    n = sync_rankings(t)
                    click.echo(f"  {t.upper()} rankings: {n} players refreshed")
                except Exception as e:
                    click.echo(f"  {t.upper()} rankings: refresh failed ({e}), continuing")
    except ImportError:
        click.echo("  sackmann_sync not available, skipping")
    click.echo()

    if grade_yesterday:
        yesterday = yesterday_iso
        click.echo(f"[2] Grading yesterday's results ({yesterday})...")
        tours = ["atp", "wta"] if tour == "both" else [tour]
        # Capture consensus closing lines BEFORE grading so update_result can populate CLV.
        try:
            from scrapers.closing_lines import capture_closing_lines_for_date
            for t in tours:
                s = capture_closing_lines_for_date(yesterday, tour=t)
                click.echo(
                    f"  CLV capture {t.upper()}: {s['captured_rows']} rows / "
                    f"{s['captured_games']} matches ({s['snapshot_calls']} API calls)"
                )
        except Exception as e:
            click.echo(f"  CLV capture failed (continuing): {e}")
        for t in tours:
            run_results(yesterday, t)
        # Back-apply CLV for any bets that graded before the close was captured.
        try:
            import subprocess, sys
            subprocess.run(
                [sys.executable, "main.py", "clv-apply", "--date", yesterday],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:
            click.echo(f"  CLV apply failed (continuing): {e}")
        click.echo()

    # Single subprocess call — when tour=="both", main.py daily merges ATP+WTA
    # into one time-sorted queue so earliest-starting matches get simulated
    # first regardless of tour. Previously this loop ran per-tour subprocesses
    # sequentially, which could process a late-afternoon ATP match ahead of a
    # morning WTA match and push us post-market on the WTA side.
    tours_label = "ATP+WTA" if tour == "both" else tour.upper()
    resim_tag = " [FORCE-RESIM]" if force_resim else ""
    click.echo(f"[3] Running {tours_label} prediction pipeline for {scope_label}{resim_tag}...")
    run_pipeline(game_date, tour, force_resim=force_resim)

    click.echo(f"\n[4] Generating bet card...")
    if game_date:
        click.echo(format_bet_card(game_date))
        txt_path, json_path = save_bet_card(game_date)
    else:
        from datetime import timedelta
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        click.echo(format_bet_card_window(today, tomorrow))
        txt_path, json_path = save_bet_card_window(today, tomorrow)
    click.echo(f"Saved: {txt_path}")
    click.echo(f"Saved: {json_path}")
    click.echo("Done. Good luck.")


if __name__ == "__main__":
    main()
