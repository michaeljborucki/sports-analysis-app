"""Game registry — maps game keys to game-specific modules."""
from games import cs2, lol

GAMES = {
    "cs2": cs2,
    "lol": lol,
}

def get_game(game_key: str):
    """Return game module by key. Each module exposes: config, scrapers, briefing, prompt."""
    return GAMES[game_key]
