"""Briefing dispatcher — routes to game-specific briefing builder."""
import logging
from games import get_game

logger = logging.getLogger("mirofish.briefing")


def build_briefing(match_data: dict, game_key: str) -> str:
    """Build a briefing by dispatching to the appropriate game module.

    Args:
        match_data: Game-specific match data dict.
        game_key: Registry key for the game (e.g. "cs2").

    Returns:
        Formatted briefing string suitable for LLM input.
    """
    game = get_game(game_key)
    return game.briefing.build_briefing(match_data)
