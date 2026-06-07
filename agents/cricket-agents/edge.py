"""Edge detection engines and Kelly criterion sizing for T20 cricket."""
import logging
import math
from scipy.stats import poisson as poisson_dist, nbinom as nbinom_dist, norm as norm_dist
from config import BET_TYPES, ACTIVE_TIERS, KELLY_FRACTION, PREDICTION_KEY_MAP

logger = logging.getLogger("mirofish.edge")

# Confidence multipliers for threshold adjustment
# High confidence → lower threshold (more willing to act)
# Low confidence → higher threshold (more cautious)
CONFIDENCE_THRESHOLD_MULTIPLIERS = {
    "high": 0.75,
    "medium": 1.00,
    "low": 1.50,
}


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


def calculate_linear_edge(
    projected: float, line: float, multiplier: float
) -> tuple[str, float, float, float]:
    """Linear multiplier engine for near-normal distributions.
    Returns (side, projected, probability, edge).
    """
    delta = projected - line
    prob_over = max(0.01, min(0.99, 0.50 + delta * multiplier))
    prob_under = 1.0 - prob_over
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(prob - 0.50, 4)
    return side, projected, round(prob, 4), edge


def calculate_exponential_edge(
    projected_mean: float, line: float
) -> tuple[str, float, float, float]:
    """Exponential CDF engine for right-skewed stats (mean ~ std_dev).
    Returns (side, projected_mean, probability, edge).
    """
    if projected_mean <= 0:
        return "under", projected_mean, 0.99, 0.49
    prob_over = math.exp(-line / projected_mean)
    prob_under = 1.0 - prob_over
    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(prob - 0.50, 4)
    return side, projected_mean, round(prob, 4), edge


def calculate_poisson_edge(
    projected_mean: float, line: float, overdispersion: float = 1.0
) -> tuple[str, float, float, float]:
    """Poisson/Negative Binomial CDF engine for discrete count stats.

    When overdispersion=1.0 (default), uses standard Poisson.
    When overdispersion>1.0, uses Negative Binomial which has
    variance = mean * overdispersion, capturing the real-world
    tendency for cricket count stats to be more spread than Poisson.

    Typical overdispersion values:
      wickets: 1.15-1.25 (bowlers have good/bad days beyond Poisson noise)
      sixes: 1.30-1.40 (venue/matchup creates extra variance)
      boundaries: 1.20-1.30

    Returns (side, projected_mean, probability, edge).
    """
    if projected_mean <= 0:
        return "under", projected_mean, 0.99, 0.49
    k = math.floor(line)

    if overdispersion <= 1.0:
        # Standard Poisson
        prob_over = 1.0 - poisson_dist.cdf(k, mu=projected_mean)
        prob_under = poisson_dist.cdf(k, mu=projected_mean)
    else:
        # Negative Binomial: variance = mean * overdispersion
        # scipy parameterization: n (successes), p (success prob)
        # mean = n*(1-p)/p, variance = n*(1-p)/p^2
        # So: overdispersion = variance/mean = 1/p → p = 1/overdispersion
        # And: n = mean * p / (1-p)
        p = 1.0 / overdispersion
        n = projected_mean * p / (1.0 - p)
        prob_over = 1.0 - nbinom_dist.cdf(k, n, p)
        prob_under = nbinom_dist.cdf(k, n, p)

    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(float(prob) - 0.50, 4)
    return side, projected_mean, round(float(prob), 4), edge


