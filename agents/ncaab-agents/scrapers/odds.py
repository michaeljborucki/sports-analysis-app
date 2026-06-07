from dataclasses import dataclass, field
from datetime import datetime
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY
from scrapers.odds_feed import (
    FeedUnavailable,
    feed_enabled,
    get_feed_events,
    warn_missing_markets,
)

# Markets the NCAAB pipeline pulls from the feed. Used to warn when the backend
# isn't serving something the agent models.
_EXPECTED_FEED_MARKETS = {
    "h2h", "spreads", "totals",
    "h2h_1st_half", "totals_1st_half", "spreads_1st_half",
}


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method.

    Finds exponent k where prob_a^(1/k) + prob_b^(1/k) = 1.
    More accurate than additive devig because favorites carry more vig
    than underdogs (favorite-longshot bias).

    Returns (fair_prob_a, fair_prob_b) summing to 1.0.
    """
    if prob_a <= 0 or prob_b <= 0:
        total = prob_a + prob_b
        if total <= 0:
            return 0.5, 0.5
        return round(prob_a / total, 4), round(prob_b / total, 4)

    # Binary search for n where p_a^n + p_b^n = 1.
    # n > 1 when overround > 1 (standard vigged market).
    lo, hi = 1.0, 10.0
    for _ in range(100):
        k = (lo + hi) / 2
        total = prob_a ** k + prob_b ** k
        if total > 1.0:
            lo = k
        else:
            hi = k
        if abs(total - 1.0) < 1e-9:
            break

    fair_a = round(prob_a ** k, 4)
    fair_b = round(prob_b ** k, 4)
    return fair_a, fair_b


def worst_case_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Worst-case devig: assume ALL vig is on your side.

    For outcome A: fair_a = 1 - prob_b (raw implied)
    For outcome B: fair_b = 1 - prob_a (raw implied)

    This gives the most conservative estimate. Used as a secondary
    filter — if a bet still shows edge under worst-case, it's robust.

    Returns (worst_case_a, worst_case_b). Note: these do NOT sum to 1.0
    (each is independently conservative).
    """
    return round(1 - prob_b, 4), round(1 - prob_a, 4)


@dataclass
class OddsData:
    home: str
    away: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    spread: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    h1_moneyline: dict = field(default_factory=dict)
    h1_total: dict = field(default_factory=dict)
    h1_spread: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def _team_abbrev(full_name: str) -> str:
    return full_name


def get_ncaab_odds(date: str = None, sport: str = None) -> list[OddsData]:
    """Fetch NCAAB odds for h2h, spreads, totals markets.

    Pulls from the shared backend feed when configured (reusing the betting
    site's live-odds cache, no API spend); otherwise hits The Odds API
    directly.
    """
    if feed_enabled():
        try:
            events = get_feed_events()
            print(f"[odds] Using shared feed ({len(events)} events)")
            warn_missing_markets(events, _EXPECTED_FEED_MARKETS, context="ncaab")
            return _build_ncaab_odds(events)
        except FeedUnavailable as e:
            print(f"[odds] Shared feed unavailable ({e}); falling back to Odds API")

    sport_keys = [sport] if sport else [ODDS_SPORT_KEY]
    markets_options = [
        "h2h,spreads,totals,h2h_1st_half,totals_1st_half,spreads_1st_half",
        "h2h,spreads,totals",
    ]

    resp = None
    for sport_key in sport_keys:
        url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
        for markets in markets_options:
            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": markets,
                "oddsFormat": "american",
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 422 and "1st_half" in markets:
                print("[odds] 1H markets not available, falling back to core markets")
                continue
            resp.raise_for_status()
            break

        data = resp.json()
        if data:
            print(f"[odds] Using {sport_key} ({len(data)} games)")
            break
        else:
            print(f"[odds] No games on {sport_key}, trying next...")

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] API requests remaining: {remaining}")

    return _build_ncaab_odds(data)


