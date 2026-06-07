"""Daily grader — fires once in the morning (4 AM America/Denver by default).

Grades STRICTLY yesterday's bets. If a match started early today (e.g. 2 AM local)
and is already complete, it is NOT graded here — it gets picked up tomorrow's run.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("mirofish.grade_tick")

REPO_ROOT = Path(__file__).resolve().parent.parent


def compute_grade_date(now_local: datetime) -> str:
    """Return ISO date for yesterday-in-local-time. Never returns today."""
    yesterday = now_local.date() - timedelta(days=1)
    return yesterday.isoformat()


def ensure_strictly_past(target_date: str, now_local: datetime) -> None:
    """Raise ValueError if target_date is today or in the future (defense-in-depth)."""
    today_iso = now_local.date().isoformat()
    if target_date >= today_iso:
        raise ValueError(
            f"Refusing to grade {target_date}: must be strictly before local today "
            f"({today_iso}). A match on today's date is never eligible for grading."
        )


def main() -> int:
    os.chdir(REPO_ROOT)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    now_local = datetime.now()
    target = compute_grade_date(now_local)
    ensure_strictly_past(target, now_local)

    # CLV capture first so results_grader can populate CLV columns.
    try:
        from scrapers.closing_lines import capture_closing_lines_for_date
        for t in ("atp", "wta"):
            s = capture_closing_lines_for_date(target, tour=t)
            logger.info("CLV capture %s %s: %s", target, t.upper(), s)
    except Exception as e:
        logger.error("CLV capture failed (continuing): %s", e)

    overall = 0
    for t in ("atp", "wta"):
        logger.info("Grading %s %s", target, t.upper())
        cmd = [sys.executable, "main.py", "results", "--date", target, "--tour", t]
        res = subprocess.run(cmd, timeout=300)
        if res.returncode != 0:
            logger.error("results %s %s exited %d", target, t, res.returncode)
            overall = res.returncode

    # Back-apply CLV for any bets that graded before the close was captured this run.
    try:
        subprocess.run(
            [sys.executable, "main.py", "clv-apply", "--date", target],
            timeout=120,
        )
    except Exception as e:
        logger.error("clv-apply failed: %s", e)

    return overall


if __name__ == "__main__":
    raise SystemExit(main())
