from datetime import date, datetime, timedelta
import requests
from config import MLB_API_BASE


def _classify_freshness(avg_pitches: float) -> str:
    if avg_pitches < 15:
        return "fresh"
    elif avg_pitches < 25:
        return "moderate"
    elif avg_pitches < 35:
        return "tired"
    return "gassed"


def get_bullpen_state(team_id: int, game_date: str) -> dict:
    """Get bullpen usage state for a team over rolling 3-day window."""
    # Get active roster
    url = f"{MLB_API_BASE}/teams/{team_id}/roster"
    params = {"rosterType": "active", "date": game_date}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        roster = resp.json()
    except Exception as e:
        print(f"[bullpen] Roster fetch failed for team {team_id}: {e}")
        return {"closer": None, "relievers": [], "bullpen_freshness": "unknown", "avg_pitches_3d": 0}

    relievers = []
    closer = None
    total_pitches = 0
    reliever_count = 0

    for player in roster.get("roster", []):
        pos = player.get("position", {}).get("abbreviation", "")
        if pos not in ("RP", "CL"):
            continue

        pid = player["person"]["id"]
        name = player["person"]["fullName"]

        # Get recent game logs
        pitches_3d = _get_recent_pitches(pid, game_date, days=3)
        available = pitches_3d < 40  # rough threshold

        entry = {
            "name": name,
            "id": pid,
            "available": available,
            "pitches_last_3d": pitches_3d,
        }

        if pos == "CL":
            closer = entry
        else:
            relievers.append(entry)

        total_pitches += pitches_3d
        reliever_count += 1

    avg_pitches = total_pitches / max(reliever_count, 1)

    return {
        "closer": closer,
        "relievers": relievers,
        "bullpen_freshness": _classify_freshness(avg_pitches),
        "avg_pitches_3d": round(avg_pitches, 1),
    }


def _get_recent_pitches(pitcher_id: int, game_date: str, days: int = 3) -> int:
    """Sum pitches thrown in the last N days."""
    url = f"{MLB_API_BASE}/people/{pitcher_id}/stats"
    params = {
        "stats": "gameLog",
        "season": game_date[:4],
        "group": "pitching",
    }
    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        cutoff = datetime.strptime(game_date, "%Y-%m-%d").date() - timedelta(days=days)
        total = 0

        for stat_group in data.get("stats", []):
            for split in stat_group.get("splits", []):
                split_date = split.get("date", "")
                if not split_date:
                    continue
                try:
                    d = datetime.strptime(split_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if d >= cutoff:
                    total += split.get("stat", {}).get("numberOfPitches", 0)

        return total
    except Exception:
        return 0
