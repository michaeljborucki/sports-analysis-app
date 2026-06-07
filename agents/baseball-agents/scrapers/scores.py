"""Pull final scores from MLB Stats API."""
import requests
from datetime import date
from config import MLB_API_BASE, TEAM_NAME_TO_ABBREV


def get_final_scores(game_date: str = None) -> list[dict]:
    """Get final scores for all games on a date.

    Returns list of:
    {
        "away": "BOS", "home": "NYY",
        "away_score": 3, "home_score": 5,
        "away_score_5": 1, "home_score_5": 3,  # first 5 innings
        "status": "Final",
        "game_pk": 12345,
    }
    """
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{MLB_API_BASE}/schedule"
    params = {
        "date": game_date,
        "sportId": 1,
        "hydrate": "linescore",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    scores = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {}).get("detailedState", "")
            if status not in ("Final", "Game Over", "Completed Early"):
                continue

            away_name = game["teams"]["away"]["team"]["name"]
            home_name = game["teams"]["home"]["team"]["name"]
            away = TEAM_NAME_TO_ABBREV.get(away_name, away_name)
            home = TEAM_NAME_TO_ABBREV.get(home_name, home_name)

            linescore = game.get("linescore", {})
            innings = linescore.get("innings", [])

            away_score = game["teams"]["away"].get("score", 0)
            home_score = game["teams"]["home"].get("score", 0)

            # Calculate first 1 inning scores (for NRFI / first_1_rl)
            away_score_1 = innings[0].get("away", {}).get("runs", 0) if len(innings) >= 1 else 0
            home_score_1 = innings[0].get("home", {}).get("runs", 0) if len(innings) >= 1 else 0

            # Calculate first 3 innings scores
            away_score_3 = sum(
                inn.get("away", {}).get("runs", 0)
                for inn in innings[:3]
            )
            home_score_3 = sum(
                inn.get("home", {}).get("runs", 0)
                for inn in innings[:3]
            )

            # Calculate first 5 innings scores
            away_score_5 = sum(
                inn.get("away", {}).get("runs", 0)
                for inn in innings[:5]
            )
            home_score_5 = sum(
                inn.get("home", {}).get("runs", 0)
                for inn in innings[:5]
            )

            scores.append({
                "away": away,
                "home": home,
                "away_score": away_score,
                "home_score": home_score,
                "away_score_1": away_score_1,
                "home_score_1": home_score_1,
                "total_runs_1": away_score_1 + home_score_1,
                "away_score_3": away_score_3,
                "home_score_3": home_score_3,
                "total_runs_3": away_score_3 + home_score_3,
                "away_score_5": away_score_5,
                "home_score_5": home_score_5,
                "total_runs": away_score + home_score,
                "total_runs_5": away_score_5 + home_score_5,
                "status": status,
                "game_pk": game.get("gamePk"),
            })

    return scores


def get_postponed_games(game_date: str) -> list[dict]:
    """Return games on `game_date` that were postponed or canceled.

    Sportsbooks void bets on these games → the grader treats them as Push.
    Returns list of {away, home, status, game_pk}. Status is the MLB API
    `detailedState` (e.g. "Postponed", "Cancelled").
    """
    url = f"{MLB_API_BASE}/schedule"
    params = {"date": game_date, "sportId": 1}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    out = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            status = game.get("status", {}).get("detailedState", "")
            if status not in ("Postponed", "Cancelled", "Canceled", "Suspended"):
                continue
            away_name = game["teams"]["away"]["team"]["name"]
            home_name = game["teams"]["home"]["team"]["name"]
            out.append({
                "away": TEAM_NAME_TO_ABBREV.get(away_name, away_name),
                "home": TEAM_NAME_TO_ABBREV.get(home_name, home_name),
                "status": status,
                "game_pk": game.get("gamePk"),
            })
    return out


def get_box_score(game_pk: int) -> dict | None:
    """Fetch box score player stats for a game.

    Returns dict mapping player full names to their team side and stats,
    or None if unavailable.
    """
    try:
        url = f"{MLB_API_BASE}/game/{game_pk}/boxscore"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        players = {}

        for side in ["home", "away"]:
            team_data = data.get("teams", {}).get(side, {})
            for player_data in team_data.get("players", {}).values():
                name = player_data.get("person", {}).get("fullName", "")
                if not name:
                    continue

                stats = player_data.get("stats", {})
                batting = stats.get("batting", {})
                pitching = stats.get("pitching", {})

                # Convert inningsPitched string to total outs
                ip_str = pitching.get("inningsPitched", "0")
                try:
                    parts = str(ip_str).split(".")
                    whole = int(parts[0]) if parts[0] else 0
                    frac = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                    outs = whole * 3 + frac
                except (ValueError, IndexError):
                    outs = 0

                players[name] = {
                    "team": side,
                    "batting": {
                        "hits": batting.get("hits", 0),
                        "runs": batting.get("runs", 0),
                        "rbi": batting.get("rbi", 0),
                        "totalBases": batting.get("totalBases", 0),
                        "strikeOuts": batting.get("strikeOuts", 0),
                        "homeRuns": batting.get("homeRuns", 0),
                        "plateAppearances": batting.get("plateAppearances", 0),
                    },
                    "pitching": {
                        "strikeOuts": pitching.get("strikeOuts", 0),
                        "hits": pitching.get("hits", 0),
                        "earnedRuns": pitching.get("earnedRuns", 0),
                        "inningsPitched": ip_str,
                        "outs": outs,
                        "battersFaced": pitching.get("battersFaced", 0),
                    },
                }

        return players if players else None
    except Exception:
        return None
