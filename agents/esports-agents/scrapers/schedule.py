"""Unified match schedule aggregator across all esports games."""
import logging
from config import SUPPORTED_GAMES, MAX_TIER
from games import get_game

log = logging.getLogger(__name__)


def get_todays_matches(game_keys: list[str] = None) -> list[dict]:
    """Get all upcoming matches across games, filtered by tier.

    Only returns Tier 1 and Tier 2 events.

    Args:
        game_keys: List of game keys to fetch. Defaults to SUPPORTED_GAMES.

    Returns:
        List of match dicts, each with a 'game_key' field added, sorted by date.
    """
    if game_keys is None:
        game_keys = SUPPORTED_GAMES

    all_matches = []
    for game_key in game_keys:
        try:
            game = get_game(game_key)
            matches = game.scrapers.fetch_upcoming_matches()
            # Filter to Tier 1 and Tier 2
            for match in matches:
                tier = match.get("tier", 3)
                if tier <= MAX_TIER:
                    match["game_key"] = game_key
                    all_matches.append(match)
                else:
                    log.debug(f"[schedule] Skipping tier {tier} match: {match.get('team_a')} vs {match.get('team_b')}")
        except Exception as e:
            log.warning(f"[schedule] Failed to fetch matches for {game_key}: {e}")

    # Sort by date
    all_matches.sort(key=lambda m: m.get("date", ""))
    log.info(f"[schedule] {len(all_matches)} matches across {len(game_keys)} games")
    return all_matches
