"""Discord alerting for daily soccer bet picks.

Ported from baseball-agents. Reads `data/alerts_config.json` for bet type
filters + webhook URL. Posts the filtered bet card as Discord messages.
"""
from notify.dispatch import send_notifications
from notify.config import load_alerts_config, DEFAULT_BET_TYPES

__all__ = ["send_notifications", "load_alerts_config", "DEFAULT_BET_TYPES"]
