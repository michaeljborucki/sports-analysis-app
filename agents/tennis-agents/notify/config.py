"""Alerts configuration: which bet types to send and Discord webhook config.

Config lives at data/alerts_config.json. The webhook URL is referenced via
${DISCORD_WEBHOOK_URL} so the file is safe to commit without leaking secrets.
"""
import json
import logging
import os
import re

from config import DATA_DIR

logger = logging.getLogger("mirofish.notify")

ALERTS_CONFIG_PATH = os.path.join(DATA_DIR, "alerts_config.json")

DEFAULT_BET_TYPES = ["moneyline", "game_handicap", "total_games"]

DEFAULT_CONFIG = {
    "discord": {
        "enabled": False,
        "webhook_url": "${DISCORD_WEBHOOK_URL}",
    },
    "discord_grades": {
        "enabled": False,
        "webhook_url": "${DISCORD_GRADES_WEBHOOK_URL}",
    },
    "discord_summary": {
        "enabled": False,
        "webhook_url": "${DISCORD_SUMMARY_WEBHOOK_URL}",
    },
    "discord_season": {
        "enabled": False,
        "webhook_url": "${DISCORD_SEASON_WEBHOOK_URL}",
    },
    "bet_types": DEFAULT_BET_TYPES,
    "min_edge_pct": 0.0,
    "min_kelly_pct": 0.0,
}

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _resolve_env(value):
    if not isinstance(value, str):
        return value
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _resolve_recursive(obj):
    if isinstance(obj, dict):
        return {k: _resolve_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_recursive(v) for v in obj]
    return _resolve_env(obj)


def write_default_config(path: str = ALERTS_CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    logger.info("Wrote default alerts config to %s", path)


def load_alerts_config(path: str | None = None) -> dict:
    path = path or ALERTS_CONFIG_PATH
    if not os.path.exists(path):
        write_default_config(path)
    with open(path) as f:
        raw = json.load(f)
    return _resolve_recursive(raw)


def discord_enabled(config: dict) -> bool:
    d = config.get("discord", {})
    return bool(d.get("enabled") and d.get("webhook_url"))


def discord_grades_enabled(config: dict) -> bool:
    d = config.get("discord_grades", {})
    return bool(d.get("enabled") and d.get("webhook_url"))


def discord_summary_enabled(config: dict) -> bool:
    d = config.get("discord_summary", {})
    return bool(d.get("enabled") and d.get("webhook_url"))


def discord_season_enabled(config: dict) -> bool:
    d = config.get("discord_season", {})
    return bool(d.get("enabled") and d.get("webhook_url"))
