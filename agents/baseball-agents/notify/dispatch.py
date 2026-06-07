"""End-to-end notification dispatch: load config, filter bets, send to Discord.

Tracks already-sent bets in `data/notifications_sent.json` to keep the
"set and forget" recurring schedule from spamming the same picks every run.
"""
import json
import logging
import os
import threading
from datetime import date as dt_date

from config import DATA_DIR
from tracker import load_bets
from notify.config import load_alerts_config, discord_enabled
from notify.format import filter_bets, split_to_messages, DISCORD_MAX
from notify.discord import send_discord

logger = logging.getLogger("mirofish.notify.dispatch")

SENT_LOG_PATH = os.path.join(DATA_DIR, "notifications_sent.json")
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


def _bet_key(bet: dict) -> str:
    return f"{bet['game']}|{bet['bet_type']}|{bet['side']}"


def send_notifications(game_date: str | None = None,
                       force: bool = False,
                       dry_run: bool = False,
                       config_path: str | None = None) -> dict:
    """Filter today's bets, format, and dispatch to Discord.

    Args:
        game_date: defaults to today
        force: if True, re-send bets already in the sent log
        dry_run: if True, print messages to stdout instead of sending
        config_path: override default alerts_config.json location

    Returns summary dict {bets_total, bets_filtered, bets_new, sent}.
    """
    if game_date is None:
        game_date = dt_date.today().isoformat()

    cfg = load_alerts_config(config_path)
    allowed = cfg.get("bet_types", [])
    min_edge = float(cfg.get("min_edge_pct", 0.0))
    min_kelly = float(cfg.get("min_kelly_pct", 0.0))

    df = load_bets()
    day = df[df["date"] == game_date]
    bets = day.to_dict(orient="records")

    filtered = filter_bets(bets, allowed, min_edge=min_edge, min_kelly=min_kelly)

    with _lock:
        sent_log = _load_sent_log()
        already_sent = set(sent_log.get(game_date, []))

    if force:
        new_bets = filtered
    else:
        new_bets = [b for b in filtered if _bet_key(b) not in already_sent]

    summary = {
        "bets_total": len(bets),
        "bets_filtered": len(filtered),
        "bets_new": len(new_bets),
        "sent": 0,
        "dry_run": dry_run,
        "discord_enabled": discord_enabled(cfg),
    }

    if not new_bets:
        logger.info("No new bets to send for %s (filtered=%d, already_sent=%d)",
                    game_date, len(filtered), len(already_sent))
        return summary

    msgs = split_to_messages(game_date, new_bets, char_limit=DISCORD_MAX)

    if dry_run:
        print(f"\n========== DISCORD ({len(msgs)} message(s)) ==========")
        for i, m in enumerate(msgs, 1):
            print(f"--- Message {i}/{len(msgs)} ({len(m)} chars) ---\n{m}\n")
        summary["sent"] = len(msgs)
        return summary

    if not discord_enabled(cfg):
        logger.warning("Discord not enabled in alerts config — nothing to send")
        return summary

    sent = send_discord(cfg["discord"]["webhook_url"], msgs)
    summary["sent"] = sent
    logger.info("Discord: sent %d/%d message(s)", sent, len(msgs))

    if sent > 0:
        with _lock:
            sent_log = _load_sent_log()
            already = set(sent_log.get(game_date, []))
            for b in new_bets:
                already.add(_bet_key(b))
            sent_log[game_date] = sorted(already)
            _save_sent_log(sent_log)

    return summary
