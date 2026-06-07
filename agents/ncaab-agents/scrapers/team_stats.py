"""Fetch NCAAB team efficiency ratings from CBBData API (wraps Bart Torvik)."""
import io
import requests
import logging
import json
import os
from datetime import date
import pyarrow.parquet as pq
from config import CBBDATA_API_KEY, CBBDATA_BASE, DATA_DIR

logger = logging.getLogger("mirofish.scrapers.team_stats")

_CACHE = {}  # in-memory cache for the day's ratings

# ESPN/Odds API display name → CBBData team name
_NAME_ALIASES: dict[str, str] = {
    "uconn": "connecticut",
    "pitt": "pittsburgh",
    "umass": "massachusetts",
    "ole miss": "mississippi",
    "unc": "north carolina",
    "miami hurricanes": "miami fl",
    "miami (oh) redhawks": "miami oh",
    "miami (fl) hurricanes": "miami fl",
    "st. johns": "st. john's",
    "saint johns": "st. john's",
    "saint marys": "saint mary's",
    "nc state": "north carolina st.",
    "ucsb": "uc santa barbara",
    "uci": "uc irvine",
    "ucd": "uc davis",
    "ucr": "uc riverside",
    "lil": "long island",
}

def _cache_path(season: int) -> str:
    return os.path.join(DATA_DIR, f"team_ratings_{season}_{date.today().isoformat()}.json")