def calculate_bimodal_chase_edge(
    projected_mean: float, line: float,
    target: float, chase_win_prob: float = 0.55,
) -> tuple[str, float, float, float]:
    """Bimodal mixture model for second innings (chasing) totals.

    Second innings scores are bimodal: either the chase succeeds (scores
    cluster near the target) or fails (scores cluster 30-50 runs below).
    A single normal distribution misses this, producing 5-11 ppt errors
    when the line falls in the valley between the two modes.

    Args:
        projected_mean: Overall projected 2nd innings score.
        line: Betting line for team total runs.
        target: First innings score + 1 (the chase target).
        chase_win_prob: Estimated probability the chasing team wins.

    Returns (side, projected_mean, probability, edge).
    """
    w = chase_win_prob

    # Component 1: Successful chase — score clusters near target
    mu_success = target + 1  # avg winning score overshoots by ~1 run
    sigma_success = 10       # tight clustering around target

    # Component 2: Failed chase — collapse well below target
    mu_failure = target - 40  # typical collapse falls ~40 short
    sigma_failure = 22        # wider spread for failures

    # Mixture CDF: P(X <= line) = w * Phi_1(line) + (1-w) * Phi_2(line)
    cdf_success = norm_dist.cdf(line, loc=mu_success, scale=sigma_success)
    cdf_failure = norm_dist.cdf(line, loc=mu_failure, scale=sigma_failure)

    prob_under = w * cdf_success + (1 - w) * cdf_failure
    prob_over = 1.0 - prob_under

    if prob_over >= prob_under:
        side, prob = "over", prob_over
    else:
        side, prob = "under", prob_under
    edge = round(float(prob) - 0.50, 4)
    return side, projected_mean, round(float(prob), 4), edge


def detect_edge(
    bet_type: str, projected: float, line: float, odds: int | None = None,
    league: str | None = None, venue: str | None = None,
    confidence: str | None = None,
    target: float | None = None, chase_win_prob: float | None = None,
) -> dict | None:
    """Detect edge for a single bet type.

    When league and/or venue are provided, the multiplier is adjusted
    for context-specific variance (e.g., IPL at Wankhede = higher scoring
    = higher variance = smaller multiplier = less sensitive to small deltas).

    When confidence is provided ("high"/"medium"/"low"), the threshold is
    adjusted: high confidence lowers the bar (×0.75), low raises it (×1.50).
    """
    cfg = BET_TYPES.get(bet_type)
    if not cfg:
        return None
    if cfg["tier"] not in ACTIVE_TIERS:
        return None

    engine = cfg["engine"]
    base_threshold = cfg["threshold"]

    # Adjust threshold based on model confidence
    conf_mult = CONFIDENCE_THRESHOLD_MULTIPLIERS.get(confidence, 1.0)
    threshold = base_threshold * conf_mult

    if engine == "linear":
        # Use adjusted multiplier when context is available
        if league or venue:
            from adjustments import get_adjusted_multiplier
            multiplier = get_adjusted_multiplier(bet_type, league, venue)
            if multiplier is None:
                multiplier = cfg["multiplier"]
        else:
            multiplier = cfg["multiplier"]
        side, proj, prob, edge = calculate_linear_edge(projected, line, multiplier)
    elif engine == "exponential":
        side, proj, prob, edge = calculate_exponential_edge(projected, line)
    elif engine == "poisson":
        od = cfg.get("overdispersion", 1.0)
        side, proj, prob, edge = calculate_poisson_edge(projected, line, od)
    elif engine == "bimodal_chase":
        if target is None:
            return None  # Need first innings info for bimodal model
        cwp = chase_win_prob if chase_win_prob is not None else 0.55
        side, proj, prob, edge = calculate_bimodal_chase_edge(
            projected, line, target, cwp
        )
    else:
        return None

    if edge < threshold:
        return None

    # Bet strength: normalized edge relative to threshold (1.0 = at threshold, 2.0 = 2x)
    strength = round(edge / base_threshold, 2)

    result = {
        "bet_type": bet_type,
        "side": f"{side} {line}",
        "projected": proj,
        "probability": prob,
        "edge": edge,
        "tier": cfg["tier"],
        "strength": strength,
    }

    if confidence:
        result["confidence"] = confidence

    if odds is not None:
        dec = american_to_decimal(odds)
        result["odds"] = odds
        result["kelly_pct"] = round(kelly_criterion(prob, dec) * KELLY_FRACTION, 4)

    return result


