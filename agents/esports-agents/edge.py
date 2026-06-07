"""Edge detection and Kelly criterion sizing for esports betting."""
import logging
from config import KELLY_FRACTION
from scrapers.odds import american_to_implied_prob, power_devig, OddsData

log = logging.getLogger(__name__)


def kelly_criterion(prob: float, american_odds: int) -> float:
    """Quarter-Kelly bet sizing.

    Returns fraction of bankroll to bet (0.0 if negative edge).
    """
    if american_odds > 0:
        b = american_odds / 100
    else:
        b = 100 / abs(american_odds)
    q = 1 - prob
    kelly = (b * prob - q) / b
    if kelly <= 0:
        return 0.0
    return KELLY_FRACTION * kelly


def _passes_worst_case_filter(sim_prob: float, raw_own: float, raw_other: float) -> tuple[bool, float]:
    """Worst-case devig: assumes all vig is assigned to our side."""
    worst_case_implied = 1 - raw_other
    worst_case_edge = sim_prob - worst_case_implied
    return worst_case_edge > 0, round(worst_case_edge, 4)


def _build_bet(side, odds_price, sim_prob, market_prob, edge, confidence, worst_case_edge=None):
    """Build a bet signal dict."""
    result = {
        "side": side,
        "odds": odds_price,
        "sim_prob": round(sim_prob, 4),
        "market_prob": round(market_prob, 4),
        "edge": round(edge, 4),
        "kelly_pct": round(kelly_criterion(sim_prob, odds_price), 4),
        "confidence": confidence or "medium",
    }
    if worst_case_edge is not None:
        result["worst_case_edge"] = worst_case_edge
    return result


def check_moneyline_edge(sim: dict, odds: OddsData, threshold: float):
    """Compare sim prob vs implied prob for match winner."""
    if not odds.implied_probs:
        return None
    ml_a_implied = odds.implied_probs.get("ml_team_a", 0.5)
    ml_b_implied = odds.implied_probs.get("ml_team_b", 0.5)

    team_a_prob = sim.get("team_a_win_prob", 0.5)
    team_b_prob = sim.get("team_b_win_prob", 0.5)

    team_a_edge = team_a_prob - ml_a_implied
    team_b_edge = team_b_prob - ml_b_implied

    raw_a = american_to_implied_prob(odds.moneyline.get("team_a", -110))
    raw_b = american_to_implied_prob(odds.moneyline.get("team_b", 110))

    if team_a_edge >= threshold and team_a_edge >= team_b_edge:
        passes, wc_edge = _passes_worst_case_filter(team_a_prob, raw_a, raw_b)
        if not passes:
            return None
        return _build_bet("team_a", odds.moneyline.get("team_a", -110),
                          team_a_prob, ml_a_implied, team_a_edge, sim.get("confidence"), wc_edge)
    elif team_b_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(team_b_prob, raw_b, raw_a)
        if not passes:
            return None
        return _build_bet("team_b", odds.moneyline.get("team_b", 110),
                          team_b_prob, ml_b_implied, team_b_edge, sim.get("confidence"), wc_edge)
    return None


def check_map_handicap_edge(sim: dict, odds: OddsData, threshold: float):
    """Favorite cover prob vs implied from handicap odds."""
    hc = odds.map_handicap
    if not hc or "team_a_odds" not in hc:
        return None

    fav_raw = american_to_implied_prob(hc.get("team_a_odds", -110))
    dog_raw = american_to_implied_prob(hc.get("team_b_odds", -110))
    fav_implied, dog_implied = power_devig(fav_raw, dog_raw)

    fav_prob = sim.get("favorite_cover_prob", 0.5)
    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    if fav_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(fav_prob, fav_raw, dog_raw)
        if not passes:
            return None
        return _build_bet("favorite", hc["team_a_odds"],
                          fav_prob, fav_implied, fav_edge, sim.get("confidence"), wc_edge)
    elif dog_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(1 - fav_prob, dog_raw, fav_raw)
        if not passes:
            return None
        return _build_bet("underdog", hc["team_b_odds"],
                          1 - fav_prob, dog_implied, dog_edge, sim.get("confidence"), wc_edge)
    return None


def check_total_maps_edge(sim: dict, odds: OddsData, threshold: float):
    """Over/under on total maps played."""
    tm = odds.total_maps
    if not tm or "over_odds" not in tm:
        return None

    over_raw = american_to_implied_prob(tm.get("over_odds", -110))
    under_raw = american_to_implied_prob(tm.get("under_odds", -110))
    over_implied, under_implied = power_devig(over_raw, under_raw)

    over_prob = sim.get("over_prob", 0.5)
    under_prob = sim.get("under_prob", 0.5)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, over_raw, under_raw)
        if not passes:
            return None
        return _build_bet("over", tm["over_odds"],
                          over_prob, over_implied, over_edge, sim.get("confidence"), wc_edge)
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, under_raw, over_raw)
        if not passes:
            return None
        return _build_bet("under", tm["under_odds"],
                          under_prob, under_implied, under_edge, sim.get("confidence"), wc_edge)
    return None


def analyze_all_edges(sim: dict, odds: OddsData, format: str, game_config) -> list[dict]:
    """Run all edge checks for esports bet types.

    Args:
        sim: Ensemble simulation result with nested predictions per bet type
        odds: OddsData with implied probs
        format: "bo1", "bo3", or "bo5"
        game_config: Game module config with EDGE_THRESHOLDS
    """
    thresholds = game_config.EDGE_THRESHOLDS.get(format, {})

    checkers = [
        ("moneyline", check_moneyline_edge),
        ("map_handicap", check_map_handicap_edge),
        ("total_maps", check_total_maps_edge),
    ]

    bets = []
    for bet_type, checker_fn in checkers:
        if bet_type not in thresholds:
            continue  # Skip N/A (e.g., map_handicap in Bo1)
        sim_section = sim.get(bet_type, {})
        if not sim_section:
            continue
        result = checker_fn(sim_section, odds, thresholds[bet_type])
        if result:
            result["bet_type"] = bet_type
            bets.append(result)
            log.debug("Edge found: %s %s | edge=%.3f sim=%.4f mkt=%.4f kelly=%.4f",
                      bet_type, result["side"], result["edge"],
                      result.get("sim_prob", 0), result.get("market_prob", 0),
                      result["kelly_pct"])
        else:
            log.debug("Edge check %s: no value (threshold=%.3f)",
                      bet_type, thresholds[bet_type])

    log.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets
