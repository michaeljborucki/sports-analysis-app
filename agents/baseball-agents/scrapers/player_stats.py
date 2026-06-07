"""Fetch per-player stats from MLB Stats API for Monte Carlo simulation."""
import json
import os
import threading
from datetime import date
import requests
import difflib
from config import MLB_API_BASE, DATA_DIR

PLAYER_MAP_FILE = os.path.join(DATA_DIR, "player_map.json")
UNMATCHED_LOG = os.path.join(DATA_DIR, "unmatched_players.log")

_player_map_lock = threading.Lock()

# In-memory handedness cache (handedness doesn't change mid-season).
_HANDEDNESS_CACHE: dict[int, dict] = {}
_handedness_lock = threading.Lock()

LEAGUE_AVERAGES = {
    "k_pct": 0.224,
    "bb_pct": 0.084,
    "hbp_pct": 0.011,
    "hr_pct": 0.033,
    "single_pct": 0.152,
    "double_pct": 0.044,
    "triple_pct": 0.004,
    "out_pct": 0.448,  # residual: 1 - sum(events above); balls-in-play outs
}

# Regression constants: how many PA/BF of league-average data to blend in.
# A stat gets 50% weight at regress_n PA. PER-STAT constants (2026-06-03) are
# each stat's empirical stabilization point — the sample size where split-half
# reliability ≈ 0.7 (Russell Carleton / FanGraphs Sabermetrics Library,
# https://library.fangraphs.com/principles/sample-size/). A single constant is
# statistically wrong: K% stabilizes in ~60 PA but extra-base-hit rate needs
# ~1610, so uniform regression over-trusts noisy power and over-regresses K%.
# In-house precedent: PITCHER_REGRESS_BF dropped 150 → 50 on 2026-05-17 after
# pitcher_strikeouts hit −30.9% ROI — every starter was collapsing to the same
# ~59.5% under probability because over-regression killed the elite-K signal.
BATTER_REGRESS_PA = {
    "k_pct": 60,
    "bb_pct": 120,
    "hbp_pct": 240,
    "hr_pct": 170,
    "single_pct": 290,
    "double_pct": 1610,   # XBH stabilization point (2B+3B share it)
    "triple_pct": 1610,
}
PITCHER_REGRESS_BF = 50


def _regress_to_mean(actual_rate: float, sample_size: int,
                     league_rate: float, regress_n: int) -> float:
    """Blend observed rate with league average weighted by sample size."""
    weight = sample_size / (sample_size + regress_n)
    return weight * actual_rate + (1 - weight) * league_rate