def get_all_team_ratings(season: int = None) -> list[dict]:
    """Bulk-fetch all 362 D1 team ratings. Cached for the day."""
    if season is None:
        today = date.today()
        season = today.year if today.month >= 11 else today.year - 1  # NCAAB season spans Nov-Apr

    cache_key = f"ratings_{season}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    # Try disk cache
    cp = _cache_path(season)
    if os.path.exists(cp):
        try:
            with open(cp) as f:
                data = json.load(f)
                _CACHE[cache_key] = data
                logger.info("Loaded %d team ratings from cache", len(data))
                return data
        except Exception:
            pass

    # Fetch from CBBData API
    if not CBBDATA_API_KEY:
        logger.warning("No CBBDATA_API_KEY set, returning empty ratings")
        return []

    data = _fetch_ratings(season)

    # If current season has no efficiency data, fall back to previous year
    if data and all(_has_no_efficiency(t) for t in data):
        logger.warning("Season %d has no efficiency data, falling back to %d", season, season - 1)
        data = _fetch_ratings(season - 1)

    if not data:
        return []

    # Cache to disk
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(cp, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("Failed to cache ratings: %s", e)

    _CACHE[cache_key] = data
    logger.info("Fetched %d team ratings from CBBData", len(data))
    return data


def _fetch_ratings(season: int) -> list[dict]:
    """Fetch ratings for a season, handling both JSON and Parquet responses."""
    url = f"{CBBDATA_BASE}/torvik/ratings"
    params = {"year": season, "key": CBBDATA_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()

        # CBBData may return Parquet (PAR1 header) or JSON
        if resp.content[:4] == b"PAR1":
            df = pq.read_table(io.BytesIO(resp.content)).to_pandas()
            data = df.to_dict(orient="records")
        else:
            data = resp.json()

        return data
    except Exception as e:
        logger.error("Failed to fetch team ratings for %d: %s", season, e)
        return []


def _has_no_efficiency(team: dict) -> bool:
    """Check if a team record has no efficiency data (all NaN/None/0)."""
    for key in ["adj_o", "adjoe", "adj_oe"]:
        val = team.get(key)
        if val is not None and val == val and val != 0:  # val == val filters NaN
            return False
    return True


def _resolve_name(team_name: str) -> str:
    """Resolve an ESPN/Odds display name to a CBBData-compatible name."""
    low = team_name.lower().strip()
    # Direct alias hit (full display name, e.g. "miami hurricanes")
    if low in _NAME_ALIASES:
        return _NAME_ALIASES[low]
    # Progressively strip words from the right to find alias
    # Handles multi-word mascots like "Tar Heels", "Red Storm", "Fighting Illini"
    words = low.split()
    for i in range(len(words) - 1, 0, -1):
        prefix = " ".join(words[:i])
        if prefix in _NAME_ALIASES:
            return _NAME_ALIASES[prefix]
    return low


def get_team_efficiency(team_name: str, season: int = None) -> dict:
    """Get efficiency profile for a single team.

    Returns dict with keys: team, conference, trank, adj_oe, adj_de, adj_em,
    adj_tempo, sos, luck, record, conf_record, home_record, away_record,
    last_10, trend, efg_off, tov_off, oreb_off, ftr_off, efg_def, tov_def,
    oreb_def, ftr_def, three_rate, three_pct, adj_oe_rank, adj_de_rank
    """
    ratings = get_all_team_ratings(season)
    resolved = _resolve_name(team_name)
    team_lower = team_name.lower()

    # Try resolved alias first (exact), then original name (exact + fuzzy)
    for team in ratings:
        name = (team.get("team") or team.get("Team") or "").lower()
        if name == resolved:
            return _normalize_team_stats(team)

    for team in ratings:
        name = (team.get("team") or team.get("Team") or "").lower()
        if name == team_lower or team_lower in name or name in team_lower:
            return _normalize_team_stats(team)

    # Last resort: match without mascot (e.g. "arizona wildcats" → "arizona")
    base = team_lower.rsplit(" ", 1)[0] if " " in team_lower else team_lower
    for team in ratings:
        name = (team.get("team") or team.get("Team") or "").lower()
        if name == base or base in name or name in base:
            return _normalize_team_stats(team)

    logger.warning("Team not found in ratings: %s", team_name)
    return _empty_team_stats(team_name)


def _normalize_team_stats(raw: dict) -> dict:
    """Normalize CBBData/Torvik response to our standard format."""
    def _g(key, default=None):
        # Try common key variations
        for k in [key, key.lower(), key.upper(), key.replace("_", "")]:
            if k in raw:
                return raw[k]
        return default

    return {
        "team": _g("team", ""),
        "conference": _g("conf", _g("conference", "")),
        "trank": _g("rk", _g("barthag_rk", _g("trank", 0))),
        "adj_oe": _g("adj_o", _g("adjoe", 0)),
        "adj_de": _g("adj_d", _g("adjde", 0)),
        "adj_em": _g("barthag", _g("adjEM", _g("adj_em", 0))),
        "adj_tempo": _g("adj_t", _g("adj_tempo", _g("tempo", 0))),
        "sos": _g("sos", 0),
        "luck": _g("luck", 0),
        "record": _g("record", ""),
        "conf_record": _g("conf_record", _g("conf_rec", "")),
        "home_record": _g("home_record", ""),
        "away_record": _g("away_record", ""),
        "last_10": _g("last_10", ""),
        "trend": _g("trend", ""),
        "efg_off": _g("efg_o", _g("efg_off", 0)),
        "tov_off": _g("tov_o", _g("tov_off", 0)),
        "oreb_off": _g("orb_o", _g("oreb_off", 0)),
        "ftr_off": _g("ftr_o", _g("ftr_off", 0)),
        "efg_def": _g("efg_d", _g("efg_def", 0)),
        "tov_def": _g("tov_d", _g("tov_def", 0)),
        "oreb_def": _g("orb_d", _g("oreb_def", 0)),
        "ftr_def": _g("ftr_d", _g("ftr_def", 0)),
        "three_rate": _g("3p_rate", _g("three_rate", 0)),
        "three_pct": _g("3p_pct", _g("three_pct", 0)),
        "adj_oe_rank": _g("adj_o_rk", _g("adjoe_rk", _g("adj_oe_rank", 0))),
        "adj_de_rank": _g("adj_d_rk", _g("adjde_rk", _g("adj_de_rank", 0))),
    }


def _empty_team_stats(team_name: str) -> dict:
    """Return empty team stats as fallback."""
    result = _normalize_team_stats({})
    result["team"] = team_name
    return result
