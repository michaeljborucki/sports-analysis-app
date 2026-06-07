"""Fetch soccer betting odds from The Odds API."""
from dataclasses import dataclass, field
import logging
import math
import requests
from config import ODDS_API_KEY, ODDS_API_BASE, SUPPORTED_LEAGUES

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
    home: str
    away: str
    commence_time: str
    asian_handicap: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    btts: dict = field(default_factory=dict)
    moneyline_1x2: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def get_soccer_odds(league: str = "MLS") -> list[OddsData]:
    """Fetch soccer odds for a given league."""
    sport_key = SUPPORTED_LEAGUES.get(league)
    if not sport_key:
        logger.warning("Unsupported league: %s", league)
        return []

    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,uk",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Odds API error for %s: %s", league, e)
        return []

    data = resp.json()
    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("[odds] %s: %d games, %s API requests remaining", league, len(data), remaining)

    results = []
    for event in data:
        home_full = event["home_team"]
        away_full = event["away_team"]

        od = OddsData(home=home_full, away=away_full, commence_time=event["commence_time"])

        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets:
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == home_full:
                        od.moneyline_1x2["home"] = outcome["price"]
                    elif outcome["name"] == away_full:
                        od.moneyline_1x2["away"] = outcome["price"]
                    elif outcome["name"] == "Draw":
                        od.moneyline_1x2["draw"] = outcome["price"]

            if "spreads" in markets:
                for outcome in markets["spreads"]["outcomes"]:
                    if outcome["name"] == home_full:
                        od.asian_handicap["home"] = outcome.get("point", -0.5)
                        od.asian_handicap["home_odds"] = outcome["price"]
                    else:
                        od.asian_handicap["away"] = outcome.get("point", 0.5)
                        od.asian_handicap["away_odds"] = outcome["price"]

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        od.total["line"] = outcome.get("point", 2.5)
                        od.total["over_odds"] = outcome["price"]
                    else:
                        od.total["under_odds"] = outcome["price"]

            if "btts" in markets:
                for outcome in markets["btts"]["outcomes"]:
                    if outcome["name"] == "Yes":
                        od.btts["yes_odds"] = outcome["price"]
                    else:
                        od.btts["no_odds"] = outcome["price"]

            if od.moneyline_1x2:
                break

        # Collect per-book entries — keyed by LINE so we can devig only within
        # matching-line groups. Different books offer different AH/total lines;
        # averaging devigged pairs across lines mixes distributions.
        ah_by_line: dict[float, list[tuple[int, int]]] = {}
        total_by_line: dict[float, list[tuple[int, int]]] = {}
        for bk in event.get("bookmakers", []):
            bk_markets = {m["key"]: m for m in bk.get("markets", [])}
            if "spreads" in bk_markets:
                h_price = a_price = None
                h_line = a_line = None
                for outcome in bk_markets["spreads"]["outcomes"]:
                    if outcome["name"] == home_full:
                        h_price = outcome["price"]
                        h_line = outcome.get("point")
                    else:
                        a_price = outcome["price"]
                        a_line = outcome.get("point")
                if (h_price is not None and a_price is not None
                        and h_line is not None and a_line is not None
                        and abs(h_line + a_line) < 1e-6):  # mirror check
                    ah_by_line.setdefault(float(h_line), []).append((h_price, a_price))
            if "totals" in bk_markets:
                ov_price = un_price = None
                line = None
                for outcome in bk_markets["totals"]["outcomes"]:
                    pt = outcome.get("point")
                    if outcome["name"] == "Over":
                        ov_price = outcome["price"]
                        line = pt if pt is not None else line
                    else:
                        un_price = outcome["price"]
                        line = pt if pt is not None else line
                if ov_price is not None and un_price is not None and line is not None:
                    total_by_line.setdefault(float(line), []).append((ov_price, un_price))

        # Mode-line consensus: pick the line with the most bookmakers, devig
        # within that group only.
        if ah_by_line:
            mode_line = max(ah_by_line, key=lambda k: len(ah_by_line[k]))
            pairs = ah_by_line[mode_line]
            dv_homes, dv_aways, h_prices, a_prices = [], [], [], []
            for h_price, a_price in pairs:
                h = american_to_implied_prob(h_price)
                a = american_to_implied_prob(a_price)
                dh, da = power_devig(h, a)
                dv_homes.append(dh)
                dv_aways.append(da)
                h_prices.append(h_price)
                a_prices.append(a_price)
            # Override od.asian_handicap with the mode-line consensus so edge
            # detection and the bet side label both use the same line.
            od.asian_handicap = {
                "home": mode_line,
                "away": round(-mode_line, 2),
                "home_odds": int(sorted(h_prices)[len(h_prices) // 2]),  # median
                "away_odds": int(sorted(a_prices)[len(a_prices) // 2]),
            }
            od.implied_probs["ah_home"] = round(sum(dv_homes) / len(dv_homes), 6)
            od.implied_probs["ah_away"] = round(sum(dv_aways) / len(dv_aways), 6)
            od.implied_probs["ah_home_worst"] = round(max(dv_homes), 6)
            od.implied_probs["ah_away_worst"] = round(max(dv_aways), 6)
            od.implied_probs["ah_book_count"] = len(dv_homes)
            od.implied_probs["ah_line"] = mode_line
            od.implied_probs["ah_lines_seen"] = len(ah_by_line)
            logger.debug("AH consensus: line=%s books=%d (of %d distinct lines)",
                         mode_line, len(dv_homes), len(ah_by_line))

        if total_by_line:
            mode_line = max(total_by_line, key=lambda k: len(total_by_line[k]))
            pairs = total_by_line[mode_line]
            dv_overs, dv_unders, ov_prices, un_prices = [], [], [], []
            for ov_price, un_price in pairs:
                o = american_to_implied_prob(ov_price)
                u = american_to_implied_prob(un_price)
                do, du = power_devig(o, u)
                dv_overs.append(do)
                dv_unders.append(du)
                ov_prices.append(ov_price)
                un_prices.append(un_price)
            od.total = {
                "line": mode_line,
                "over_odds": int(sorted(ov_prices)[len(ov_prices) // 2]),
                "under_odds": int(sorted(un_prices)[len(un_prices) // 2]),
            }
            od.implied_probs["over"] = round(sum(dv_overs) / len(dv_overs), 6)
            od.implied_probs["under"] = round(sum(dv_unders) / len(dv_unders), 6)
            od.implied_probs["over_worst"] = round(max(dv_overs), 6)
            od.implied_probs["under_worst"] = round(max(dv_unders), 6)
            od.implied_probs["total_book_count"] = len(dv_overs)
            od.implied_probs["total_line"] = mode_line
            od.implied_probs["total_lines_seen"] = len(total_by_line)
            logger.debug("Total consensus: line=%s books=%d (of %d distinct lines)",
                         mode_line, len(dv_overs), len(total_by_line))

        # Estimate BTTS using Poisson model from scoring rates
        if not od.btts or od.btts.get("estimated"):
            from scrapers.team_stats import _load_standings, _find_stat
            entries = _load_standings(league)

            home_gf_pm = away_gf_pm = 1.3  # defaults
            home_ga_pm = away_ga_pm = 1.3

            for entry in entries:
                team_data = entry.get("team", {})
                stats = entry.get("stats", [])
                gp = int(_find_stat(stats, "gamesPlayed", 1)) or 1

                if team_data.get("displayName") == home_full:
                    home_gf_pm = int(_find_stat(stats, "pointsFor")) / gp
                    home_ga_pm = int(_find_stat(stats, "pointsAgainst")) / gp
                elif team_data.get("displayName") == away_full:
                    away_gf_pm = int(_find_stat(stats, "pointsFor")) / gp
                    away_ga_pm = int(_find_stat(stats, "pointsAgainst")) / gp

            # Expected goals for each team in this matchup
            home_expected = (home_gf_pm + away_ga_pm) / 2
            away_expected = (away_gf_pm + home_ga_pm) / 2

            # P(team scores >= 1) = 1 - P(Poisson(lambda) = 0) = 1 - e^(-lambda)
            p_home_scores = 1 - math.exp(-home_expected)
            p_away_scores = 1 - math.exp(-away_expected)
            btts_yes_est = round(p_home_scores * p_away_scores, 4)
            btts_yes_est = min(max(btts_yes_est, 0.30), 0.80)

            if btts_yes_est >= 0.5:
                yes_odds = int(-100 * btts_yes_est / (1 - btts_yes_est))
                no_odds = int(100 * (1 - btts_yes_est) / btts_yes_est)
            else:
                yes_odds = int(100 * (1 - btts_yes_est) / btts_yes_est)
                no_odds = int(-100 * btts_yes_est / (1 - btts_yes_est))

            od.btts = {"yes_odds": yes_odds, "no_odds": no_odds, "estimated": True}
            od.implied_probs["btts_yes"] = btts_yes_est
            od.implied_probs["btts_no"] = round(1 - btts_yes_est, 4)
            logger.debug("BTTS Poisson: %s vs %s = %.2f (home_exp=%.2f, away_exp=%.2f)",
                        home_full, away_full, btts_yes_est, home_expected, away_expected)

        if od.btts and not od.btts.get("estimated"):
            yes_imp = american_to_implied_prob(od.btts.get("yes_odds", -110))
            no_imp = american_to_implied_prob(od.btts.get("no_odds", -110))
            total_prob = yes_imp + no_imp
            if total_prob > 0:
                od.implied_probs["btts_yes"] = yes_imp / total_prob
                od.implied_probs["btts_no"] = no_imp / total_prob

        results.append(od)

    return results
