"""Post daily grading results to two dedicated Discord channels.

Two channels, both driven by the same graded-bet list:
  - `discord_grades`  — game-by-game code blocks, no summary header.
  - `discord_summary` — single-message daily record + per-bet-type breakdown.

Auto-fires from the results grader, subject to two rules:
  1. Don't post for a `game_date` equal to (or after) today — results are
     only finalized the next morning, so same-day grading shouldn't alert.
  2. Regrade flows must not re-post. Once a channel has been posted for a
     date, it stays in the sent log keyed on channel-per-date and requires
     `force=True` to re-send.
"""
import json
import logging
import os
import threading
from datetime import date as dt_date

from config import DATA_DIR
from tracker import load_bets
from notify.config import (
    load_alerts_config,
    discord_grades_enabled,
    discord_summary_enabled,
)
from notify.format import (
    split_grade_blocks,
    format_grade_header,
    DISCORD_MAX,
)
from notify.discord import send_discord

logger = logging.getLogger("mirofish.notify.grades")

SENT_LOG_PATH = os.path.join(DATA_DIR, "grade_notifications_sent.json")
_lock = threading.Lock()


def _load_sent_log() -> dict:
    if not os.path.exists(SENT_LOG_PATH):
        return {}
    try:
        with open(SENT_LOG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sent_log(log: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = f"{SENT_LOG_PATH}.tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, SENT_LOG_PATH)


def _date_entry(sent_log: dict, game_date: str) -> dict:
    """Return (and normalize) the per-channel sent record for `game_date`.

    Old log format stored a bare `true` per date; migrate that to
    `{"grades": true, "summary": false}` so existing-channel dedup survives
    but the new summary channel can still be posted.
    """
    entry = sent_log.get(game_date, {})
    if isinstance(entry, bool):
        entry = {"grades": entry, "summary": False}
    return entry


def send_grade_notifications(game_date: str,
                             force: bool = False,
                             dry_run: bool = False,
                             config_path: str | None = None) -> dict:
    """Post graded bet results to the grades + summary Discord channels.

    Summary keys:
        bets_total, bets_graded, bets_filtered,
        grades_sent, summary_sent, skipped_reason.
    """
    cfg = load_alerts_config(config_path)
    today = dt_date.today().isoformat()

    summary = {
        "bets_total": 0,
        "bets_graded": 0,
        "bets_filtered": 0,
        "grades_sent": 0,
        "summary_sent": 0,
        "dry_run": dry_run,
        "grades_enabled": discord_grades_enabled(cfg),
        "summary_enabled": discord_summary_enabled(cfg),
        "skipped_reason": None,
    }

    if game_date >= today:
        summary["skipped_reason"] = "game_date_not_in_past"
        logger.info("Skipping grade notify: %s is not before today (%s)", game_date, today)
        return summary

    df = load_bets()
    day = df[df["date"] == game_date]
    summary["bets_total"] = len(day)
    graded = day[day["result"].isin(["W", "L", "P"])]
    summary["bets_graded"] = len(graded)

    # Grades + summary intentionally show every market — picks alerts use
    # cfg["bet_types"] to be selective, but the daily record shows the full
    # picture. (2026-04-29 split.)
    graded_picks = graded.to_dict(orient="records")
    summary["bets_filtered"] = len(graded_picks)

    if not graded_picks:
        logger.info("No graded picks for %s in configured bet types", game_date)
        return summary

    with _lock:
        sent_log = _load_sent_log()
        entry = _date_entry(sent_log, game_date)

    grades_done = bool(entry.get("grades")) and not force
    summary_done = bool(entry.get("summary")) and not force

    game_block_msgs = split_grade_blocks(game_date, graded_picks, char_limit=DISCORD_MAX)
    summary_msg = format_grade_header(game_date, graded_picks)

    if dry_run:
        print(f"\n========== GRADES DISCORD ({len(game_block_msgs)} message(s)) ==========")
        for i, m in enumerate(game_block_msgs, 1):
            print(f"--- Message {i}/{len(game_block_msgs)} ({len(m)} chars) ---\n{m}\n")
        print(f"\n========== SUMMARY DISCORD (1 message) ==========")
        print(f"--- ({len(summary_msg)} chars) ---\n{summary_msg}\n")
        summary["grades_sent"] = len(game_block_msgs)
        summary["summary_sent"] = 1
        return summary

    if summary["grades_enabled"] and not grades_done:
        n = send_discord(cfg["discord_grades"]["webhook_url"], game_block_msgs)
        summary["grades_sent"] = n
        logger.info("Grades channel: sent %d/%d message(s)", n, len(game_block_msgs))
        if n > 0:
            entry["grades"] = True

    if summary["summary_enabled"] and not summary_done:
        n = send_discord(cfg["discord_summary"]["webhook_url"], [summary_msg])
        summary["summary_sent"] = n
        logger.info("Summary channel: sent %d/1 message", n)
        if n > 0:
            entry["summary"] = True

    if not summary["grades_enabled"] and not summary["summary_enabled"]:
        summary["skipped_reason"] = "webhooks_disabled"
    elif grades_done and summary_done:
        summary["skipped_reason"] = "already_sent"

    if summary["grades_sent"] > 0 or summary["summary_sent"] > 0:
        with _lock:
            sent_log = _load_sent_log()
            current = _date_entry(sent_log, game_date)
            current["grades"] = current.get("grades") or entry.get("grades", False)
            current["summary"] = current.get("summary") or entry.get("summary", False)
            sent_log[game_date] = current
            _save_sent_log(sent_log)

    return summary
