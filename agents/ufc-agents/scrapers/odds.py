"""UFC/MMA odds scraper via The Odds API."""
from dataclasses import dataclass, field
import logging
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY

logger = logging.getLogger("mirofish.scrapers.odds")


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
    fighter_a: str
    fighter_b: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    total_rounds: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)
    method_odds: dict = field(default_factory=dict)   # {ko_tko: int, submission: int, decision: int}


def get_ufc_odds(date: str = None) -> list[OddsData]:
    """Fetch UFC/MMA odds from The Odds API for h2h and totals markets."""
    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,totals",
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("[odds] %d fights found, API requests remaining: %s", len(data), remaining)

    if not data:
        return []

    results = []
    for event in data:
        fighter_a = event["home_team"]
        fighter_b = event["away_team"]

        odds_data = OddsData(
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            commence_time=event["commence_time"],
        )

        # Collect odds from ALL bookmakers
        all_ml_a = []
        all_ml_b = []
        h2h_pairs = []  # (fighter_a_price, fighter_b_price) per book
        all_tr_line = []
        all_tr_over = []
        all_tr_under = []

        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets:
                fa, fb = None, None
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == fighter_a:
                        all_ml_a.append(outcome["price"])
                        fa = outcome["price"]
                    else:
                        all_ml_b.append(outcome["price"])
                        fb = outcome["price"]
                if fa is not None and fb is not None:
                    h2h_pairs.append((fa, fb))

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        if "point" in outcome:
                            all_tr_line.append(outcome["point"])
                        all_tr_over.append(outcome["price"])
                    else:
                        all_tr_under.append(outcome["price"])

        # Use median odds for display (robustness against outliers)
        def _median(values):
            if not values:
                return None
            s = sorted(values)
            mid = len(s) // 2
            return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) // 2

        if all_ml_a:
            odds_data.moneyline["fighter_a"] = _median(all_ml_a)
        if all_ml_b:
            odds_data.moneyline["fighter_b"] = _median(all_ml_b)
        if all_tr_over:
            odds_data.total_rounds["over_odds"] = _median(all_tr_over)
        if all_tr_under:
            odds_data.total_rounds["under_odds"] = _median(all_tr_under)
        if all_tr_line:
            odds_data.total_rounds["line"] = all_tr_line[0]  # Line is same across books

        # Store bookmaker count for quality signal
        odds_data.moneyline["num_books"] = len(all_ml_a)

        # Compute consensus implied probs by averaging power-devigged
        # probabilities across ALL bookmakers
        if odds_data.moneyline and h2h_pairs:
            dv_as, dv_bs = [], []
            for fa_price, fb_price in h2h_pairs:
                pa = american_to_implied_prob(fa_price)
                pb = american_to_implied_prob(fb_price)
                da, db = power_devig(pa, pb)
                dv_as.append(da)
                dv_bs.append(db)
            odds_data.implied_probs["fighter_a"] = round(sum(dv_as) / len(dv_as), 6)
            odds_data.implied_probs["fighter_b"] = round(sum(dv_bs) / len(dv_bs), 6)
            odds_data.implied_probs["fighter_a_worst"] = round(max(dv_as), 6)
            odds_data.implied_probs["fighter_b_worst"] = round(max(dv_bs), 6)
            odds_data.implied_probs["ml_book_count"] = len(dv_as)

        results.append(odds_data)

    return results