def _build_ncaab_odds(events: list[dict]) -> list[OddsData]:
    """Parse raw Odds API events into consensus OddsData. Shared by the
    direct-API and shared-feed paths."""
    results = []
    for event in events:
        home_full = event["home_team"]
        away_full = event["away_team"]
        home = _team_abbrev(home_full)
        away = _team_abbrev(away_full)

        odds_data = OddsData(
            home=home,
            away=away,
            commence_time=event["commence_time"],
        )

        # Collect odds from ALL bookmakers for consensus
        ml_home_prices = []
        ml_away_prices = []
        sp_home_points = []
        sp_home_prices = []
        sp_away_points = []
        sp_away_prices = []
        total_lines = []
        total_over_prices = []
        total_under_prices = []
        h1_ml_home_prices = []
        h1_ml_away_prices = []
        h1_total_lines = []
        h1_total_over_prices = []
        h1_total_under_prices = []
        h1_sp_home_points = []
        h1_sp_home_prices = []
        h1_sp_away_points = []
        h1_sp_away_prices = []

        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets:
                for outcome in markets["h2h"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        ml_home_prices.append(outcome["price"])
                    else:
                        ml_away_prices.append(outcome["price"])

            if "spreads" in markets:
                for outcome in markets["spreads"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        sp_home_points.append(outcome.get("point", -1.5))
                        sp_home_prices.append(outcome["price"])
                    else:
                        sp_away_points.append(outcome.get("point", 1.5))
                        sp_away_prices.append(outcome["price"])

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        total_lines.append(outcome.get("point", 0))
                        total_over_prices.append(outcome["price"])
                    else:
                        total_under_prices.append(outcome["price"])

            if "h2h_1st_half" in markets:
                for outcome in markets["h2h_1st_half"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        h1_ml_home_prices.append(outcome["price"])
                    else:
                        h1_ml_away_prices.append(outcome["price"])

            if "totals_1st_half" in markets:
                for outcome in markets["totals_1st_half"]["outcomes"]:
                    if outcome["name"] == "Over":
                        h1_total_lines.append(outcome.get("point", 0))
                        h1_total_over_prices.append(outcome["price"])
                    else:
                        h1_total_under_prices.append(outcome["price"])

            if "spreads_1st_half" in markets:
                for outcome in markets["spreads_1st_half"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        h1_sp_home_points.append(outcome.get("point", 0))
                        h1_sp_home_prices.append(outcome["price"])
                    else:
                        h1_sp_away_points.append(outcome.get("point", 0))
                        h1_sp_away_prices.append(outcome["price"])

        # Collect paired odds per bookmaker for consensus devig
        h2h_pairs = []  # list of (home_price, away_price) per book
        spread_pairs = []  # list of (home_price, away_price) per book
        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}
            if "h2h" in markets:
                h, a = None, None
                for outcome in markets["h2h"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        h = outcome["price"]
                    else:
                        a = outcome["price"]
                if h is not None and a is not None:
                    h2h_pairs.append((h, a))
            if "spreads" in markets:
                h, a = None, None
                for outcome in markets["spreads"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        h = outcome["price"]
                    else:
                        a = outcome["price"]
                if h is not None and a is not None:
                    spread_pairs.append((h, a))

        # Helper to compute median (more robust than mean for odds)
        def _median(values):
            if not values:
                return None
            s = sorted(values)
            n = len(s)
            if n % 2 == 1:
                return s[n // 2]
            return (s[n // 2 - 1] + s[n // 2]) / 2

        # Build consensus odds from median across bookmakers
        if ml_home_prices and ml_away_prices:
            odds_data.moneyline["home"] = round(_median(ml_home_prices))
            odds_data.moneyline["away"] = round(_median(ml_away_prices))

        if sp_home_prices and sp_away_prices:
            odds_data.spread["home"] = _median(sp_home_points)
            odds_data.spread["home_odds"] = round(_median(sp_home_prices))
            odds_data.spread["away"] = _median(sp_away_points)
            odds_data.spread["away_odds"] = round(_median(sp_away_prices))

        if total_over_prices and total_under_prices:
            odds_data.total["line"] = _median(total_lines)
            odds_data.total["over_odds"] = round(_median(total_over_prices))
            odds_data.total["under_odds"] = round(_median(total_under_prices))

        if h1_ml_home_prices and h1_ml_away_prices:
            odds_data.h1_moneyline["home"] = round(_median(h1_ml_home_prices))
            odds_data.h1_moneyline["away"] = round(_median(h1_ml_away_prices))

        if h1_total_over_prices and h1_total_under_prices:
            odds_data.h1_total["line"] = _median(h1_total_lines)
            odds_data.h1_total["over_odds"] = round(_median(h1_total_over_prices))
            odds_data.h1_total["under_odds"] = round(_median(h1_total_under_prices))

        if h1_sp_home_prices and h1_sp_away_prices:
            odds_data.h1_spread["home"] = _median(h1_sp_home_points)
            odds_data.h1_spread["home_odds"] = round(_median(h1_sp_home_prices))
            odds_data.h1_spread["away"] = _median(h1_sp_away_points)
            odds_data.h1_spread["away_odds"] = round(_median(h1_sp_away_prices))

        # Compute market consensus implied probs by averaging
        # power-devigged probabilities across ALL bookmakers
        if odds_data.moneyline and h2h_pairs:
            dv_homes, dv_aways = [], []
            for h_price, a_price in h2h_pairs:
                h = american_to_implied_prob(h_price)
                a = american_to_implied_prob(a_price)
                dh, da = power_devig(h, a)
                dv_homes.append(dh)
                dv_aways.append(da)
            odds_data.implied_probs["ml_home"] = round(sum(dv_homes) / len(dv_homes), 4)
            odds_data.implied_probs["ml_away"] = round(sum(dv_aways) / len(dv_aways), 4)
            odds_data.implied_probs["ml_home_worst"] = round(max(dv_homes), 4)
            odds_data.implied_probs["ml_away_worst"] = round(max(dv_aways), 4)
            odds_data.implied_probs["ml_book_count"] = len(dv_homes)

        if odds_data.spread and spread_pairs:
            dv_homes, dv_aways = [], []
            for h_price, a_price in spread_pairs:
                h = american_to_implied_prob(h_price)
                a = american_to_implied_prob(a_price)
                dh, da = power_devig(h, a)
                dv_homes.append(dh)
                dv_aways.append(da)
            odds_data.implied_probs["sp_home"] = round(sum(dv_homes) / len(dv_homes), 4)
            odds_data.implied_probs["sp_away"] = round(sum(dv_aways) / len(dv_aways), 4)
            odds_data.implied_probs["sp_home_worst"] = round(max(dv_homes), 4)
            odds_data.implied_probs["sp_away_worst"] = round(max(dv_aways), 4)
            odds_data.implied_probs["sp_book_count"] = len(dv_homes)

        results.append(odds_data)

    return results
