"""CS2 match data scrapers via HLTV."""
import asyncio
import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

try:
    from hltv_async_api import Hltv
    _hltv = Hltv()
    HLTV_AVAILABLE = True
except ImportError:
    HLTV_AVAILABLE = False
    log.warning("[cs2] hltv-async-api not installed — using stub data")


async def _fetch_team_profile_async(team_name: str) -> dict:
    """Fetch CS2 team profile from HLTV."""
    if not HLTV_AVAILABLE:
        return _empty_team_profile(team_name)
    try:
        # Attempt to use hltv-async-api
        # The exact API may vary — adapt as needed
        team_data = await _hltv.get_team_info(team_name)
        return _parse_team_data(team_data, team_name)
    except Exception as e:
        log.warning(f"[cs2] HLTV fetch failed for {team_name}: {e}")
        return _empty_team_profile(team_name)


async def _fetch_upcoming_matches_async() -> list[dict]:
    """Fetch upcoming CS2 matches from HLTV."""
    if not HLTV_AVAILABLE:
        return []
    try:
        matches = await _hltv.get_upcoming_matches()
        return [_parse_match(m) for m in (matches or [])]
    except Exception as e:
        log.warning(f"[cs2] HLTV upcoming matches failed: {e}")
        return []


async def _fetch_head_to_head_async(team_a: str, team_b: str) -> dict:
    """Fetch H2H history from HLTV."""
    return {
        "total_matches": 0,
        "team_a_wins": 0,
        "team_b_wins": 0,
        "recent_5": [],
    }


async def _fetch_match_result_async(team_a: str, team_b: str, date: str) -> dict:
    """Fetch completed match result for bet grading."""
    if not HLTV_AVAILABLE:
        return _empty_match_result()
    try:
        results = await _hltv.get_results()
        for r in (results or []):
            if _matches_teams(r, team_a, team_b):
                return _parse_result(r)
        return _empty_match_result()
    except Exception as e:
        log.warning(f"[cs2] HLTV results fetch failed: {e}")
        return _empty_match_result()


# --- Sync wrappers ---

def fetch_team_profile(team_name: str) -> dict:
    return asyncio.run(_fetch_team_profile_async(team_name))

def fetch_upcoming_matches() -> list[dict]:
    return asyncio.run(_fetch_upcoming_matches_async())

def fetch_head_to_head(team_a: str, team_b: str) -> dict:
    return asyncio.run(_fetch_head_to_head_async(team_a, team_b))

def fetch_match_result(team_a: str, team_b: str, date: str) -> dict:
    return asyncio.run(_fetch_match_result_async(team_a, team_b, date))


# --- Helpers ---

def _empty_team_profile(name: str) -> dict:
    return {
        "name": name, "hltv_ranking": 0,
        "win_rate_3m": 0.0, "win_rate_6m": 0.0,
        "lan_record": "0-0", "online_record": "0-0",
        "roster": [], "coach": "",
        "days_since_roster_change": 999,
        "map_pool": {}, "recent_form": [],
    }

def _empty_match_result() -> dict:
    return {"winner": "", "score": "0-0", "maps_played": 0, "map_scores": []}

def _parse_team_data(data, fallback_name: str) -> dict:
    """Parse HLTV team data into our standard format."""
    if not data or not isinstance(data, dict):
        return _empty_team_profile(fallback_name)
    return {
        "name": data.get("name", fallback_name),
        "hltv_ranking": data.get("ranking", 0),
        "win_rate_3m": data.get("win_rate_3m", 0.0),
        "win_rate_6m": data.get("win_rate_6m", 0.0),
        "lan_record": data.get("lan_record", "0-0"),
        "online_record": data.get("online_record", "0-0"),
        "roster": data.get("players", []),
        "coach": data.get("coach", ""),
        "days_since_roster_change": data.get("days_since_roster_change", 999),
        "map_pool": data.get("map_pool", {}),
        "recent_form": data.get("recent_form", []),
    }

def _parse_match(m) -> dict:
    if not isinstance(m, dict):
        return {}
    return {
        "team_a": m.get("team1", m.get("team_a", "")),
        "team_b": m.get("team2", m.get("team_b", "")),
        "tournament": m.get("event", m.get("tournament", "")),
        "format": m.get("format", "bo3"),
        "tier": m.get("tier", 2),
        "date": m.get("date", ""),
        "lan": m.get("lan", False),
    }

def _parse_result(r) -> dict:
    return {
        "winner": r.get("winner", ""),
        "score": r.get("score", "0-0"),
        "maps_played": r.get("maps_played", 0),
        "map_scores": r.get("map_scores", []),
    }

def _matches_teams(result, team_a, team_b) -> bool:
    t1 = str(result.get("team1", "")).lower()
    t2 = str(result.get("team2", "")).lower()
    return (team_a.lower() in t1 or team_a.lower() in t2) and \
           (team_b.lower() in t1 or team_b.lower() in t2)
