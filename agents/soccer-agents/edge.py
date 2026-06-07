"""Edge detection and Kelly criterion sizing for soccer bet types."""
import logging
import math
from config import EDGE_THRESHOLDS, KELLY_FRACTION
from scrapers.odds import american_to_implied_prob, power_devig

logger = logging.getLogger("mirofish.edge")

# Empirical correlations for same-match bets (soccer-specific). Total and BTTS
# both load on the latent "match goal count" factor, so they're strongly tied.
# AH correlates with total only when the favorite scores in a blowout pattern,
# so it's moderate. Revisit these priors once the backtest harness exists.
SAME_MATCH_CORRELATION = {
    frozenset({"asian_handicap", "total"}): 0.40,
    frozenset({"asian_handicap", "btts"}): 0.30,
    frozenset({"total", "btts"}): 0.70,
}


def apply_correlation_penalty(bets: list[dict]) -> list[dict]:
    """Scale Kelly stakes for correlated same-match bets.

    Formula: kelly_i /= sqrt(1 + sum_{j != i} rho(i, j)). Keeps combined exposure
    close to a single ⅛-Kelly bet when all three slots fire together.
    """
    if len(bets) <= 1:
        return bets

    for i, bet in enumerate(bets):
        rho_sum = 0.0
        for j, other in enumerate(bets):
            if i == j:
                continue
            key = frozenset({bet["bet_type"], other["bet_type"]})
            rho_sum += SAME_MATCH_CORRELATION.get(key, 0.0)
        scale = 1.0 / math.sqrt(1.0 + rho_sum)
        original = bet.get("kelly_pct", 0)
        bet["kelly_pct_raw"] = original
        bet["correlation_scale"] = round(scale, 4)
        bet["kelly_pct"] = round(original * scale, 4)
    return bets


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds < 0:
        return round(100 / abs(odds) + 1, 4)
    return round(odds / 100 + 1, 4)


def kelly_criterion(prob: float, decimal_odds: float) -> float:
    """Calculate Kelly fraction. Returns 0 if no edge."""
    b = decimal_odds - 1
    q = 1 - prob
    if b <= 0:
        return 0
    kelly = (b * prob - q) / b
    return max(0, round(kelly, 4))


def _passes_worst_case_filter(sim_prob: float, raw_own: float, raw_other: float) -> tuple[bool, float]:
    """Worst-case devig: assumes all vig is assigned to our side."""
    worst_case_implied = 1 - raw_other
    worst_case_edge = sim_prob - worst_case_implied
    return worst_case_edge > 0, round(worst_case_edge, 4)


def check_asian_handicap_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Asian Handicap value on either side."""
    ah_pred = sim.get("predictions", {}).get("asian_handicap", {})
    ah_odds = odds.get("asian_handicap", {})
    if not ah_pred or not ah_odds:
        return None

    threshold = EDGE_THRESHOLDS["asian_handicap"]

    home_prob = ah_pred.get("home_cover_prob", 0)
    away_prob = ah_pred.get("away_cover_prob", 0)

    home_implied = odds.get("implied_probs", {}).get("ah_home", 0)
    away_implied = odds.get("implied_probs", {}).get("ah_away", 0)

    # If implied probs not pre-computed, compute from odds using power devig
    if not home_implied and ah_odds.get("home_odds"):
        h_imp = american_to_implied_prob(ah_odds["home_odds"])
        a_imp = american_to_implied_prob(ah_odds["away_odds"])
        home_implied, away_implied = power_devig(h_imp, a_imp)

    home_edge = home_prob - home_implied
    away_edge = away_prob - away_implied

    home_point = ah_odds.get("home", -0.5)
    away_point = ah_odds.get("away", 0.5)

    raw_h = american_to_implied_prob(ah_odds.get("home_odds", -110))
    raw_a = american_to_implied_prob(ah_odds.get("away_odds", -110))

    if home_edge >= threshold and home_edge >= away_edge:
        passes, wc_edge = _passes_worst_case_filter(home_prob, raw_h, raw_a)
        if not passes:
            return None
        dec = american_to_decimal(ah_odds["home_odds"])
        return {
            "bet_type": "asian_handicap",
            "side": f"home {home_point}",
            "odds": ah_odds["home_odds"],
            "sim_prob": home_prob,
            "market_prob": round(home_implied, 4),
            "edge": round(home_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": round(kelly_criterion(home_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ah_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(away_prob, raw_a, raw_h)
        if not passes:
            return None
        dec = american_to_decimal(ah_odds["away_odds"])
        return {
            "bet_type": "asian_handicap",
            "side": f"away {away_point}",
            "odds": ah_odds["away_odds"],
            "sim_prob": away_prob,
            "market_prob": round(away_implied, 4),
            "edge": round(away_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": round(kelly_criterion(away_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ah_pred.get("confidence", "medium"),
        }

    return None


def check_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total goals (over/under) value."""
    total_pred = sim.get("predictions", {}).get("total", {})
    total_odds = odds.get("total", {})
    if not total_pred or not total_odds:
        return None

    threshold = EDGE_THRESHOLDS["total"]

    over_prob = total_pred.get("over_prob", 0)
    under_prob = total_pred.get("under_prob", 0)

    over_odds = total_odds.get("over_odds", -110)
    under_odds = total_odds.get("under_odds", -110)

    # Use multi-book consensus if available, else power devig
    over_implied = odds.get("implied_probs", {}).get("over", 0)
    under_implied = odds.get("implied_probs", {}).get("under", 0)
    if not over_implied:
        raw_o = american_to_implied_prob(over_odds)
        raw_u = american_to_implied_prob(under_odds)
        over_implied, under_implied = power_devig(raw_o, raw_u)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    line = total_odds.get("line", 2.5)
    raw_o = american_to_implied_prob(over_odds)
    raw_u = american_to_implied_prob(under_odds)

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_o, raw_u)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_u, raw_o)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }

    return None


