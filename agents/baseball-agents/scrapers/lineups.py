import requests
from config import MLB_API_BASE, TEAM_NAME_TO_ABBREV


def get_confirmed_lineups(game_date: str) -> dict:
    """Fetch confirmed lineups from MLB Stats API.

    Returns dict keyed by team abbreviation with lineup data.
    """
    url = f"{MLB_API_BASE}/schedule"
    params = {
        "date": game_date,
        "sportId": 1,
        "hydrate": "lineups",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    result = {}
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            away_name = game["teams"]["away"]["team"]["name"]
            home_name = game["teams"]["home"]["team"]["name"]
            away = TEAM_NAME_TO_ABBREV.get(away_name, away_name)
            home = TEAM_NAME_TO_ABBREV.get(home_name, home_name)

            lineups = game.get("lineups", {})
            away_players = lineups.get("awayPlayers", [])
            home_players = lineups.get("homePlayers", [])

            result[away] = {
                "confirmed": len(away_players) > 0,
                "lineup": [
                    {
                        "id": p["id"],
                        "name": p["fullName"],
                        "position": p.get("primaryPosition", {}).get("abbreviation", ""),
                        "bats": p.get("batSide", {}).get("code", ""),
                    }
                    for p in away_players
                ],
            }

            result[home] = {
                "confirmed": len(home_players) > 0,
                "lineup": [
                    {
                        "id": p["id"],
                        "name": p["fullName"],
                        "position": p.get("primaryPosition", {}).get("abbreviation", ""),
                        "bats": p.get("batSide", {}).get("code", ""),
                    }
                    for p in home_players
                ],
            }

    return result
