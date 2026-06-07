"""Esports news and roster context scraper."""
import logging

log = logging.getLogger(__name__)


def fetch_match_context(game_key: str, team_a: str, team_b: str) -> dict:
    """Fetch contextual news for a specific esports match.

    Returns roster news, tournament context, narrative, and online/LAN flag.
    In production, this would scrape from Liquipedia, HLTV news, and team socials.
    """
    return {
        "roster_news": {
            "team_a": _get_roster_news(game_key, team_a),
            "team_b": _get_roster_news(game_key, team_b),
        },
        "tournament_context": {
            "stage": "",
            "stakes": "",
            "format": "",
        },
        "narrative": "",
        "online_lan": "unknown",
    }


def _get_roster_news(game_key: str, team_name: str) -> list[str]:
    """Get recent roster news for a team.

    Stub implementation — will be backed by Liquipedia API or HLTV scraping.
    """
    log.debug(f"[news] Fetching roster news for {team_name} ({game_key})")
    return []


def get_injuries(team: str = None) -> list[dict]:
    """Legacy interface — returns empty list.

    Esports doesn't have "injuries" in the traditional sense.
    Roster substitutions are handled via fetch_match_context().
    """
    return []
