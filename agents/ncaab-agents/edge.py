"""Edge detection and Kelly criterion sizing for all 5 bet types."""
import logging
from config import EDGE_THRESHOLDS, KELLY_FRACTION, MAX_ML_ODDS
from scrapers.odds import american_to_implied_prob, power_devig, worst_case_devig

logger = logging.getLogger("mirofish.edge")

# Maximum percentage points a sim_prob can exceed market_prob for underdogs
MAX_UNDERDOG_DEVIATION = 0.10


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds < 0:
        return round(100 / abs(odds) + 1, 4)
    return round(odds / 100 + 1, 4)


def kelly_criterion(prob: float, decimal_odds: float) -> float:
    """Calculate Kelly fraction. Returns 0 if no edge."""
    b = decimal_odds - 1  # net odds
    q = 1 - prob
    if b <= 0:
        return 0
    kelly = (b * prob - q) / b
    return max(0, round(kelly, 4))


def dampen_probability(sim_prob: float, market_prob: float,
                       shrinkage: float = 0.3) -> float:
    """Apply Bayesian shrinkage to pull underdog estimates toward market.

    Only dampens when sim_prob < 0.5 (underdog side). Shrinkage increases
    with how extreme the underdog is (lower market_prob = more dampening).
    Also applies a hard cap: sim_prob cannot exceed market_prob by more
    than MAX_UNDERDOG_DEVIATION.

    Formula: dampened = sim_prob * (1 - effective_shrinkage) + market_prob * effective_shrinkage
    where effective_shrinkage scales up for extreme underdogs.
    """
    if sim_prob >= 0.5:
        return sim_prob

    # Hard cap: never deviate more than MAX_UNDERDOG_DEVIATION from market
    capped = min(sim_prob, market_prob + MAX_UNDERDOG_DEVIATION)

    # Scale shrinkage: more dampening for extreme underdogs
    # market_prob of 0.10 → 1.5x shrinkage, market_prob of 0.40 → 0.75x shrinkage
    extremity = max(0.5, min(2.0, 1.0 - (market_prob - 0.25) * 2))
    effective = min(shrinkage * extremity, 0.6)  # cap at 60% shrinkage

    return round(capped * (1 - effective) + market_prob * effective, 4)


def dampen_total_probability(sim_prob: float, shrinkage: float = 0.25) -> float:
    """Apply shrinkage to total (over/under) probabilities toward the market prior of 0.50.

    LLMs systematically overestimate totals. This pulls extreme over/under
    probabilities back toward 50/50, reducing phantom edges.

    A shrinkage of 0.25 means: dampened = sim_prob * 0.75 + 0.50 * 0.25
    """
    return round(sim_prob * (1 - shrinkage) + 0.50 * shrinkage, 4)


