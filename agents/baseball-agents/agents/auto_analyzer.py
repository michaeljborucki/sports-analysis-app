"""Auto-trigger the daily pipeline when unanalyzed games approach first pitch.

Logic:
  - Load today's MLB schedule (free MLB Stats API)
  - Load analyzed_games state for today
  - For each scheduled game:
      - Skip if already analyzed
      - Skip if first_pitch is in the past (game started)
      - Skip if first_pitch > ANALYZE_LEAD_MINUTES from now (too early)
  - If any remaining games exist, the user's intent is to screen them NOW —
    launch `python -m agents.daily_runner`.

Intended to be called on a schedule (e.g. every 30 min). Cheap when nothing
is due; spawns the pipeline as a subprocess when action is needed.
"""
import logging
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import click

from agents.analyzed_games import load_analyzed
from scrapers.pitchers import get_probable_starters

logger = logging.getLogger("mirofish.auto_analyzer")

ANALYZE_LEAD_MINUTES = 120  # launch pipeline up to 2h before first pitch


def _games_due_for_analysis(now_utc: datetime | None = None) -> list[dict]:
    """Return scheduled games that are unanalyzed and within ANALYZE_LEAD_MINUTES of first pitch."""
    now_utc = now_utc or datetime.now(timezone.utc)
    eastern_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    games = get_probable_starters(eastern_today)
    analyzed = load_analyzed(eastern_today)

    due = []
    for g in games:
        game_key = f"{g['away_team']}@{g['home_team']}"
        if game_key in analyzed:
            continue

        gd = g.get("game_date") or ""
        if not gd:
            continue
        try:
            first_pitch = datetime.fromisoformat(gd.replace("Z", "+00:00"))
        except ValueError:
            continue

        minutes_to_fp = (first_pitch - now_utc).total_seconds() / 60.0
        if minutes_to_fp <= -5:
            continue  # game has already started (or ended)
        if minutes_to_fp > ANALYZE_LEAD_MINUTES:
            continue  # too early — come back later

        due.append({**g, "minutes_to_fp": minutes_to_fp, "game_key": game_key})

    return due


def _has_future_unanalyzed_games(now_utc: datetime | None = None) -> bool:
    """True if any of today's unanalyzed games still have first_pitch in the future (T-5 buffer).

    When False, no further work this day — auto-analyzer can shut off.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    eastern_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    games = get_probable_starters(eastern_today)
    analyzed = load_analyzed(eastern_today)

    for g in games:
        game_key = f"{g['away_team']}@{g['home_team']}"
        if game_key in analyzed:
            continue
        gd = g.get("game_date") or ""
        if not gd:
            continue
        try:
            first_pitch = datetime.fromisoformat(gd.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (first_pitch - now_utc).total_seconds() / 60.0 > -5:
            return True
    return False


@click.command()
@click.option("--dry-run", is_flag=True, help="Report what would be launched without running the pipeline")
def main(dry_run):
    """Check schedule + state and run the daily pipeline if any games are due."""
    due = _games_due_for_analysis()

    if not due:
        if not _has_future_unanalyzed_games():
            click.echo("auto-analyzer: monitoring complete for today — all games analyzed (or started).")
            return
        click.echo("auto-analyzer: no games due within 2h window. Standing by.")
        return

    due_desc = ", ".join(f"{g['game_key']} (T-{g['minutes_to_fp']:.0f}m)" for g in due)
    click.echo(f"auto-analyzer: {len(due)} games due: {due_desc}")

    if dry_run:
        click.echo("  --dry-run: skipping pipeline launch")
        return

    click.echo("  launching daily pipeline...")
    logger.info("auto-analyzer launching pipeline for %d due games", len(due))
    result = subprocess.run([sys.executable, "-m", "agents.daily_runner"])
    click.echo(f"  pipeline exit code: {result.returncode}")


if __name__ == "__main__":
    main()
