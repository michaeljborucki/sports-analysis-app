import requests
from config import MLB_API_BASE


def pythagorean_win_pct(runs_scored: float, runs_allowed: float, exp: float = 1.83) -> float:
    """Calculate Pythagorean expected win percentage."""
    if runs_scored == 0 and runs_allowed == 0:
        return 0.5
    return runs_scored ** exp / (runs_scored ** exp + runs_allowed ** exp)


def get_team_profile(team_abbrev: str, season: int = 2026) -> dict:
    """Get team profile from MLB Stats API standings."""
    url = f"{MLB_API_BASE}/teams"
    params = {"season": season, "sportId": 1, "hydrate": "record"}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    for team in data.get("teams", []):
        if team.get("abbreviation") != team_abbrev:
            continue

        record = team.get("record", {})
        wins = record.get("wins", 0)
        losses = record.get("losses", 0)
        rs = record.get("runsScored", 0)
        ra = record.get("runsAllowed", 0)
        games = wins + losses

        home_rec = ""
        away_rec = ""
        for sr in record.get("records", {}).get("splitRecords", []):
            if sr["type"] == "home":
                home_rec = f"{sr['wins']}-{sr['losses']}"
            elif sr["type"] == "away":
                away_rec = f"{sr['wins']}-{sr['losses']}"

        rpg = rs / max(games, 1)
        rapg = ra / max(games, 1)

        return {
            "team": team_abbrev,
            "record": f"{wins}-{losses}",
            "pct": round(wins / max(games, 1), 3),
            "home_record": home_rec,
            "away_record": away_rec,
            "run_diff": rs - ra,
            "runs_per_game": round(rpg, 1),
            "runs_allowed_per_game": round(rapg, 1),
            "pyth_pct": round(pythagorean_win_pct(rpg, rapg), 3),
            "division": team.get("division", {}).get("name", ""),
            "div_rank": record.get("divisionRank", ""),
        }

    return {"team": team_abbrev, "error": "team not found"}