def check_moneyline_edge(sim: dict, odds: dict) -> dict | None:
    """Check for moneyline value on either side."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = EDGE_THRESHOLDS["moneyline"]

    # Reject heavy underdogs — LLMs overestimate their chances, creating phantom edges
    home_american = ml_odds.get("home", 0)
    away_american = ml_odds.get("away", 0)

    # Check home
    home_prob = ml_pred.get("home_win_prob", 0)
    home_implied = odds.get("implied_probs", {}).get("ml_home", 0)

    # Check away
    away_prob = ml_pred.get("away_win_prob", 0)
    away_implied = odds.get("implied_probs", {}).get("ml_away", 0)

    # Apply underdog dampening to pull LLM estimates toward market
    home_prob = dampen_probability(home_prob, home_implied)
    away_prob = dampen_probability(away_prob, away_implied)

    home_edge = home_prob - home_implied
    away_edge = away_prob - away_implied

    # Take the side with more edge
    if home_edge >= threshold and home_edge >= away_edge and home_american <= MAX_ML_ODDS:
        dec = american_to_decimal(ml_odds["home"])
        return {
            "bet_type": "moneyline",
            "side": "home",
            "odds": ml_odds["home"],
            "sim_prob": home_prob,
            "market_prob": home_implied,
            "edge": round(home_edge, 4),
            "kelly_pct": round(kelly_criterion(home_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold and away_american <= MAX_ML_ODDS:
        dec = american_to_decimal(ml_odds["away"])
        return {
            "bet_type": "moneyline",
            "side": "away",
            "odds": ml_odds["away"],
            "sim_prob": away_prob,
            "market_prob": away_implied,
            "edge": round(away_edge, 4),
            "kelly_pct": round(kelly_criterion(away_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }

    return None


def check_spread_edge(sim: dict, odds: dict) -> dict | None:
    """Check for spread value. Determines favorite by spread point, not position."""
    sp_pred = sim.get("predictions", {}).get("spread", {})
    sp_odds = odds.get("spread", {})
    if not sp_pred or not sp_odds:
        return None

    threshold = EDGE_THRESHOLDS["spread"]
    fav_prob = sp_pred.get("favorite_cover_prob", 0)

    # Determine which side is the favorite based on spread point
    home_point = sp_odds.get("home", 0)
    home_odds = sp_odds.get("home_odds", -110)
    away_odds = sp_odds.get("away_odds", -110)

    # The side with the negative point is the favorite
    home_is_fav = home_point < 0

    if home_is_fav:
        fav_odds = home_odds
        dog_odds = away_odds
        fav_label = f"home {home_point}"
        dog_label = f"away {sp_odds.get('away', 0)}"
    else:
        fav_odds = away_odds
        dog_odds = home_odds
        fav_label = f"away {sp_odds.get('away', 0)}"
        dog_label = f"home {home_point}"

    fav_raw = american_to_implied_prob(fav_odds)
    dog_raw = american_to_implied_prob(dog_odds)
    fav_implied, dog_implied = power_devig(fav_raw, dog_raw)

    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    if fav_edge >= threshold and fav_edge >= dog_edge:
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "spread",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_implied, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": sp_pred.get("confidence", "medium"),
        }
    elif dog_edge >= threshold:
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "spread",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_implied, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": sp_pred.get("confidence", "medium"),
        }

    return None


def check_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total (over/under) value."""
    total_pred = sim.get("predictions", {}).get("total", {})
    total_odds = odds.get("total", {})
    if not total_pred or not total_odds:
        return None

    threshold = EDGE_THRESHOLDS["total"]

    over_prob = total_pred.get("over_prob", 0)
    under_prob = total_pred.get("under_prob", 0)

    # Dampen total probabilities to counteract systematic LLM over-bias
    over_prob = dampen_total_probability(over_prob)
    under_prob = dampen_total_probability(under_prob)
    # Normalize to preserve complementary invariant after independent dampening
    total_prob = over_prob + under_prob
    if total_prob > 0:
        over_prob = round(over_prob / total_prob, 4)
        under_prob = round(under_prob / total_prob, 4)

    over_odds = total_odds.get("over_odds", -110)
    under_odds = total_odds.get("under_odds", -110)
    over_raw = american_to_implied_prob(over_odds)
    under_raw = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(over_raw, under_raw)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    line = total_odds.get("line", "?")

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }

    return None


