"""Fetch NCAAB injury reports (best-effort -- NCAA has no mandatory reporting)."""
import requests
import logging
from config import ESPN_CBB_BASE

logger = logging.getLogger("mirofish.scrapers.injuries")


def get_ncaab_injuries(team_id: str = None) -> list[dict]:
    """Get injury reports for a team. Returns list of injury dicts.

    NOTE: NCAA has no mandatory injury reporting. Data may be incomplete.
    """
    if not team_id:
        return []

    injuries = []

    # Try ESPN injuries endpoint
    try:
        url = f"{ESPN_CBB_BASE}/teams/{team_id}/injuries"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("injuries", []):
                for entry in item.get("injuries", []):
                    athlete = entry.get("athlete", {})
                    injuries.append({
                        "player": athlete.get("displayName", "Unknown"),
                        "status": entry.get("status", "unknown"),
                        "detail": entry.get("longComment", entry.get("shortComment", "")),
                        "team": team_id,
                    })
    except Exception as e:
        logger.debug("ESPN injuries endpoint failed for team %s: %s", team_id, e)

    if not injuries:
        logger.debug("No injuries found for team %s (NCAA has no mandatory reporting)", team_id)

    return injuries
