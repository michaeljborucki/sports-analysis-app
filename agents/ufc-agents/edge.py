"""Edge detection and Kelly criterion sizing for UFC bet types."""
import logging
from config import EDGE_THRESHOLDS, KELLY_FRACTION
from scrapers.odds import american_to_implied_prob, power_devig

logger = logging.getLogger("mirofish.edge")


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


def dynamic_threshold(base_threshold: float, confidence: float) -> float:
    """Adjust edge threshold based on model confidence (0-1 numeric).

    High confidence (>0.75) → lower bar (reward certainty)
    Low confidence (<0.50) → higher bar (penalize uncertainty)
    """
    if confidence >= 0.80:
        return base_threshold * 0.75   # 25% easier
    elif confidence >= 0.65:
        return base_threshold * 0.90   # 10% easier
    elif confidence <= 0.40:
        return base_threshold * 1.50   # 50% harder
    elif confidence <= 0.55:
        return base_threshold * 1.25   # 25% harder
    return base_threshold              # Medium confidence = baseline


def kelly_with_confidence(prob: float, decimal_odds: float,
                          confidence: float, base_fraction: float) -> float:
    """Kelly criterion scaled by model confidence.

    Args:
        prob: Estimated win probability
        decimal_odds: Decimal odds
        confidence: Model confidence 0-1
        base_fraction: Base Kelly fraction (e.g., 0.125)
    """
    raw_kelly = kelly_criterion(prob, decimal_odds)

    # Scale fraction by confidence
    if confidence >= 0.80:
        fraction = base_fraction * 1.40   # High confidence → more aggressive
    elif confidence >= 0.65:
        fraction = base_fraction * 1.15
    elif confidence <= 0.40:
        fraction = base_fraction * 0.60   # Low confidence → conservative
    elif confidence <= 0.55:
        fraction = base_fraction * 0.80
    else:
        fraction = base_fraction

    return max(0, round(raw_kelly * fraction, 4))


def _passes_worst_case_filter(sim_prob: float, raw_own: float, raw_other: float) -> tuple[bool, float]:
    """Worst-case devig: assumes all vig is assigned to our side."""
    worst_case_implied = 1 - raw_other
    worst_case_edge = sim_prob - worst_case_implied
    return worst_case_edge > 0, round(worst_case_edge, 4)


def check_moneyline_edge(sim: dict, odds: dict) -> dict | None:
    """Check for moneyline value on either fighter."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    # Support both numeric (0.65) and categorical ("medium") confidence
    raw_conf = ml_pred.get("confidence", 0.5)
    if isinstance(raw_conf, str):
        confidence = {"low": 0.35, "medium": 0.55, "high": 0.80}.get(raw_conf, 0.55)
    else:
        confidence = float(raw_conf)

    threshold = dynamic_threshold(EDGE_THRESHOLDS["moneyline"], confidence)

    a_prob = ml_pred.get("fighter_a_win_prob", 0)
    a_implied = odds.get("implied_probs", {}).get("fighter_a", 0)
    a_edge = a_prob - a_implied

    b_prob = ml_pred.get("fighter_b_win_prob", 0)
    b_implied = odds.get("implied_probs", {}).get("fighter_b", 0)
    b_edge = b_prob - b_implied

    raw_a = american_to_implied_prob(ml_odds["fighter_a"])
    raw_b = american_to_implied_prob(ml_odds["fighter_b"])

    if a_edge >= threshold and a_edge >= b_edge:
        passes, wc_edge = _passes_worst_case_filter(a_prob, raw_a, raw_b)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["fighter_a"])
        return {
            "bet_type": "moneyline",
            "side": "fighter_a",
            "odds": ml_odds["fighter_a"],
            "sim_prob": a_prob,
            "market_prob": a_implied,
            "edge": round(a_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_with_confidence(a_prob, dec, confidence, KELLY_FRACTION),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif b_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(b_prob, raw_b, raw_a)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["fighter_b"])
        return {
            "bet_type": "moneyline",
            "side": "fighter_b",
            "odds": ml_odds["fighter_b"],
            "sim_prob": b_prob,
            "market_prob": b_implied,
            "edge": round(b_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_with_confidence(b_prob, dec, confidence, KELLY_FRACTION),
            "confidence": ml_pred.get("confidence", "medium"),
        }

    return None


def check_total_rounds_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total rounds (over/under) value."""
    tr_pred = sim.get("predictions", {}).get("total_rounds", {})
    tr_odds = odds.get("total_rounds", {})
    if not tr_pred or not tr_odds:
        return None

    # Support both numeric (0.65) and categorical ("medium") confidence
    raw_conf = tr_pred.get("confidence", 0.5)
    if isinstance(raw_conf, str):
        confidence = {"low": 0.35, "medium": 0.55, "high": 0.80}.get(raw_conf, 0.55)
    else:
        confidence = float(raw_conf)

    threshold = dynamic_threshold(EDGE_THRESHOLDS["total_rounds"], confidence)

    over_prob = tr_pred.get("over_prob", 0)
    under_prob = tr_pred.get("under_prob", 0)

    over_odds = tr_odds.get("over_odds", -110)
    under_odds = tr_odds.get("under_odds", -110)
    raw_o = american_to_implied_prob(over_odds)
    raw_u = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_o, raw_u)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    line = tr_odds.get("line", "?")

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_o, raw_u)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total_rounds",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_with_confidence(over_prob, dec, confidence, KELLY_FRACTION),
            "confidence": tr_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_u, raw_o)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total_rounds",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_with_confidence(under_prob, dec, confidence, KELLY_FRACTION),
            "confidence": tr_pred.get("confidence", "medium"),
        }

    return None