def check_h1_ml_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First Half moneyline value."""
    h1_pred = sim.get("predictions", {}).get("first_half", {})
    if not h1_pred:
        return None

    threshold = EDGE_THRESHOLDS["first_half_ml"]

    h1_ml = odds.get("h1_moneyline", {})
    if not h1_ml:
        return None

    home_odds = h1_ml.get("home", -110)
    away_odds = h1_ml.get("away", -110)
    h_raw = american_to_implied_prob(home_odds)
    a_raw = american_to_implied_prob(away_odds)
    h_implied, a_implied = power_devig(h_raw, a_raw)

    h_prob = h1_pred.get("h1_home_win_prob", 0)
    a_prob = h1_pred.get("h1_away_win_prob", 0)
    h_edge = h_prob - h_implied
    a_edge = a_prob - a_implied

    if h_edge >= threshold and h_edge >= a_edge:
        dec = american_to_decimal(home_odds)
        return {
            "bet_type": "first_half_ml",
            "side": "home H1 ML",
            "odds": home_odds,
            "sim_prob": h_prob,
            "market_prob": round(h_implied, 4),
            "edge": round(h_edge, 4),
            "kelly_pct": round(kelly_criterion(h_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }
    elif a_edge >= threshold:
        dec = american_to_decimal(away_odds)
        return {
            "bet_type": "first_half_ml",
            "side": "away H1 ML",
            "odds": away_odds,
            "sim_prob": a_prob,
            "market_prob": round(a_implied, 4),
            "edge": round(a_edge, 4),
            "kelly_pct": round(kelly_criterion(a_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }

    return None


def check_h1_spread_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First Half spread value."""
    h1_pred = sim.get("predictions", {}).get("first_half", {})
    if not h1_pred:
        return None

    h1_sp_odds = odds.get("h1_spread", {})
    if not h1_sp_odds:
        return None

    fav_prob = h1_pred.get("h1_favorite_cover_prob", 0)
    if not fav_prob:
        return None

    threshold = EDGE_THRESHOLDS["first_half_spread"]

    home_point = h1_sp_odds.get("home", 0)
    home_odds = h1_sp_odds.get("home_odds", -110)
    away_odds = h1_sp_odds.get("away_odds", -110)

    home_is_fav = home_point < 0

    if home_is_fav:
        fav_odds = home_odds
        dog_odds = away_odds
        fav_label = f"home H1 {home_point}"
        dog_label = f"away H1 {h1_sp_odds.get('away', 0)}"
    else:
        fav_odds = away_odds
        dog_odds = home_odds
        fav_label = f"away H1 {h1_sp_odds.get('away', 0)}"
        dog_label = f"home H1 {home_point}"

    fav_raw = american_to_implied_prob(fav_odds)
    dog_raw = american_to_implied_prob(dog_odds)
    fav_implied, dog_implied = power_devig(fav_raw, dog_raw)

    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    if fav_edge >= threshold and fav_edge >= dog_edge:
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "first_half_spread",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_implied, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }
    elif dog_edge >= threshold:
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "first_half_spread",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_implied, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }

    return None


