"""Fetch NCAAB daily schedule from ESPN API."""
import requests
import logging
from config import ESPN_CBB_BASE

logger = logging.getLogger("mirofish.scrapers.schedule")

def get_ncaab_schedule(game_date: str) -> list[dict]:
    """Get today's NCAAB games from ESPN scoreboard API.

    Returns list of dicts with keys:
    game_id, away_team, away_abbrev, home_team, home_abbrev,
    away_conference, home_conference, venue, neutral_site,
    conference_game, game_time, tournament_id
    """
    url = f"{ESPN_CBB_BASE}/scoreboard"
    params = {"dates": game_date.replace("-", "")}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Failed to fetch schedule: %s", e)
        return []

    games = []
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        competitors = competition.get("competitors", [])
        if len(competitors) != 2:
            continue

        # ESPN puts home team first in competitors
        home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_team_info = home_comp.get("team", {})
        away_team_info = away_comp.get("team", {})

        venue_info = competition.get("venue", {})

        status = competition.get("status", {}).get("type", {}).get("name", "")

        games.append({
            "game_id": event.get("id", ""),
            "away_team": away_team_info.get("displayName", ""),
            "away_abbrev": away_team_info.get("abbreviation", ""),
            "away_team_id": away_team_info.get("id", ""),
            "away_conference": away_team_info.get("conferenceId", ""),
            "home_team": home_team_info.get("displayName", ""),
            "home_abbrev": home_team_info.get("abbreviation", ""),
            "home_team_id": home_team_info.get("id", ""),
            "home_conference": home_team_info.get("conferenceId", ""),
            "venue": venue_info.get("fullName", ""),
            "venue_city": venue_info.get("address", {}).get("city", ""),
            "neutral_site": competition.get("neutralSite", False),
            "conference_game": competition.get("conferenceCompetition", False),
            "game_time": event.get("date", ""),
            "status": status,
            "tournament_id": competition.get("tournamentId"),
            "away_record": away_comp.get("records", [{}])[0].get("summary", "") if away_comp.get("records") else "",
            "home_record": home_comp.get("records", [{}])[0].get("summary", "") if home_comp.get("records") else "",
        })

    logger.info("Found %d games for %s", len(games), game_date)
    return games
