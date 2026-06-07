"""Post a rolling season totals summary to a dedicated Discord channel.

Runs at the same point as the grades/summary channels (end of
`main.py results`) so the channel shows the latest record + per-bet-type
breakdown through the graded date. Dedupes per date so repeated runs
don't spam; `force=True` re-posts.
"""
import json
import logging
import os
import threading
from datetime import date as dt_date

from config import DATA_DIR
from tracker import load_bets
from notify.config import load_alerts_config, discord_season_enabled
from notify.format import format_season_summary
from notify.discord import send_discord

logger = logging.getLogger("mirofish.notify.season")

SENT_LOG_PATH = os.path.join(DATA_DIR, "season_notifications_sent.json")
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


def send_season_notification(through_date: str,
                             force: bool = False,
                             dry_run: bool = False,
                             config_path: str | None = None) -> dict:
    """Post one-message season summary aggregated through `through_date`."""
    cfg = load_alerts_config(config_path)
    allowed = set(cfg.get("bet_types", []))
    today = dt_date.today().isoformat()

    summary = {
        "bets_filtered": 0,
        "sent": 0,
        "dry_run": dry_run,
        "enabled": discord_season_enabled(cfg),
        "skipped_reason": None,
    }

    if through_date >= today:
        summary["skipped_reason"] = "through_date_not_in_past"
        logger.info("Skipping season notify: %s is not before today (%s)",
                    through_date, today)
        return summary

    df = load_bets()
    mask = (
        (df["date"] <= through_date)
        & df["bet_type"].isin(allowed)
        & df["result"].isin(["W", "L", "P"])
    )
    graded = df[mask].to_dict(orient="records")
    summary["bets_filtered"] = len(graded)
    msg = format_season_summary(through_date, graded)

    if dry_run:
        print(f"\n========== SEASON DISCORD (1 message, {len(msg)} chars) ==========")
        print(msg)
        summary["sent"] = 1
        return summary

    with _lock:
        sent_log = _load_sent_log()
        already_sent = bool(sent_log.get(through_date))

    if already_sent and not force:
        summary["skipped_reason"] = "already_sent"
        logger.info("Season totals for %s already posted — skipping", through_date)
        return summary

    if not summary["enabled"]:
        summary["skipped_reason"] = "webhook_disabled"
        logger.warning("discord_season not enabled — nothing to send")
        return summary

    sent = send_discord(cfg["discord_season"]["webhook_url"], [msg])
    summary["sent"] = sent
    logger.info("Season channel: sent %d/1 message", sent)

    if sent > 0:
        with _lock:
            sent_log = _load_sent_log()
            sent_log[through_date] = True
            _save_sent_log(sent_log)

    return summary
