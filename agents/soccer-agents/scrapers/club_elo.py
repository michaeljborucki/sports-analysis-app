"""Club Elo rating anchor — free daily power ratings for European clubs.

Source: http://api.clubelo.com/{YYYY-MM-DD} (CSV, no key, stable 10+ years).

Usage:
    elo_home = get_team_elo("Manchester City", league="EPL")
    elo_diff = elo_home - elo_away   # feed into briefing + Poisson prior

Limitations:
- No MLS coverage. Returns None for MLS teams.
- Name matching is best-effort — check logs for "Elo: no match" warnings.
"""
from __future__ import annotations
import csv
import io
import logging
import os
from datetime import date, timedelta

import requests
from unidecode import unidecode

from config import DATA_DIR

logger = logging.getLogger("mirofish.scrapers.club_elo")

CACHE_DIR = os.path.join(DATA_DIR, "club_elo")
BASE_URL = "http://api.clubelo.com"

# ESPN/Odds-API normalized team name -> clubelo "Club" column.
# Clubelo uses condensed spellings (Man City, not Manchester City).
CLUBELO_OVERRIDES: dict[str, str] = {
    # EPL
    "Manchester City": "ManCity",
    "Manchester United": "ManUnited",
    "Tottenham Hotspur": "Tottenham",
    "Nottingham Forest": "Forest",
    "West Ham United": "WestHam",
    "Brighton & Hove Albion": "Brighton",
    "Wolverhampton Wanderers": "Wolves",
    "Leicester City": "Leicester",
    "Newcastle United": "Newcastle",
    "AFC Bournemouth": "Bournemouth",
    "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds",
    # Serie A
    "AC Milan": "Milan",
    "Internazionale": "Inter",
    "Inter Milan": "Inter",
    "AS Roma": "Roma",
    "Hellas Verona": "Verona",
    # Eredivisie
    "PSV Eindhoven": "PSV",
    "AZ Alkmaar": "AZ",
    "Ajax Amsterdam": "Ajax",
    "Feyenoord Rotterdam": "Feyenoord",
    "FC Twente": "Twente",
    "FC Groningen": "Groningen",
    "PEC Zwolle": "Zwolle",
    "Telstar": "Telstar",
}


def _cache_path(iso_date: str) -> str:
    return os.path.join(CACHE_DIR, f"{iso_date}.csv")


def _fetch_csv(iso_date: str) -> str | None:
    """Fetch the clubelo CSV for a date. Caches to disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(iso_date)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()

    url = f"{BASE_URL}/{iso_date}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Club Elo fetch failed for %s: %s", iso_date, e)
        return None

    text = resp.text
    with open(path, "w") as f:
        f.write(text)
    logger.info("Club Elo: fetched %s (%d bytes, cached)", iso_date, len(text))
    return text


_team_elo_cache: dict[str, dict[str, float]] = {}


def _load_elo_map(iso_date: str) -> dict[str, float]:
    """Load {normalized_club_name: elo} for a given date."""
    if iso_date in _team_elo_cache:
        return _team_elo_cache[iso_date]

    text = _fetch_csv(iso_date)
    if not text:
        _team_elo_cache[iso_date] = {}
        return {}

    out: dict[str, float] = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        club = row.get("Club") or ""
        elo = row.get("Elo")
        if not club or not elo:
            continue
        try:
            out[_norm(club)] = float(elo)
        except ValueError:
            continue

    _team_elo_cache[iso_date] = out
    logger.info("Club Elo: loaded %d clubs for %s", len(out), iso_date)
    return out


def _norm(s: str) -> str:
    return unidecode(s).lower().replace(" ", "").replace("-", "").replace(".", "")


def get_team_elo(team_name: str, league: str = "", game_date: str | None = None) -> float | None:
    """Look up a team's Club Elo on a given date.

    Returns None for MLS (not covered by clubelo) or when the team can't be matched.
    """
    if league == "MLS":
        return None  # clubelo doesn't cover MLS

    iso_date = game_date or date.today().isoformat()
    elo_map = _load_elo_map(iso_date)
    if not elo_map:
        # Fall back one day — clubelo occasionally lags by 24h
        prev = (date.fromisoformat(iso_date) - timedelta(days=1)).isoformat()
        elo_map = _load_elo_map(prev)
    if not elo_map:
        return None

    override = CLUBELO_OVERRIDES.get(team_name)
    candidates = [override, team_name] if override else [team_name]
    for c in candidates:
        key = _norm(c)
        if key in elo_map:
            return elo_map[key]

    # Last-resort: substring containment (short clubelo name embedded in the longer team name)
    target = _norm(team_name)
    for k, v in elo_map.items():
        if len(k) >= 4 and (k in target or target in k):
            return v

    logger.warning("Club Elo: no match for '%s' (league=%s)", team_name, league)
    return None


def get_match_elo(home_team: str, away_team: str,
                  league: str = "", game_date: str | None = None) -> dict:
    """Return {home_elo, away_elo, elo_diff, home_win_prob, draw_prob} or empty dict.

    Win/draw probabilities use the classic Elo soccer formula:
      P(home_win) = 1 / (1 + 10^(-(elo_diff + HFA) / 400))
      P(draw)    ~= 0.28 * exp(-abs(elo_diff + HFA) / 400)  (heuristic)
    """
    from config import HOME_ADVANTAGE_BY_LEAGUE

    home_elo = get_team_elo(home_team, league, game_date)
    away_elo = get_team_elo(away_team, league, game_date)
    if home_elo is None or away_elo is None:
        return {}

    hfa_pts = 100 * HOME_ADVANTAGE_BY_LEAGUE.get(league, 0.10)  # scale 0.08 -> 80 elo pts
    diff = home_elo - away_elo + hfa_pts

    p_home = 1.0 / (1.0 + 10 ** (-diff / 400))
    p_draw_raw = 0.28 * (2.71828 ** (-abs(diff) / 400))
    p_draw = max(0.15, min(p_draw_raw, 0.30))
    p_home_win = max(0.0, p_home - p_draw / 2)
    p_away_win = max(0.0, (1.0 - p_home) - p_draw / 2)

    return {
        "home_elo": round(home_elo, 1),
        "away_elo": round(away_elo, 1),
        "elo_diff_plus_hfa": round(diff, 1),
        "elo_home_win_prob": round(p_home_win, 4),
        "elo_draw_prob": round(p_draw, 4),
        "elo_away_win_prob": round(p_away_win, 4),
    }
