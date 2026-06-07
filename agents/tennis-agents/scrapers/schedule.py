"""Fetch tournament schedule from API-Tennis."""
import logging
from datetime import datetime, timedelta, timezone
import requests
from config import API_TENNIS_KEY, API_TENNIS_BASE

logger = logging.getLogger("mirofish.scrapers.schedule")


def get_schedule(tour: str = "atp", game_date: str = None) -> list[dict]:
    if not API_TENNIS_KEY:
        logger.warning("API_TENNIS_KEY not set, returning empty schedule")
        return []
    params = {"method": "get_fixtures", "APIkey": API_TENNIS_KEY, "date_start": game_date, "date_stop": game_date}
    try:
        resp = requests.get(API_TENNIS_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Schedule fetch error: %s", e)
        return []

    events = data.get("result", [])
    if not isinstance(events, list):
        return []
    matches = []
    tour_filter = tour.lower()
    for event in events:
        event_type = event.get("event_type_type", "").lower()
        if tour_filter not in event_type or "doubles" in event_type:
            continue
        tournament = event.get("tournament_name", "")
        matches.append({
            "player_a": event.get("event_first_player", ""),
            "player_b": event.get("event_second_player", ""),
            # player_key fields let downstream resolve abbreviated names ("A.
            # Rublev") to the full Sackmann-format names ("Andrey Rublev") the
            # local archive is keyed by. Without this, get_player_profile
            # returns placeholder data (Elo 1500, 0-0 record) and challenger
            # correctly kills the bet.
            "player_a_key": event.get("first_player_key", ""),
            "player_b_key": event.get("second_player_key", ""),
            "tournament": tournament,
            "round": event.get("tournament_round", ""),
            "surface": _extract_surface(tournament),
            "indoor_outdoor": "indoor" if "indoor" in tournament.lower() else "outdoor",
            "start_time": f"{event.get('event_date', '')} {event.get('event_time', '')}".strip(),
            "match_id": event.get("event_key", ""),
        })
    logger.info("Schedule: found %d %s matches for %s", len(matches), tour.upper(), game_date)
    return matches


def _extract_surface(tournament: str) -> str:
    name = tournament.lower()
    if "clay" in name:
        return "clay"
    if "grass" in name:
        return "grass"
    return "hard"


def parse_match_datetime(start_time: str) -> datetime | None:
    """Parse 'YYYY-MM-DD HH:MM' as UTC."""
    if not start_time:
        return None
    s = start_time.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def get_upcoming_matches(tour: str = "atp", hours: int = 24) -> list[dict]:
    """Fetch matches commencing within [now, now + hours] (UTC), sorted by start time."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    dates_needed = sorted({now.date().isoformat(), end.date().isoformat()})
    combined = []
    seen_ids = set()
    for d in dates_needed:
        for m in get_schedule(tour, d):
            mid = m.get("match_id")
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            combined.append(m)
    upcoming = []
    for m in combined:
        ct = parse_match_datetime(m.get("start_time"))
        if ct and now <= ct <= end:
            upcoming.append(m)
    upcoming.sort(key=lambda m: m.get("start_time", ""))
    logger.info("Upcoming: %d %s matches in next %dh", len(upcoming), tour.upper(), hours)
    return upcoming