def check_method_edge(sim: dict, odds: dict) -> dict | None:
    """Check for method-of-victory value (KO/TKO, Submission, Decision)."""
    method_pred = sim.get("predictions", {}).get("method", {})
    method_odds = odds.get("method_odds", {})
    if not method_pred or not method_odds:
        return None

    # Support both numeric (0.65) and categorical ("medium") confidence
    raw_conf = method_pred.get("confidence", 0.5)
    if isinstance(raw_conf, str):
        confidence = {"low": 0.35, "medium": 0.55, "high": 0.80}.get(raw_conf, 0.55)
    else:
        confidence = float(raw_conf)

    threshold = dynamic_threshold(EDGE_THRESHOLDS["method"], confidence)

    methods = {
        "ko_tko": method_pred.get("ko_tko_prob", 0),
        "submission": method_pred.get("submission_prob", 0),
        "decision": method_pred.get("decision_prob", 0),
    }

    best_method = None
    best_edge = 0

    for method, sim_prob in methods.items():
        market_odds = method_odds.get(method)
        if market_odds is None:
            continue
        implied = american_to_implied_prob(market_odds)
        edge = sim_prob - implied
        if edge >= threshold and edge > best_edge:
            best_edge = edge
            best_method = method

    if best_method is None:
        return None

    dec = american_to_decimal(method_odds[best_method])
    return {
        "bet_type": "method",
        "side": best_method,
        "odds": method_odds[best_method],
        "sim_prob": methods[best_method],
        "market_prob": round(american_to_implied_prob(method_odds[best_method]), 4),
        "edge": round(best_edge, 4),
        "kelly_pct": kelly_with_confidence(methods[best_method], dec, confidence, KELLY_FRACTION),
        "confidence": method_pred.get("confidence", "medium"),
    }


def analyze_all_edges(sim: dict, odds: dict) -> list[dict]:
    """Run all edge checks for a single fight. Returns 0-3 bet signals with correlation adjustment."""
    bets = []
    checkers = [
        ("moneyline", check_moneyline_edge),
        ("total_rounds", check_total_rounds_edge),
        ("method", check_method_edge),
    ]

    for name, checker in checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f sim=%.4f mkt=%.4f kelly=%.4f",
                         name, result["side"], result["edge"],
                         result.get("sim_prob", 0), result.get("market_prob", 0),
                         result["kelly_pct"])
        else:
            logger.debug("Edge check %s: no value", name)

    # Correlation adjustment: moneyline + method share ~60% correlation
    has_ml = any(b["bet_type"] == "moneyline" for b in bets)
    has_method = any(b["bet_type"] == "method" for b in bets)
    if has_ml and has_method:
        for b in bets:
            if b["bet_type"] == "method":
                original = b["kelly_pct"]
                b["kelly_pct"] = round(original * 0.65, 4)  # 35% reduction
                logger.info("Correlation adjustment: method kelly %.4f → %.4f (correlated with ML)",
                           original, b["kelly_pct"])

    # Odds range filter: skip extreme chalk/longshots
    filtered = []
    for b in bets:
        american = b.get("odds", 0)
        if american < -500:
            logger.info("Filtered %s: odds %d too extreme (heavy chalk)", b["bet_type"], american)
            continue
        if american > 700:
            logger.info("Filtered %s: odds %d too extreme (longshot)", b["bet_type"], american)
            continue
        filtered.append(b)
    bets = filtered

    # Max bet cap: 5% single, 10% per fight
    MAX_SINGLE = 0.05
    MAX_TOTAL = 0.10
    for b in bets:
        if b["kelly_pct"] > MAX_SINGLE:
            logger.info("Kelly capped: %s %.4f → %.4f", b["bet_type"], b["kelly_pct"], MAX_SINGLE)
            b["kelly_pct"] = MAX_SINGLE

    total_kelly = sum(b["kelly_pct"] for b in bets)
    if total_kelly > MAX_TOTAL and bets:
        scale = MAX_TOTAL / total_kelly
        for b in bets:
            b["kelly_pct"] = round(b["kelly_pct"] * scale, 4)
        logger.info("Total Kelly capped: %.4f → %.4f", total_kelly, MAX_TOTAL)

    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets
