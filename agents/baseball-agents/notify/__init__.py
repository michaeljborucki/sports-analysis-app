"""Discord alerting for daily bet picks.

Reads a config file specifying which bet types to include. Posts the filtered
bet card to a Discord webhook as a series of code-block messages (one or
more games per message, chunked to fit Discord's 2000-char limit).
"""
from notify.dispatch import send_notifications
from notify.grades import send_grade_notifications
from notify.season import send_season_notification
from notify.config import load_alerts_config, DEFAULT_BET_TYPES

__all__ = [
    "send_notifications",
    "send_grade_notifications",
    "send_season_notification",
    "load_alerts_config",
    "DEFAULT_BET_TYPES",
]
