"""Fetch NBA injury report."""
import logging
import requests

logger = logging.getLogger("mirofish.scrapers.injuries")


def classify_impact_tier(minutes_per_game: float) -> str:
    """Classify player impact by minutes per game."""
    if minutes_per_game >= 28:
        return "star"
    elif minutes_per_game >= 18:
        return "rotation"
    return "bench"


def get_injuries() -> list[dict]:
    """Fetch current NBA injury report.

    Returns list of dicts with team, player, status, reason, impact_tier.
    """
    try:
        logger.info("Injury report: using stub implementation")
        return []
    except Exception as e:
        logger.error("Failed to fetch injuries: %s", e)
        return []
