"""Cricket odds scraper using The Odds API."""
import logging
from dataclasses import dataclass, field

import requests

from config import ODDS_API_KEY, ODDS_API_BASE, LEAGUES, TEAM_NAME_TO_ABBREV

logger = logging.getLogger("cricket.scrapers.odds")


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


def _team_abbrev(full_name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(full_name, full_name)


@dataclass
class OddsData:
    team_a: str                              # abbreviation (home team)
    team_b: str                              # abbreviation (away team)
    team_a_full: str                         # full name
    team_b_full: str                         # full name
    moneyline: dict = field(default_factory=dict)   # {"team_a": price, "team_b": price}
    total_runs: dict = field(default_factory=dict)  # {"line": X, "over": price, "under": price}
    implied_probs: dict = field(default_factory=dict)  # {"team_a": prob, "team_b": prob}


def get_cricket_odds(league: str) -> list[OddsData]:
    """Fetch cricket odds from The Odds API for a specific league.

    Args:
        league: League key from LEAGUES dict (e.g. "ipl", "bbl")

    Returns:
        List of OddsData objects, one per upcoming match.
    """
    league_cfg = LEAGUES.get(league)
    if not league_cfg:
        raise ValueError(f"Unknown league: {league}. Valid keys: {list(LEAGUES.keys())}")

    sport_key = league_cfg["odds_key"]
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "uk,eu,au",
        "markets": "h2h,totals",
        "oddsFormat": "american",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("[odds] %s: %d events found, API requests remaining: %s",
                league.upper(), len(data), remaining)

    results = []
    for event in data:
        home_full = event["home_team"]
        away_full = event["away_team"]
        team_a = _team_abbrev(home_full)
        team_b = _team_abbrev(away_full)

        odds_obj = OddsData(
            team_a=team_a,
            team_b=team_b,
            team_a_full=home_full,
            team_b_full=away_full,
        )

        h2h_pairs = []  # (team_a_price, team_b_price) per book
        got_display = False
        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            # Collect paired h2h odds from ALL bookmakers
            if "h2h" in markets:
                ta, tb = None, None
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == home_full:
                        ta = outcome["price"]
                    else:
                        tb = outcome["price"]
                if ta is not None and tb is not None:
                    h2h_pairs.append((ta, tb))

            # Use first bookmaker for display odds
            if not got_display:
                if "h2h" in markets:
                    for outcome in markets["h2h"]["outcomes"]:
                        key = "team_a" if outcome["name"] == home_full else "team_b"
                        odds_obj.moneyline[key] = outcome["price"]

                if "totals" in markets:
                    for outcome in markets["totals"]["outcomes"]:
                        if outcome["name"] == "Over":
                            odds_obj.total_runs["line"] = outcome.get("point", 0)
                            odds_obj.total_runs["over"] = outcome["price"]
                        else:
                            odds_obj.total_runs["under"] = outcome["price"]

                if odds_obj.moneyline:
                    got_display = True

        # Compute consensus implied probs across ALL bookmakers
        if "team_a" in odds_obj.moneyline and "team_b" in odds_obj.moneyline and h2h_pairs:
            dv_as, dv_bs = [], []
            for ta_price, tb_price in h2h_pairs:
                pa = american_to_implied_prob(ta_price)
                pb = american_to_implied_prob(tb_price)
                da, db = power_devig(pa, pb)
                dv_as.append(da)
                dv_bs.append(db)
            odds_obj.implied_probs["team_a"] = round(sum(dv_as) / len(dv_as), 6)
            odds_obj.implied_probs["team_b"] = round(sum(dv_bs) / len(dv_bs), 6)
            odds_obj.implied_probs["team_a_worst"] = round(max(dv_as), 6)
            odds_obj.implied_probs["team_b_worst"] = round(max(dv_bs), 6)
            odds_obj.implied_probs["ml_book_count"] = len(dv_as)

        results.append(odds_obj)

    return results
