"""Event-driven tennis pipeline trigger.

Intended to run hourly (via launchd). On each tick:
  1. Fetch ATP + WTA upcoming schedules.
  2. Find match dates with at least one commence_time in [now + 7h, now + 9h].
  3. Skip dates we already analyzed (dedup via `data/pipeline_runs.json`).
  4. For each remaining date, run the pipeline for that specific date and record.

The goal: catch each day's slate ~8h before the first match, regardless of tour
timezone (Madrid 11:00Z, Australia 00:00Z, US 16:00Z all get handled).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("mirofish.pipeline_tick")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_LOG = REPO_ROOT / "data" / "pipeline_runs.json"
DEFAULT_LOCK = REPO_ROOT / "data" / "pipeline_tick.lock"


def _parse_commence(m: dict) -> datetime | None:
    """Accepts pre-parsed `commence_iso` or `start_time` ("YYYY-MM-DD HH:MM" UTC)."""
    raw = m.get("commence_iso") or m.get("start_time") or ""
    raw = str(raw).strip()
    if not raw or raw.lower() == "nan":
        return None
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def find_dates_in_window(matches: list[dict],
                         now: datetime,
                         window_start_hours: float = 7,
                         window_end_hours: float = 9) -> list[str]:
    """Return distinct match dates (ISO) with ≥1 match commencing in [now+start, now+end]."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    lo = now + timedelta(hours=window_start_hours)
    hi = now + timedelta(hours=window_end_hours)
    dates: set[str] = set()
    for m in matches:
        ct = _parse_commence(m)
        if ct is None:
            continue
        if lo <= ct <= hi:
            dates.add(ct.date().isoformat())
    return sorted(dates)


def _load_runs_log(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_runs_log(path: str, log: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, path)


def filter_already_run(dates: list[str], runs_log_path: str = None) -> list[str]:
    path = runs_log_path or str(DEFAULT_RUNS_LOG)
    log = _load_runs_log(path)
    return [d for d in dates if d not in log]


def record_run(game_date: str, runs_log_path: str = None) -> None:
    path = runs_log_path or str(DEFAULT_RUNS_LOG)
    log = _load_runs_log(path)
    log[game_date] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_runs_log(path, log)


def _acquire_lock(lock_path: Path) -> bool:
    """Non-blocking lock: returns True if we acquired, False if already held."""
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _fetch_all_upcoming() -> list[dict]:
    from scrapers.schedule import get_upcoming_matches
    combined: list[dict] = []
    for t in ("atp", "wta"):
        try:
            for m in get_upcoming_matches(t, hours=48):
                m2 = dict(m)
                m2.setdefault("tour", t)
                combined.append(m2)
        except Exception as e:
            logger.warning("fetch %s upcoming failed: %s", t, e)
    return combined


def main() -> int:
    # Must run from repo root so main.py's relative paths resolve.
    os.chdir(REPO_ROOT)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if not _acquire_lock(DEFAULT_LOCK):
        logger.info("Another tick is running — exiting.")
        return 0

    try:
        now = datetime.now(timezone.utc)
        upcoming = _fetch_all_upcoming()
        logger.info("Tick at %s: %d upcoming matches", now.isoformat(), len(upcoming))

        dates = find_dates_in_window(upcoming, now=now,
                                     window_start_hours=7, window_end_hours=9)
        pending = filter_already_run(dates)
        if not pending:
            logger.info("No new dates to analyze (in-window=%s, pending=[]).", dates)
            return 0

        for d in pending:
            logger.info("Dispatching daily pipeline for %s", d)
            t0 = time.time()
            cmd = [sys.executable, "-u", "-m", "agents.daily_runner",
                   "--date", d, "--skip-health"]
            try:
                result = subprocess.run(cmd, timeout=3600)
                elapsed = time.time() - t0
                if result.returncode == 0:
                    record_run(d)
                    logger.info("Pipeline %s OK in %.0fs", d, elapsed)
                else:
                    logger.error("Pipeline %s exited %d after %.0fs",
                                 d, result.returncode, elapsed)
            except subprocess.TimeoutExpired:
                logger.error("Pipeline %s timed out after 1h", d)
            except Exception as e:
                logger.exception("Pipeline %s crashed: %s", d, e)
        return 0
    finally:
        _release_lock(DEFAULT_LOCK)


if __name__ == "__main__":
    raise SystemExit(main())