def check_h1_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First Half over/under value using projected total vs line heuristic."""
    h1_pred = sim.get("predictions", {}).get("first_half", {})
    if not h1_pred:
        return None

    h1_total_odds = odds.get("h1_total", {})
    if not h1_total_odds:
        return None

    projected = h1_pred.get("h1_projected_total")
    if projected is None:
        return None

    line = h1_total_odds.get("line")
    if line is None:
        return None

    threshold = EDGE_THRESHOLDS["first_half_total"]

    over_odds = h1_total_odds.get("over_odds", -110)
    under_odds = h1_total_odds.get("under_odds", -110)
    over_raw = american_to_implied_prob(over_odds)
    under_raw = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(over_raw, under_raw)

    # Prefer explicit ensemble probabilities over heuristic
    h1_over = h1_pred.get("h1_over_prob")
    h1_under = h1_pred.get("h1_under_prob")
    if h1_over is not None and h1_under is not None:
        over_prob = float(h1_over)
        under_prob = float(h1_under)
    else:
        # Fallback heuristic: estimate probability from projected vs line delta
        delta = projected - line
        over_prob = min(max(0.5 + delta * 0.03, 0.01), 0.99)
        under_prob = 1 - over_prob

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "first_half_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "first_half_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }

    return None


def _worst_case_prob(bet: dict, odds: dict) -> float | None:
    """Compute worst-case implied probability for the bet's side.

    Uses pre-computed multi-book worst-case when available (from consensus
    devig across all sportsbooks). Falls back to single-book worst-case
    (assumes ALL vig is on our side) when multi-book data not present.
    """
    bt = bet["bet_type"]
    side = bet.get("side", "")
    implied = odds.get("implied_probs", {})

    if bt == "moneyline":
        # Try multi-book worst-case first
        if side == "home" and "ml_home_worst" in implied:
            return implied["ml_home_worst"]
        if side == "away" and "ml_away_worst" in implied:
            return implied["ml_away_worst"]
        # Fallback: single-book worst-case
        ml = odds.get("moneyline", {})
        if side == "home":
            other_raw = american_to_implied_prob(ml.get("away", 110))
            return 1 - other_raw
        else:
            other_raw = american_to_implied_prob(ml.get("home", -110))
            return 1 - other_raw

    if bt == "total":
        t = odds.get("total", {})
        if "over" in side:
            other_raw = american_to_implied_prob(t.get("under_odds", -110))
            return 1 - other_raw
        else:
            other_raw = american_to_implied_prob(t.get("over_odds", -110))
            return 1 - other_raw

    if bt == "spread":
        # Try multi-book worst-case first
        if "home" in side and "sp_home_worst" in implied:
            return implied["sp_home_worst"]
        if "away" in side and "sp_away_worst" in implied:
            return implied["sp_away_worst"]
        # Fallback: single-book worst-case
        sp = odds.get("spread", {})
        if "home" in side:
            other_raw = american_to_implied_prob(sp.get("away_odds", -110))
            return 1 - other_raw
        else:
            other_raw = american_to_implied_prob(sp.get("home_odds", -110))
            return 1 - other_raw

    # For first-half bets, skip worst-case (already filtered by higher thresholds)
    return None


def analyze_all_edges(sim: dict, odds: dict) -> list[dict]:
    """Run all edge checks for a single game. Returns 0-6 bet signals."""
    bets = []
    checkers = [
        ("moneyline", check_moneyline_edge),
        ("spread", check_spread_edge),
        ("total", check_total_edge),
        ("first_half_ml", check_h1_ml_edge),
        ("first_half_spread", check_h1_spread_edge),
        ("first_half_total", check_h1_total_edge),
    ]

    for name, checker in checkers:
        result = checker(sim, odds)
        if result:
            # Worst-case filter: verify edge exists even if ALL vig is on our side
            wc_prob = _worst_case_prob(result, odds)
            if wc_prob is not None:
                wc_edge = result["sim_prob"] - wc_prob
                if wc_edge <= 0:
                    logger.debug("Edge check %s: fails worst-case filter (wc_edge=%.4f)", name, wc_edge)
                    continue
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f sim=%.4f mkt=%.4f kelly=%.4f",
                         name, result["side"], result["edge"],
                         result.get("sim_prob", 0), result.get("market_prob", 0),
                         result["kelly_pct"])
        else:
            logger.debug("Edge check %s: no value (threshold=%.3f)",
                         name, EDGE_THRESHOLDS.get(name, 0))

    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets


def _best_side(side_a: dict, side_b: dict) -> dict:
    """Return the side with higher edge, computing Kelly for the winner."""
    if side_a["edge"] >= side_b["edge"]:
        return side_a
    return side_b


def analyze_all_bets(sim: dict, odds: dict) -> list[dict]:
    """Analyze ALL 6 bet types and return best-side result for each, regardless of edge.

    Unlike analyze_all_edges() which filters by threshold, this always returns
    all 6 bet types so the full analysis can be displayed on the bet card.
    """
    results = []
    preds = sim.get("predictions", {})

    # --- Moneyline ---
    ml_pred = preds.get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if ml_pred and ml_odds:
        home_prob = ml_pred.get("home_win_prob", 0)
        away_prob = ml_pred.get("away_win_prob", 0)
        home_implied = odds.get("implied_probs", {}).get("ml_home", 0)
        away_implied = odds.get("implied_probs", {}).get("ml_away", 0)
        home_prob = dampen_probability(home_prob, home_implied)
        away_prob = dampen_probability(away_prob, away_implied)
        home_edge = home_prob - home_implied
        away_edge = away_prob - away_implied

        home_dec = american_to_decimal(ml_odds.get("home", -110))
        away_dec = american_to_decimal(ml_odds.get("away", 110))
        home_side = {
            "bet_type": "moneyline", "side": "home", "odds": ml_odds.get("home", 0),
            "sim_prob": home_prob, "market_prob": round(home_implied, 4),
            "edge": round(home_edge, 4),
            "kelly_pct": round(kelly_criterion(home_prob, home_dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
        away_side = {
            "bet_type": "moneyline", "side": "away", "odds": ml_odds.get("away", 0),
            "sim_prob": away_prob, "market_prob": round(away_implied, 4),
            "edge": round(away_edge, 4),
            "kelly_pct": round(kelly_criterion(away_prob, away_dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
        results.append(_best_side(home_side, away_side))

    # --- Spread ---
    sp_pred = preds.get("spread", {})
    sp_odds = odds.get("spread", {})
    if sp_pred and sp_odds:
        fav_prob = sp_pred.get("favorite_cover_prob", 0)
        home_point = sp_odds.get("home", 0)
        home_odds_val = sp_odds.get("home_odds", -110)
        away_odds_val = sp_odds.get("away_odds", -110)
        home_is_fav = home_point < 0

        if home_is_fav:
            fav_odds, dog_odds = home_odds_val, away_odds_val
            fav_label = f"home {home_point}"
            dog_label = f"away {sp_odds.get('away', 0)}"
        else:
            fav_odds, dog_odds = away_odds_val, home_odds_val
            fav_label = f"away {sp_odds.get('away', 0)}"
            dog_label = f"home {home_point}"

        fav_raw = american_to_implied_prob(fav_odds)
        dog_raw = american_to_implied_prob(dog_odds)
        fav_implied, dog_implied = power_devig(fav_raw, dog_raw)

        fav_edge = fav_prob - fav_implied
        dog_edge = (1 - fav_prob) - dog_implied

        fav_dec = american_to_decimal(fav_odds)
        dog_dec = american_to_decimal(dog_odds)
        fav_side = {
            "bet_type": "spread", "side": fav_label, "odds": fav_odds,
            "sim_prob": fav_prob, "market_prob": round(fav_implied, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, fav_dec) * KELLY_FRACTION, 4),
            "confidence": sp_pred.get("confidence", "medium"),
        }
        dog_side = {
            "bet_type": "spread", "side": dog_label, "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4), "market_prob": round(dog_implied, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dog_dec) * KELLY_FRACTION, 4),
            "confidence": sp_pred.get("confidence", "medium"),
        }
        results.append(_best_side(fav_side, dog_side))

    # --- Total ---
    total_pred = preds.get("total", {})
    total_odds = odds.get("total", {})
    if total_pred and total_odds:
        over_prob = total_pred.get("over_prob", 0)
        under_prob = total_pred.get("under_prob", 0)
        over_odds_val = total_odds.get("over_odds", -110)
        under_odds_val = total_odds.get("under_odds", -110)
        over_raw = american_to_implied_prob(over_odds_val)
        under_raw = american_to_implied_prob(under_odds_val)
        over_implied, under_implied = power_devig(over_raw, under_raw)
        line = total_odds.get("line", "?")

        over_edge = over_prob - over_implied
        under_edge = under_prob - under_implied

        over_dec = american_to_decimal(over_odds_val)
        under_dec = american_to_decimal(under_odds_val)
        over_side = {
            "bet_type": "total", "side": f"over {line}", "odds": over_odds_val,
            "sim_prob": over_prob, "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, over_dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }
        under_side = {
            "bet_type": "total", "side": f"under {line}", "odds": under_odds_val,
            "sim_prob": under_prob, "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, under_dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
        }
        results.append(_best_side(over_side, under_side))

    # --- First Half ML ---
    h1_pred = preds.get("first_half", {})
    h1_ml_odds = odds.get("h1_moneyline", {})
    if h1_pred and h1_ml_odds:
        h_prob = h1_pred.get("h1_home_win_prob", 0)
        a_prob = h1_pred.get("h1_away_win_prob", 0)
        h_odds = h1_ml_odds.get("home", -110)
        a_odds = h1_ml_odds.get("away", -110)
        h_raw = american_to_implied_prob(h_odds)
        a_raw = american_to_implied_prob(a_odds)
        h_impl, a_impl = power_devig(h_raw, a_raw)

        h_dec = american_to_decimal(h_odds)
        a_dec = american_to_decimal(a_odds)
        home_h1 = {
            "bet_type": "first_half_ml", "side": "home H1 ML", "odds": h_odds,
            "sim_prob": h_prob, "market_prob": round(h_impl, 4),
            "edge": round(h_prob - h_impl, 4),
            "kelly_pct": round(kelly_criterion(h_prob, h_dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }
        away_h1 = {
            "bet_type": "first_half_ml", "side": "away H1 ML", "odds": a_odds,
            "sim_prob": a_prob, "market_prob": round(a_impl, 4),
            "edge": round(a_prob - a_impl, 4),
            "kelly_pct": round(kelly_criterion(a_prob, a_dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
        }
        results.append(_best_side(home_h1, away_h1))

    # --- First Half Spread ---
    h1_sp_odds = odds.get("h1_spread", {})
    if h1_pred and h1_sp_odds:
        fav_prob = h1_pred.get("h1_favorite_cover_prob", 0)
        if fav_prob:
            h1_home_pt = h1_sp_odds.get("home", 0)
            h1_home_odds = h1_sp_odds.get("home_odds", -110)
            h1_away_odds = h1_sp_odds.get("away_odds", -110)
            h1_home_is_fav = h1_home_pt < 0

            if h1_home_is_fav:
                fav_o, dog_o = h1_home_odds, h1_away_odds
                fav_lbl = f"home H1 {h1_home_pt}"
                dog_lbl = f"away H1 {h1_sp_odds.get('away', 0)}"
            else:
                fav_o, dog_o = h1_away_odds, h1_home_odds
                fav_lbl = f"away H1 {h1_sp_odds.get('away', 0)}"
                dog_lbl = f"home H1 {h1_home_pt}"

            fi_raw = american_to_implied_prob(fav_o)
            di_raw = american_to_implied_prob(dog_o)
            fi, di = power_devig(fi_raw, di_raw)

            fd = american_to_decimal(fav_o)
            dd = american_to_decimal(dog_o)
            fav_h1sp = {
                "bet_type": "first_half_spread", "side": fav_lbl, "odds": fav_o,
                "sim_prob": fav_prob, "market_prob": round(fi, 4),
                "edge": round(fav_prob - fi, 4),
                "kelly_pct": round(kelly_criterion(fav_prob, fd) * KELLY_FRACTION, 4),
                "confidence": h1_pred.get("confidence", "medium"),
            }
            dog_h1sp = {
                "bet_type": "first_half_spread", "side": dog_lbl, "odds": dog_o,
                "sim_prob": round(1 - fav_prob, 4), "market_prob": round(di, 4),
                "edge": round((1 - fav_prob) - di, 4),
                "kelly_pct": round(kelly_criterion(1 - fav_prob, dd) * KELLY_FRACTION, 4),
                "confidence": h1_pred.get("confidence", "medium"),
            }
            results.append(_best_side(fav_h1sp, dog_h1sp))

    # --- First Half Total ---
    h1_total_odds = odds.get("h1_total", {})
    if h1_pred and h1_total_odds:
        projected = h1_pred.get("h1_projected_total")
        h1_line = h1_total_odds.get("line")
        if projected is not None and h1_line is not None:
            h1_over_odds = h1_total_odds.get("over_odds", -110)
            h1_under_odds = h1_total_odds.get("under_odds", -110)
            oi_raw = american_to_implied_prob(h1_over_odds)
            ui_raw = american_to_implied_prob(h1_under_odds)
            oi, ui = power_devig(oi_raw, ui_raw)

            h1_over = h1_pred.get("h1_over_prob")
            h1_under = h1_pred.get("h1_under_prob")
            if h1_over is not None and h1_under is not None:
                op = float(h1_over)
                up = float(h1_under)
            else:
                delta = projected - h1_line
                op = min(max(0.5 + delta * 0.03, 0.01), 0.99)
                up = 1 - op

            od = american_to_decimal(h1_over_odds)
            ud = american_to_decimal(h1_under_odds)
            over_h1t = {
                "bet_type": "first_half_total", "side": f"over {h1_line}", "odds": h1_over_odds,
                "sim_prob": round(op, 4), "market_prob": round(oi, 4),
                "edge": round(op - oi, 4),
                "kelly_pct": round(kelly_criterion(op, od) * KELLY_FRACTION, 4),
                "confidence": h1_pred.get("confidence", "medium"),
            }
            under_h1t = {
                "bet_type": "first_half_total", "side": f"under {h1_line}", "odds": h1_under_odds,
                "sim_prob": round(up, 4), "market_prob": round(ui, 4),
                "edge": round(up - ui, 4),
                "kelly_pct": round(kelly_criterion(up, ud) * KELLY_FRACTION, 4),
                "confidence": h1_pred.get("confidence", "medium"),
            }
            results.append(_best_side(over_h1t, under_h1t))

    # Tag which bets pass the edge threshold
    for r in results:
        threshold = EDGE_THRESHOLDS.get(r["bet_type"], 0.05)
        r["has_edge"] = r["edge"] >= threshold

    return results