def _load_player_map() -> dict:
    """Load cached name→ID mapping."""
    if os.path.exists(PLAYER_MAP_FILE):
        try:
            with open(PLAYER_MAP_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_player_map(mapping: dict) -> None:
    os.makedirs(os.path.dirname(PLAYER_MAP_FILE), exist_ok=True)
    with open(PLAYER_MAP_FILE, "w") as f:
        json.dump(mapping, f, indent=2)


def resolve_player(name: str, team: str = None) -> int | None:
    """Resolve a player display name to MLB player ID."""
    if not name:
        return None

    # 1. Check cache (locked)
    with _player_map_lock:
        mapping = _load_player_map()
        if name in mapping:
            return mapping[name]

    # 2. MLB Stats API search (unlocked — no lock during network I/O)
    pid = None
    try:
        url = f"{MLB_API_BASE}/people/search"
        resp = requests.get(url, params={"names": name, "limit": 5}, timeout=10)
        if resp.status_code == 200:
            people = resp.json().get("people", [])
            if people:
                for p in people:
                    if p.get("active", False):
                        pid = p["id"]
                        break
                if pid is None:
                    pid = people[0]["id"]
    except Exception:
        pass

    # 3. Fuzzy match against cache (locked)
    if pid is None:
        with _player_map_lock:
            mapping = _load_player_map()
            cached_names = list(mapping.keys())
            if cached_names:
                matches = difflib.get_close_matches(name, cached_names, n=1, cutoff=0.85)
                if matches:
                    pid = mapping[matches[0]]

    # 4. Save to cache if resolved (locked, re-read to avoid lost updates)
    if pid is not None:
        with _player_map_lock:
            mapping = _load_player_map()
            mapping[name] = pid
            _save_player_map(mapping)
        return pid

    # 5. Log unmatched (locked)
    with _player_map_lock:
        try:
            os.makedirs(os.path.dirname(UNMATCHED_LOG), exist_ok=True)
            with open(UNMATCHED_LOG, "a") as f:
                f.write(f"{name} (team={team})\n")
        except Exception:
            pass

    return None


def get_handedness(player_id: int) -> dict:
    """Fetch a player's batting and throwing hand from MLB Stats API.

    Returns {"bat_side": "L"|"R"|"S", "pitch_hand": "L"|"R"} with safe
    defaults of "R"/"R" on any failure. Cached per-process — handedness
    doesn't change within a season.
    """
    with _handedness_lock:
        cached = _HANDEDNESS_CACHE.get(player_id)
        if cached is not None:
            return cached

    result = {"bat_side": "R", "pitch_hand": "R"}
    try:
        url = f"{MLB_API_BASE}/people/{player_id}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            people = resp.json().get("people", [])
            if people:
                p = people[0]
                bs = (p.get("batSide") or {}).get("code")
                ph = (p.get("pitchHand") or {}).get("code")
                if bs in ("L", "R", "S"):
                    result["bat_side"] = bs
                if ph in ("L", "R"):
                    result["pitch_hand"] = ph
    except Exception:
        pass

    with _handedness_lock:
        _HANDEDNESS_CACHE[player_id] = result
    return result


def get_batter_stats(player_id: int, season: int = None) -> dict:
    """Fetch batter season stats from MLB Stats API.

    Returns dict with rate stats (k_pct, bb_pct, hr_pct, etc.) needed by PA engine.
    Falls back to league averages if stats unavailable.
    """
    if season is None:
        season = date.today().year
    result = {
        "player_id": player_id,
        **LEAGUE_AVERAGES,
        **get_handedness(player_id),
    }

    try:
        url = f"{MLB_API_BASE}/people/{player_id}/stats"
        params = {"stats": "season", "season": season, "group": "hitting"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return result

        splits = resp.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return result

        s = splits[0].get("stat", {})
        pa = s.get("plateAppearances", 0)
        if pa < 20:
            return result

        ab = s.get("atBats", 1)
        hits = s.get("hits", 0)
        doubles = s.get("doubles", 0)
        triples = s.get("triples", 0)
        hr = s.get("homeRuns", 0)
        bb = s.get("baseOnBalls", 0)
        k = s.get("strikeOuts", 0)
        hbp = s.get("hitByPitch", 0)
        singles = hits - doubles - triples - hr

        # Per-PA event rates, each regressed toward league average by its own
        # stabilization constant (see BATTER_REGRESS_PA).
        events = {
            "k_pct": k / pa,
            "bb_pct": bb / pa,
            "hbp_pct": hbp / pa,
            "hr_pct": hr / pa,
            "single_pct": singles / pa,
            "double_pct": doubles / pa,
            "triple_pct": triples / pa,
        }
        for key, raw_rate in events.items():
            result[key] = _regress_to_mean(
                raw_rate, pa, LEAGUE_AVERAGES[key], BATTER_REGRESS_PA[key]
            )
        # out_pct (balls-in-play outs) is the residual, not an independent
        # skill: deriving it keeps the 8 outcomes summing to 1.0 and excludes
        # strikeouts, which are their own outcome in the PA engine.
        result["out_pct"] = max(0.01, 1 - sum(result[key] for key in events))
        result["pa"] = int(pa)

    except Exception:
        pass

    return result


def get_pitcher_stats(player_id: int, season: int = None) -> dict:
    """Fetch pitcher season stats from MLB Stats API.

    Returns dict with rate stats needed by PA engine + avg_pitch_count.
    """
    if season is None:
        season = date.today().year
    result = {
        "player_id": player_id,
        "avg_pitch_count": 90,
        **LEAGUE_AVERAGES,
        **get_handedness(player_id),
    }

    try:
        url = f"{MLB_API_BASE}/people/{player_id}/stats"
        params = {"stats": "season", "season": season, "group": "pitching"}
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return result

        splits = resp.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return result

        s = splits[0].get("stat", {})
        bf = s.get("battersFaced", 0)
        if bf < 20:
            return result

        hits = s.get("hits", 0)
        doubles = s.get("doubles", 0)
        triples = s.get("triples", 0)
        hr = s.get("homeRuns", 0)
        bb = s.get("baseOnBalls", 0)
        k = s.get("strikeOuts", 0)
        singles = hits - doubles - triples - hr

        raw = {
            "k_pct": k / bf,
            "bb_pct": bb / bf,
            "hr_pct": hr / bf,
            "single_pct": singles / bf,
            "double_pct": doubles / bf,
            "triple_pct": triples / bf,
            "out_pct": max(0.01, 1 - (hits + bb) / bf),
        }
        for key, raw_rate in raw.items():
            result[key] = _regress_to_mean(
                raw_rate, bf, LEAGUE_AVERAGES[key], PITCHER_REGRESS_BF
            )

        # Estimate avg pitch count from innings pitched
        ip = float(s.get("inningsPitched", "0"))
        games_started = s.get("gamesStarted", 0)
        if games_started > 0 and ip > 0:
            result["avg_pitch_count"] = int((ip / games_started) * 16)  # ~16 pitches per IP

    except Exception:
        pass

    return result


def get_lineup(game_pk: int) -> dict | None:
    """Fetch confirmed lineup for a game.

    Returns:
      {"home": [player_ids], "away": [player_ids],
       "home_pitcher": id, "away_pitcher": id,
       "names": {player_id: full_name, ...}}
    or None if the lineup isn't confirmed yet.
    """
    try:
        url = f"{MLB_API_BASE}/game/{game_pk}/boxscore"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        teams = data.get("teams", {})
        result = {"home": [], "away": [], "home_pitcher": None,
                  "away_pitcher": None, "names": {}}

        for side in ["home", "away"]:
            team_data = teams.get(side, {})
            batting_order = team_data.get("battingOrder", [])
            if batting_order:
                result[side] = batting_order[:9]

            pitchers = team_data.get("pitchers", [])
            if pitchers:
                result[f"{side}_pitcher"] = pitchers[0]

            # Extract name for every player referenced in the boxscore. Stored
            # once in a flat dict so downstream consumers (brief formatter)
            # can look up by ID regardless of which side the player is on.
            for key, player in team_data.get("players", {}).items():
                pid = player.get("person", {}).get("id")
                name = player.get("person", {}).get("fullName")
                if pid and name:
                    result["names"][pid] = name

        if result["home"] and result["away"]:
            return result
    except Exception:
        pass

    return None