def _passes_worst_case_filter(sim_prob: float, raw_own: float, raw_other: float) -> tuple[bool, float]:
    """Worst-case devig: assumes all vig is assigned to our side."""
    worst_case_implied = 1 - raw_other
    worst_case_edge = sim_prob - worst_case_implied
    return worst_case_edge > 0, round(worst_case_edge, 4)


def check_moneyline_edge(
    team_a_prob: float, team_b_prob: float,
    team_a_odds: int | None = None, team_b_odds: int | None = None,
    implied_probs: dict | None = None,
) -> dict | None:
    """Check moneyline edge for both teams. Returns best side if any.

    Uses multi-book consensus implied probs when available, else 0.50 baseline.
    Applies worst-case filter when multi-book data is present.
    """
    from scrapers.odds import american_to_implied_prob
    threshold = BET_TYPES["moneyline"]["threshold"]

    best = None
    sides = [
        ("team_a", team_a_prob, team_a_odds, "team_b"),
        ("team_b", team_b_prob, team_b_odds, "team_a"),
    ]
    for team, prob, odds_val, other_team in sides:
        # Use market consensus implied prob if available, else 0.50 baseline
        if implied_probs and team in implied_probs:
            market_prob = implied_probs[team]
        else:
            market_prob = 0.50
        edge = round(prob - market_prob, 4)
        if edge >= threshold:
            # Worst-case filter: check against worst book
            if implied_probs and f"{team}_worst" in implied_probs:
                if prob <= implied_probs[f"{team}_worst"]:
                    continue  # fails worst-case
            elif odds_val is not None:
                # Fallback: single-book worst-case
                other_odds = team_b_odds if team == "team_a" else team_a_odds
                if other_odds is not None:
                    raw_own = american_to_implied_prob(odds_val)
                    raw_other = american_to_implied_prob(other_odds)
                    passes, _ = _passes_worst_case_filter(prob, raw_own, raw_other)
                    if not passes:
                        continue

            result = {
                "bet_type": "moneyline",
                "side": team,
                "projected": prob,
                "probability": prob,
                "market_prob": round(market_prob, 4),
                "edge": edge,
                "tier": 1,
            }
            if odds_val is not None:
                dec = american_to_decimal(odds_val)
                result["odds"] = odds_val
                result["kelly_pct"] = round(kelly_criterion(prob, dec) * KELLY_FRACTION, 4)
            if best is None or edge > best["edge"]:
                best = result

    return best


def analyze_all_edges(predictions: dict, odds: dict) -> list[dict]:
    """Run edge detection across all available bet types."""
    edges = []
    preds = predictions.get("predictions", {})

    # Moneyline
    ml = preds.get("moneyline", {})
    if ml:
        ml_odds = odds.get("moneyline", {})
        result = check_moneyline_edge(
            ml.get("team_a_win_prob", 0),
            ml.get("team_b_win_prob", 0),
            ml_odds.get("team_a"),
            ml_odds.get("team_b"),
            implied_probs=odds.get("implied_probs"),
        )
        if result:
            edges.append(result)

    # Build reverse map: bet_type key -> prediction key
    reverse_map = {v: k for k, v in PREDICTION_KEY_MAP.items()}

    # All other bet types
    for bet_type, cfg in BET_TYPES.items():
        if bet_type == "moneyline":
            continue
        pred_key = reverse_map.get(bet_type, bet_type)
        pred = preds.get(bet_type, {}) or preds.get(pred_key, {})
        odds_data = odds.get(bet_type, {}) or odds.get(pred_key, {})
        projected = pred.get("projected")
        line = odds_data.get("line")
        if projected is None or line is None:
            continue
        bet_odds = odds_data.get("odds")
        result = detect_edge(bet_type, projected, line, bet_odds)
        if result:
            edges.append(result)

    return edges
