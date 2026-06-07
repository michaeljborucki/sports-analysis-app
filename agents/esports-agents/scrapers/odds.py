"""Esports odds scraper — OddsPapi (primary) + The Odds API (fallback)."""
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import os
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, ODDSPAPI_API_KEY, ODDSPAPI_BASE, DATA_DIR

log = logging.getLogger(__name__)

# OddsPapi sport ID mapping
ODDSPAPI_SPORT_IDS = {
    "cs2": 17,
    "lol": 18,
    "dota2": 16,
    "valorant": 61,
}

# The Odds API sport key mapping (fallback)
ODDS_API_SPORT_KEYS = {
    "lol": "esports_lol",
}

# Rate limiting
REQUEST_BUDGET_FILE = os.path.join(DATA_DIR, "oddspapi_usage.json")
MONTHLY_BUDGET = 250
BUDGET_RESERVE = 10  # Reserve for health checks

# Caching
ODDS_CACHE_TTL = 1800  # 30 minutes
_odds_cache: dict = {}


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method. Solves for n where p_a^n + p_b^n = 1."""
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    if abs(total - 1.0) < 1e-6:
        return (prob_a, prob_b)
    if prob_a <= 0.001 or prob_b <= 0.001:
        return (prob_a / total, prob_b / total)
    lo, hi = 0.01, 20.0
    for _ in range(100):
        mid = (lo + hi) / 2
        val = prob_a ** mid + prob_b ** mid
        if val > 1.0:
            lo = mid
        else:
            hi = mid
        if abs(val - 1.0) < 1e-10:
            break
    n = (lo + hi) / 2
    return (round(prob_a ** n, 6), round(prob_b ** n, 6))


@dataclass
class OddsData:
    team_a: str
    team_b: str
    commence_time: str
    game_title: str = ""
    tournament: str = ""
    format: str = "bo3"
    moneyline: dict = field(default_factory=dict)
    map_handicap: dict = field(default_factory=dict)
    total_maps: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)
    bookmaker_count: int = 0
    pinnacle_odds: dict = field(default_factory=dict)

    def compute_implied_probs(self):
        """Calculate vig-removed implied probabilities using power devig."""
        if self.moneyline and "team_a" in self.moneyline and "team_b" in self.moneyline:
            raw_a = american_to_implied_prob(self.moneyline["team_a"])
            raw_b = american_to_implied_prob(self.moneyline["team_b"])
            da, db = power_devig(raw_a, raw_b)
            self.implied_probs["ml_team_a"] = da
            self.implied_probs["ml_team_b"] = db

    def to_dict(self) -> dict:
        """Serialize for passing to ensemble layers."""
        return {
            "team_a": self.team_a,
            "team_b": self.team_b,
            "moneyline": self.moneyline,
            "map_handicap": self.map_handicap,
            "total_maps": self.total_maps,
            "implied_probs": self.implied_probs,
            "format": self.format,
        }


# --- Rate Limiting ---

def _load_usage() -> dict:
    """Load monthly request counter."""
    if os.path.exists(REQUEST_BUDGET_FILE):
        try:
            with open(REQUEST_BUDGET_FILE) as f:
                data = json.load(f)
            if data.get("month") == datetime.now().strftime("%Y-%m"):
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {"month": datetime.now().strftime("%Y-%m"), "requests": 0}


def _record_request():
    """Increment request counter."""
    usage = _load_usage()
    usage["requests"] += 1
    os.makedirs(os.path.dirname(REQUEST_BUDGET_FILE), exist_ok=True)
    with open(REQUEST_BUDGET_FILE, "w") as f:
        json.dump(usage, f)
    remaining = MONTHLY_BUDGET - usage["requests"]
    if remaining < 50:
        log.warning(f"OddsPapi budget low — {remaining} requests remaining this month")


# --- Caching ---

def _get_cached_odds(game_key: str) -> list | None:
    key = f"{game_key}_{datetime.now().strftime('%Y-%m-%d')}"
    if key in _odds_cache:
        ts, data = _odds_cache[key]
        if (datetime.now() - ts).total_seconds() < ODDS_CACHE_TTL:
            log.info(f"[odds] Using cached odds for {game_key}")
            return data
    return None


def _set_cached_odds(game_key: str, data: list):
    key = f"{game_key}_{datetime.now().strftime('%Y-%m-%d')}"
    _odds_cache[key] = (datetime.now(), data)


# --- OddsPapi ---

def _fetch_oddspapi(game_key: str) -> list[OddsData]:
    """Fetch odds from OddsPapi REST API."""
    if not ODDSPAPI_API_KEY:
        log.warning("[odds] No ODDSPAPI_API_KEY set")
        return []

    usage = _load_usage()
    if usage["requests"] >= MONTHLY_BUDGET - BUDGET_RESERVE:
        log.warning("[odds] OddsPapi monthly budget exhausted, using fallback only")
        return []

    sport_id = ODDSPAPI_SPORT_IDS.get(game_key)
    if sport_id is None:
        log.warning(f"[odds] Unknown game key for OddsPapi: {game_key}")
        return []

    try:
        _record_request()
        resp = requests.get(
            f"{ODDSPAPI_BASE}/odds",
            params={
                "sport_id": sport_id,
                "market": "match_winner,map_handicap,total_maps",
            },
            headers={"Authorization": f"Bearer {ODDSPAPI_API_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        log.error(f"[odds] OddsPapi error: {e}")
        return []

    results = []
    for event in events if isinstance(events, list) else []:
        try:
            od = OddsData(
                team_a=event.get("home_team", event.get("team_a", "")),
                team_b=event.get("away_team", event.get("team_b", "")),
                commence_time=event.get("commence_time", ""),
                game_title=game_key,
                tournament=event.get("tournament", ""),
                format=event.get("format", "bo3"),
            )
            # Parse moneyline
            for market in event.get("markets", []):
                if market.get("key") == "match_winner":
                    outcomes = market.get("outcomes", [])
                    if len(outcomes) >= 2:
                        od.moneyline["team_a"] = outcomes[0].get("price", 0)
                        od.moneyline["team_b"] = outcomes[1].get("price", 0)
                elif market.get("key") == "map_handicap":
                    outcomes = market.get("outcomes", [])
                    if len(outcomes) >= 2:
                        od.map_handicap["team_a_line"] = outcomes[0].get("point", -1.5)
                        od.map_handicap["team_a_odds"] = outcomes[0].get("price", 0)
                        od.map_handicap["team_b_line"] = outcomes[1].get("point", 1.5)
                        od.map_handicap["team_b_odds"] = outcomes[1].get("price", 0)
                elif market.get("key") == "total_maps":
                    outcomes = market.get("outcomes", [])
                    for o in outcomes:
                        if o.get("name") == "Over":
                            od.total_maps["line"] = o.get("point", 2.5)
                            od.total_maps["over_odds"] = o.get("price", 0)
                        elif o.get("name") == "Under":
                            od.total_maps["under_odds"] = o.get("price", 0)

            od.bookmaker_count = event.get("bookmaker_count", 0)
            od.compute_implied_probs()
            if od.moneyline:
                results.append(od)
        except Exception as e:
            log.warning(f"[odds] Failed to parse event: {e}")
            continue

    return results


# --- The Odds API (fallback) ---

def _fetch_the_odds_api(game_key: str) -> list[OddsData]:
    """Fetch odds from The Odds API — fallback, only works for LoL."""
    sport_key = ODDS_API_SPORT_KEYS.get(game_key)
    if not sport_key or not ODDS_API_KEY:
        return []

    try:
        resp = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us,eu",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
            },
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        log.error(f"[odds] The Odds API error: {e}")
        return []

    remaining = resp.headers.get("x-requests-remaining", "?")
    log.info(f"[odds] The Odds API requests remaining: {remaining}")

    results = []
    for event in events:
        od = OddsData(
            team_a=event.get("home_team", ""),
            team_b=event.get("away_team", ""),
            commence_time=event.get("commence_time", ""),
            game_title=game_key,
        )
        h2h_pairs = []  # (team_a_price, team_b_price) per book
        got_display = False
        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}
            # Collect paired h2h odds from ALL bookmakers
            if "h2h" in markets:
                outcomes = markets["h2h"]["outcomes"]
                if len(outcomes) >= 2:
                    h2h_pairs.append((outcomes[0]["price"], outcomes[1]["price"]))
            # Use first book for display odds
            if not got_display:
                if "h2h" in markets:
                    outcomes = markets["h2h"]["outcomes"]
                    if len(outcomes) >= 2:
                        od.moneyline["team_a"] = outcomes[0]["price"]
                        od.moneyline["team_b"] = outcomes[1]["price"]
                if "spreads" in markets:
                    outcomes = markets["spreads"]["outcomes"]
                    if len(outcomes) >= 2:
                        od.map_handicap["team_a_line"] = outcomes[0].get("point", -1.5)
                        od.map_handicap["team_a_odds"] = outcomes[0]["price"]
                        od.map_handicap["team_b_line"] = outcomes[1].get("point", 1.5)
                        od.map_handicap["team_b_odds"] = outcomes[1]["price"]
                if "totals" in markets:
                    for o in markets["totals"]["outcomes"]:
                        if o["name"] == "Over":
                            od.total_maps["line"] = o.get("point", 2.5)
                            od.total_maps["over_odds"] = o["price"]
                        else:
                            od.total_maps["under_odds"] = o["price"]
                if od.moneyline:
                    got_display = True

        # Compute consensus implied probs across ALL bookmakers
        if od.moneyline and h2h_pairs:
            dv_as, dv_bs = [], []
            for ta_price, tb_price in h2h_pairs:
                pa = american_to_implied_prob(ta_price)
                pb = american_to_implied_prob(tb_price)
                da, db = power_devig(pa, pb)
                dv_as.append(da)
                dv_bs.append(db)
            od.implied_probs["ml_team_a"] = round(sum(dv_as) / len(dv_as), 6)
            od.implied_probs["ml_team_b"] = round(sum(dv_bs) / len(dv_bs), 6)
            od.implied_probs["ml_team_a_worst"] = round(max(dv_as), 6)
            od.implied_probs["ml_team_b_worst"] = round(max(dv_bs), 6)
            od.implied_probs["ml_book_count"] = len(dv_as)
            od.bookmaker_count = len(dv_as)
        else:
            od.compute_implied_probs()

        if od.moneyline:
            results.append(od)

    return results


# --- Public API ---

def get_esports_odds(game_key: str) -> list[OddsData]:
    """Fetch esports odds. Tries OddsPapi first, The Odds API fallback for LoL."""
    # Check cache
    cached = _get_cached_odds(game_key)
    if cached is not None:
        return cached

    # Try OddsPapi
    odds = _fetch_oddspapi(game_key)
    if odds:
        _set_cached_odds(game_key, odds)
        log.info(f"[odds] OddsPapi: {len(odds)} matches for {game_key}")
        return odds

    # Fallback: The Odds API (only LoL)
    if game_key in ODDS_API_SPORT_KEYS:
        odds = _fetch_the_odds_api(game_key)
        if odds:
            _set_cached_odds(game_key, odds)
            log.info(f"[odds] The Odds API fallback: {len(odds)} matches for {game_key}")
            return odds

    log.warning(f"[odds] No odds available for {game_key}")
    return []