def check_btts_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Both Teams to Score value."""
    btts_pred = sim.get("predictions", {}).get("btts", {})
    btts_odds = odds.get("btts", {})
    if not btts_pred or not btts_odds:
        return None

    threshold = EDGE_THRESHOLDS["btts"]

    yes_prob = btts_pred.get("btts_yes_prob", 0)
    no_prob = btts_pred.get("btts_no_prob", 0)

    yes_odds = btts_odds.get("yes_odds", -110)
    no_odds = btts_odds.get("no_odds", -110)

    # Use pre-computed implied probs if available, else power devig
    yes_implied = odds.get("implied_probs", {}).get("btts_yes", 0)
    no_implied = odds.get("implied_probs", {}).get("btts_no", 0)
    if not yes_implied:
        raw_y = american_to_implied_prob(yes_odds)
        raw_n = american_to_implied_prob(no_odds)
        yes_implied, no_implied = power_devig(raw_y, raw_n)

    yes_edge = yes_prob - yes_implied
    no_edge = no_prob - no_implied

    raw_y = american_to_implied_prob(yes_odds)
    raw_n = american_to_implied_prob(no_odds)

    if yes_edge >= threshold and yes_edge >= no_edge:
        passes, wc_edge = _passes_worst_case_filter(yes_prob, raw_y, raw_n)
        if not passes:
            return None
        dec = american_to_decimal(yes_odds)
        return {
            "bet_type": "btts",
            "side": "yes",
            "odds": yes_odds,
            "sim_prob": yes_prob,
            "market_prob": round(yes_implied, 4),
            "edge": round(yes_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": round(kelly_criterion(yes_prob, dec) * KELLY_FRACTION, 4),
            "confidence": btts_pred.get("confidence", "medium"),
        }
    elif no_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(no_prob, raw_n, raw_y)
        if not passes:
            return None
        dec = american_to_decimal(no_odds)
        return {
            "bet_type": "btts",
            "side": "no",
            "odds": no_odds,
            "sim_prob": no_prob,
            "market_prob": round(no_implied, 4),
            "edge": round(no_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": round(kelly_criterion(no_prob, dec) * KELLY_FRACTION, 4),
            "confidence": btts_pred.get("confidence", "medium"),
        }

    return None


def analyze_all_edges(sim: dict, odds: dict) -> list[dict]:
    """Run all edge checks for a single match. Returns 0-3 bet signals."""
    bets = []
    checkers = [
        ("asian_handicap", check_asian_handicap_edge),
        ("total", check_total_edge),
        ("btts", check_btts_edge),
    ]

    for name, checker in checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])
        else:
            logger.debug("Edge check %s: no value (threshold=%.3f)",
                         name, EDGE_THRESHOLDS.get(name, 0))

    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    if len(bets) > 1:
        apply_correlation_penalty(bets)
        logger.info(
            "Correlation penalty applied: %s",
            ", ".join(f"{b['bet_type']}={b['correlation_scale']:.2f}x" for b in bets),
        )
    return bets
