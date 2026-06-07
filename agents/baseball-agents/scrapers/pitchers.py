from datetime import date, datetime, timedelta
import requests
import pandas as pd

from pybaseball import playerid_lookup, pitching_stats, statcast_pitcher
from config import MLB_API_BASE, TEAM_NAME_TO_ABBREV


def get_probable_starters(game_date: str = None) -> list[dict]:
    """Fetch today's games with probable pitchers from MLB Stats API."""
    if game_date is None:
        game_date = date.today().isoformat()

    url = f"{MLB_API_BASE}/schedule"
    params = {
        "date": game_date,
        "sportId": 1,
        "hydrate": "probablePitcher,venue",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            away = game["teams"]["away"]
            home = game["teams"]["home"]

            away_pitcher = away.get("probablePitcher", {})
            home_pitcher = home.get("probablePitcher", {})

            games.append({
                "game_pk": game["gamePk"],
                "game_date": game.get("gameDate", ""),
                "status": game.get("status", {}).get("detailedState", ""),
                "venue": game.get("venue", {}).get("name", ""),
                "away_team": TEAM_NAME_TO_ABBREV.get(
                    away["team"]["name"], away["team"]["name"]
                ),
                "away_team_id": away["team"]["id"],
                "away_pitcher": away_pitcher.get("fullName", "TBD"),
                "away_pitcher_id": away_pitcher.get("id"),
                "home_team": TEAM_NAME_TO_ABBREV.get(
                    home["team"]["name"], home["team"]["name"]
                ),
                "home_team_id": home["team"]["id"],
                "home_pitcher": home_pitcher.get("fullName", "TBD"),
                "home_pitcher_id": home_pitcher.get("id"),
            })

    return games


def get_starter_profile(pitcher_name: str, season: int = 2026) -> dict:
    """Build comprehensive pitcher profile from pybaseball + MLB API."""
    first, last = pitcher_name.split(" ", 1)

    lookup = playerid_lookup(last, first)
    if lookup.empty:
        return {"name": pitcher_name, "error": "player not found"}

    mlbam_id = int(lookup.iloc[0]["key_mlbam"])

    try:
        stats_df = pitching_stats(season, season, qual=0)
        player_row = stats_df[
            stats_df["Name"].str.contains(last, case=False, na=False)
        ]
        if player_row.empty:
            season_stats = {}
        else:
            row = player_row.iloc[0]
            season_stats = {
                "w": int(row.get("W", 0)),
                "l": int(row.get("L", 0)),
                "era": float(row.get("ERA", 0)),
                "fip": float(row.get("FIP", 0)),
                "xfip": float(row.get("xFIP", 0)),
                "whip": float(row.get("WHIP", 0)),
                "k_per_9": float(row.get("K/9", 0)),
                "bb_per_9": float(row.get("BB/9", 0)),
                "hr_per_9": float(row.get("HR/9", 0)),
                "ip": float(row.get("IP", 0)),
                "starts": int(row.get("GS", 0)),
            }
    except Exception:
        season_stats = {}

    pitch_mix = {}
    recent_velo = None
    try:
        end = date.today()
        start = end - timedelta(days=30)
        sc = statcast_pitcher(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), mlbam_id
        )
        if not sc.empty and "pitch_type" in sc.columns:
            counts = sc["pitch_type"].value_counts(normalize=True)
            pitch_mix = {k: round(v * 100, 1) for k, v in counts.items()}
        if not sc.empty and "release_speed" in sc.columns:
            fastballs = sc[sc["pitch_type"].isin(["FF", "SI"])]
            if not fastballs.empty:
                recent_velo = round(fastballs["release_speed"].mean(), 1)
    except Exception:
        pass

    last_5 = _get_recent_game_logs(mlbam_id, season, limit=5)

    days_rest = None
    if last_5:
        try:
            last_start_date = datetime.strptime(last_5[0]["date"], "%Y-%m-%d").date()
            days_rest = (date.today() - last_start_date).days
        except (ValueError, KeyError):
            pass

    return {
        "name": pitcher_name,
        "mlbam_id": mlbam_id,
        "season_stats": season_stats,
        "last_5_starts": last_5,
        "pitch_mix": pitch_mix,
        "recent_velo_avg": recent_velo,
        "days_rest": days_rest,
    }


def _get_recent_game_logs(pitcher_id: int, season: int, limit: int = 5) -> list[dict]:
    """Fetch recent game logs from MLB Stats API."""
    url = f"{MLB_API_BASE}/people/{pitcher_id}/stats"
    params = {
        "stats": "gameLog",
        "season": season,
        "group": "pitching",
    }
    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        logs = []
        for split_group in data.get("stats", []):
            for split in split_group.get("splits", []):
                stat = split.get("stat", {})
                logs.append({
                    "date": split.get("date", ""),
                    "opp": split.get("opponent", {}).get("abbreviation", ""),
                    "ip": stat.get("inningsPitched", "0"),
                    "er": stat.get("earnedRuns", 0),
                    "k": stat.get("strikeOuts", 0),
                    "bb": stat.get("baseOnBalls", 0),
                    "hits": stat.get("hits", 0),
                    "pitches": stat.get("numberOfPitches", 0),
                    "decision": stat.get("decision", ""),
                })

        logs.sort(key=lambda x: x["date"], reverse=True)
        return logs[:limit]
    except Exception:
        return []
