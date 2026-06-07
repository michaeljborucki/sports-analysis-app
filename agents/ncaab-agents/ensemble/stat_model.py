"""Pure-math statistical anchor model for the MiroFish NCAAB ensemble.

This model uses zero LLM calls. It derives predictions entirely from
Torvik/CBBData efficiency metrics and the normal distribution, producing
the same JSON structure as LLM panel members so it plugs directly into
the ensemble weighted-average and consensus machinery.

Design rationale
----------------
The 6-LLM ensemble suffers from correlated biases (all models share
training-data priors, all overestimate totals). This model breaks the
echo chamber by anchoring to:

1. **Tempo-free efficiency metrics** -- the single best predictor of
   NCAAB outcomes according to decades of KenPom / Torvik research.
2. **The normal distribution** with sigma = 11 points (the empirical
   standard deviation of NCAAB final margins in the modern era).
3. **Market regression** -- the model blends its raw projection with
   the betting line (70/30 model/market) to avoid overconfident
   predictions when efficiency data disagrees with sharp money.

Formulas
--------
**Projected total** (full game):
    away_pts_per_100 = away_adjOE * (home_adjDE / D1_AVG)
    home_pts_per_100 = home_adjOE * (away_adjDE / D1_AVG)
    projected_total  = (away_pts + home_pts) * pace / 100

    D1_AVG (= 100) normalizes so that average offense vs average defense
    produces the raw efficiency. The cross-match formula accounts for the
    actual defensive quality faced.

**Projected spread** (home perspective, negative = home favored):
    raw_spread = -(home_adjEM - away_adjEM) / 2 - HCA

    We divide the EM gap by 2 (not raw subtraction) because each team's
    AdjEM already contains both offense and defense. The direct difference
    double-counts. Dividing by 2 calibrates to the margin-of-victory
    scale. We then add home-court advantage (3.5 pts).

    NOTE: home_spread uses the convention "negative = home favored",
    matching the odds feed (spread.home = -6.5 means home -6.5).

    Blended spread = 0.7 * model_spread + 0.3 * market_spread
    (when market spread is available).

**Win probability** (from spread via normal CDF):
    home_win_prob = Phi((-spread) / sigma)

    where sigma = 11 (the historical std dev of NCAAB final margins).
    A projected home spread of -7 means the home team is favored by 7,
    so (-(-7)) / 11 = 7/11 = 0.636 z-score -> ~73.7% home win prob.

**Over/under probability** (from projected total vs line):
    over_prob = Phi((projected_total - line) / sigma_total)

    sigma_total = 11 (total margin std dev is empirically ~10-12 pts;
    11 is a conservative middle ground).

**First-half projections**:
    h1_total = full_game_total * H1_FRACTION (0.48)
    h1_spread = full_game_spread * H1_FRACTION (0.48)

    48% rather than 50% because second halves tend slightly higher-scoring
    (more fouls, intentional fouling, free throws in close games).

**Confidence mapping** (from abs(edge)):
    |edge| < 0.03 -> "low"
    |edge| < 0.07 -> "medium"
    |edge| >= 0.07 -> "high"
"""

import logging
import math

from config import HOME_COURT_ADVANTAGE

logger = logging.getLogger("mirofish.ensemble.stat_model")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Empirical standard deviation of NCAAB final margins (modern era, ~2005-2025).
# Sources: KenPom, Torvik historical data. Range is 10.5-11.5; 11 is standard.
MARGIN_SIGMA = 11.0

# Standard deviation for total points scored. Empirically ~10-12; we use 11.
TOTAL_SIGMA = 11.0

# D1 average efficiency (points per 100 possessions). By construction of
# adjusted metrics, the D1 average is always ~100.
D1_AVG_EFFICIENCY = 100.0

# First-half scoring fraction. Empirically 47-49% of points are scored in
# the first half. 0.48 is a well-calibrated default.
H1_FRACTION = 0.48

# Blend weight for model projection vs market line.
# 0.7 model / 0.3 market keeps the model opinionated enough to serve as an
# anchor against LLM consensus, while still respecting sharp-money signal.
MODEL_WEIGHT = 0.70
MARKET_WEIGHT = 0.30

# Model key used in ensemble results and weight tracking
STAT_MODEL_KEY = "stat_anchor"


# ---------------------------------------------------------------------------
# Normal CDF using only the standard library (no scipy dependency)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF: P(Z <= x) using math.erf.

    Phi(x) = 0.5 * (1 + erf(x / sqrt(2)))
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Core projection functions
# ---------------------------------------------------------------------------

def project_total(away_oe: float, away_de: float,
                  home_oe: float, home_de: float,
                  away_tempo: float, home_tempo: float) -> float:
    """Project full-game total points from efficiency metrics.

    Uses the cross-match formula:
        away_pts_per_100 = away_adjOE * (home_adjDE / 100)
        home_pts_per_100 = home_adjOE * (away_adjDE / 100)
        total = (away_pts + home_pts) * pace / 100

    This is the same formula used by Torvik/KenPom for expected scores.
    """
    pace = (away_tempo + home_tempo) / 2.0

    # Cross-match: each team's offense against opponent's defense
    away_pts_per_100 = away_oe * (home_de / D1_AVG_EFFICIENCY)
    home_pts_per_100 = home_oe * (away_de / D1_AVG_EFFICIENCY)

    total = (away_pts_per_100 + home_pts_per_100) * pace / 100.0
    return round(total, 1)


def project_spread(away_em: float, home_em: float,
                   home_court: float = None,
                   neutral: bool = False) -> float:
    """Project spread from efficiency margins.

    Returns the home team's spread (negative = home favored).

    The raw efficiency gap (home_em - away_em) represents the
    expected margin per game. We apply home-court advantage.
    """
    if home_court is None:
        home_court = HOME_COURT_ADVANTAGE

    hca = 0.0 if neutral else home_court

    # Projected margin from home team's perspective (positive = home wins by X)
    projected_margin = (home_em - away_em) / 2.0 + hca

    # Convert to spread convention (negative = home favored)
    home_spread = -projected_margin

    return round(home_spread, 1)


def spread_to_win_prob(spread: float, sigma: float = MARGIN_SIGMA) -> float:
    """Convert a spread to home win probability via normal CDF.

    spread is in "home spread" convention: -7 means home is 7-point favorite.
    home_win_prob = Phi((-spread) / sigma)

    Example: spread = -7 -> z = 7/11 = 0.636 -> Phi(0.636) = 0.7377
    """
    if sigma <= 0:
        return 0.5
    z = (-spread) / sigma
    return round(_norm_cdf(z), 4)


def total_to_over_prob(projected_total: float, line: float,
                       sigma: float = TOTAL_SIGMA) -> float:
    """Probability that the actual total exceeds the line.

    over_prob = Phi((projected - line) / sigma)
    """
    if sigma <= 0:
        return 0.5
    z = (projected_total - line) / sigma
    return round(_norm_cdf(z), 4)


def _edge_to_confidence(edge: float) -> str:
    """Map absolute edge to confidence label."""
    ae = abs(edge)
    if ae >= 0.07:
        return "high"
    if ae >= 0.03:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Value side determination
# ---------------------------------------------------------------------------

def _ml_value_side(home_prob: float, market_home_prob: float) -> str:
    """Determine moneyline value side."""
    edge_home = home_prob - market_home_prob
    edge_away = (1 - home_prob) - (1 - market_home_prob)
    if edge_home > 0.02:
        return "home"
    if edge_away > 0.02:
        return "away"
    return "none"


def _spread_value_side(model_spread: float, market_spread: float) -> str:
    """Determine spread value side (favorite/underdog).

    If model thinks the favorite should be favored by MORE than the market,
    the favorite is the value side. Otherwise, the underdog.
    """
    # model_spread and market_spread both negative = home favored
    # If model_spread < market_spread (more negative), model says home
    # should be favored by more -> favorite covers
    if model_spread < market_spread - 0.5:
        return "favorite"
    if model_spread > market_spread + 0.5:
        return "underdog"
    return "none"


def _total_value_side(projected: float, line: float) -> str:
    """Determine total value side."""
    diff = projected - line
    if diff > 1.0:
        return "over"
    if diff < -1.0:
        return "under"
    return "none"


# ---------------------------------------------------------------------------
# Main prediction builder
# ---------------------------------------------------------------------------

def run_stat_model(game_data: dict) -> dict | None:
    """Generate predictions from pure efficiency math.

    Args:
        game_data: The same game_data dict passed to build_briefing(),
                   containing away_stats, home_stats, odds, matchup, etc.

    Returns:
        A dict in the same format as LLM parsed results (with "predictions"
        and "analyst_assessments" keys), or None if stats are unavailable.
    """
    a_stats = game_data.get("away_stats", {})
    h_stats = game_data.get("home_stats", {})
    odds = game_data.get("odds", {})
    matchup = game_data.get("matchup", {})

    # Extract efficiency metrics
    away_oe = a_stats.get("adj_oe", 0) or 0
    away_de = a_stats.get("adj_de", 0) or 0
    home_oe = h_stats.get("adj_oe", 0) or 0
    home_de = h_stats.get("adj_de", 0) or 0
    away_tempo = a_stats.get("adj_tempo", 0) or 0
    home_tempo = h_stats.get("adj_tempo", 0) or 0

    # Bail out if no efficiency data (can't predict without it)
    if away_oe == 0 or home_oe == 0 or away_tempo == 0 or home_tempo == 0:
        logger.warning("stat_anchor: missing efficiency data, returning None")
        return None

    away_em = away_oe - away_de
    home_em = home_oe - home_de

    neutral = matchup.get("neutral_site", False)

    # --- Full-game projections ---
    raw_total = project_total(away_oe, away_de, home_oe, home_de,
                              away_tempo, home_tempo)
    raw_spread = project_spread(away_em, home_em, neutral=neutral)

    # --- Blend with market ---
    market_spread = odds.get("spread", {}).get("home")
    market_total_line = odds.get("total", {}).get("line")

    if market_spread is not None:
        blended_spread = round(
            MODEL_WEIGHT * raw_spread + MARKET_WEIGHT * float(market_spread), 1
        )
    else:
        blended_spread = raw_spread

    if market_total_line is not None:
        blended_total = round(
            MODEL_WEIGHT * raw_total + MARKET_WEIGHT * float(market_total_line), 1
        )
    else:
        blended_total = raw_total

    # --- Win probabilities ---
    home_win_prob = spread_to_win_prob(blended_spread)
    away_win_prob = round(1.0 - home_win_prob, 4)

    # --- Total probabilities ---
    if market_total_line is not None:
        over_prob = total_to_over_prob(blended_total, float(market_total_line))
    else:
        over_prob = 0.5
    under_prob = round(1.0 - over_prob, 4)

    # --- Spread cover probability ---
    # P(favorite covers) when market spread = S:
    # favorite_cover = P(margin > |S|) where margin is from favorite's perspective
    # Using the blended spread as our projected margin:
    if market_spread is not None:
        ms = float(market_spread)
        # Projected margin from home perspective = -blended_spread
        # If home is favorite (ms < 0): P(home covers) = P(margin > |ms|)
        # = P(Z > (|ms| - projected_margin) / sigma)
        projected_margin = -blended_spread
        if ms < 0:
            # Home is favorite, needs to win by more than |ms|
            z = (projected_margin - abs(ms)) / MARGIN_SIGMA
            favorite_cover_prob = round(_norm_cdf(z), 4)
        elif ms > 0:
            # Away is favorite (home getting points)
            # Away projected margin = -projected_margin
            away_margin = -projected_margin
            z = (away_margin - abs(ms)) / MARGIN_SIGMA
            favorite_cover_prob = round(_norm_cdf(z), 4)
        else:
            favorite_cover_prob = 0.50
    else:
        favorite_cover_prob = 0.50

    # --- Market implied probabilities for edge calculation ---
    implied = odds.get("implied_probs", {})
    market_home_prob = implied.get("ml_home", 0.5)
    market_away_prob = implied.get("ml_away", 0.5)

    ml_edge_home = home_win_prob - market_home_prob
    ml_edge_away = away_win_prob - market_away_prob
    ml_edge = max(ml_edge_home, ml_edge_away)

    # --- Spread edge ---
    spread_edge = abs(favorite_cover_prob - 0.5)

    # --- Total edge ---
    total_edge = abs(over_prob - 0.5)

    # --- Value sides ---
    ml_value = _ml_value_side(home_win_prob, market_home_prob)
    spread_value = "none"
    if market_spread is not None:
        spread_value = _spread_value_side(blended_spread, float(market_spread))
    total_value = "none"
    if market_total_line is not None:
        total_value = _total_value_side(blended_total, float(market_total_line))

    # --- First-half projections ---
    h1_total = round(blended_total * H1_FRACTION, 1)
    h1_spread = round(blended_spread * H1_FRACTION, 1)
    h1_home_win_prob = spread_to_win_prob(h1_spread)
    h1_away_win_prob = round(1.0 - h1_home_win_prob, 4)

    h1_total_line = odds.get("h1_total", {}).get("line")
    if h1_total_line is not None:
        h1_over_prob = total_to_over_prob(h1_total, float(h1_total_line))
    else:
        h1_over_prob = 0.5
    h1_under_prob = round(1.0 - h1_over_prob, 4)

    # H1 spread cover probability
    h1_market_spread = odds.get("h1_spread", {}).get("home")
    if h1_market_spread is not None:
        h1_ms = float(h1_market_spread)
        h1_projected_margin = -h1_spread
        if h1_ms < 0:
            z = (h1_projected_margin - abs(h1_ms)) / (MARGIN_SIGMA * math.sqrt(H1_FRACTION))
            h1_fav_cover = round(_norm_cdf(z), 4)
        elif h1_ms > 0:
            h1_away_margin = -h1_projected_margin
            z = (h1_away_margin - abs(h1_ms)) / (MARGIN_SIGMA * math.sqrt(H1_FRACTION))
            h1_fav_cover = round(_norm_cdf(z), 4)
        else:
            h1_fav_cover = 0.50
    else:
        h1_fav_cover = 0.50

    # H1 value sides
    h1_ml_value = _ml_value_side(h1_home_win_prob,
                                  implied.get("ml_home", 0.5))
    h1_total_value = "none"
    if h1_total_line is not None:
        h1_total_value = _total_value_side(h1_total, float(h1_total_line))
    h1_spread_value = "none"
    if h1_market_spread is not None:
        h1_spread_value = _spread_value_side(h1_spread, float(h1_market_spread))

    # --- Predicted score ---
    pace = (away_tempo + home_tempo) / 2.0
    away_pts = round(away_oe * (home_de / D1_AVG_EFFICIENCY) * pace / 100.0)
    home_pts = round(home_oe * (away_de / D1_AVG_EFFICIENCY) * pace / 100.0)
    # Adjust for home court (add half of HCA to each side's projection)
    if not neutral:
        hca_pts = HOME_COURT_ADVANTAGE / 2.0
        home_pts = round(home_pts + hca_pts)
        away_pts = round(away_pts - hca_pts)

    # --- Confidence levels ---
    ml_confidence = _edge_to_confidence(ml_edge)
    spread_confidence = _edge_to_confidence(spread_edge)
    total_confidence = _edge_to_confidence(total_edge)

    # First-half confidence is always one notch lower (less signal)
    h1_confidence = "low" if ml_confidence in ("low", "medium") else "medium"

    # --- Key factors ---
    key_factors = []

    em_gap = home_em - away_em
    if abs(em_gap) > 10:
        key_factors.append(f"Large efficiency gap: {em_gap:+.1f} AdjEM")
    elif abs(em_gap) > 5:
        key_factors.append(f"Moderate efficiency gap: {em_gap:+.1f} AdjEM")

    tempo_diff = abs(away_tempo - home_tempo)
    if tempo_diff > 5:
        key_factors.append(f"Significant tempo mismatch: {tempo_diff:.1f} poss/40min")

    if market_total_line and abs(blended_total - float(market_total_line)) > 3:
        direction = "above" if blended_total > float(market_total_line) else "below"
        key_factors.append(
            f"Model total {blended_total} is {abs(blended_total - float(market_total_line)):.1f} pts "
            f"{direction} market line {market_total_line}"
        )

    if not neutral:
        key_factors.append(f"Home court: +{HOME_COURT_ADVANTAGE} pts")

    if not key_factors:
        key_factors.append("Projections align with market consensus")

    # --- Build output (same JSON schema as LLM models) ---
    result = {
        "analyst_assessments": [
            {
                "role": "efficiency",
                "pick": game_data.get("home_team", "HOME") if home_em > away_em
                        else game_data.get("away_team", "AWAY"),
                "reasoning": (
                    f"Statistical model: AdjEM gap {em_gap:+.1f}, "
                    f"projected spread {blended_spread:+.1f}, "
                    f"projected total {blended_total:.1f}"
                ),
            },
        ],
        "predictions": {
            "moneyline": {
                "home_win_prob": home_win_prob,
                "away_win_prob": away_win_prob,
                "value_side": ml_value,
                "edge": round(ml_edge, 4),
                "confidence": ml_confidence,
            },
            "spread": {
                "favorite_cover_prob": favorite_cover_prob,
                "value_side": spread_value,
                "edge": round(spread_edge, 4),
                "confidence": spread_confidence,
            },
            "total": {
                "projected_total": blended_total,
                "over_prob": over_prob,
                "under_prob": under_prob,
                "value_side": total_value,
                "edge": round(total_edge, 4),
                "confidence": total_confidence,
            },
            "first_half": {
                "h1_home_win_prob": h1_home_win_prob,
                "h1_away_win_prob": h1_away_win_prob,
                "h1_projected_total": h1_total,
                "h1_over_prob": h1_over_prob,
                "h1_under_prob": h1_under_prob,
                "h1_favorite_cover_prob": h1_fav_cover,
                "h1_ml_value": h1_ml_value,
                "h1_total_value": h1_total_value,
                "h1_spread_value": h1_spread_value,
                "confidence": h1_confidence,
            },
            "predicted_score": {"away": away_pts, "home": home_pts},
            "key_factors": key_factors,
        },
    }

    logger.info(
        "stat_anchor: spread=%+.1f total=%.1f home_win=%.1f%% | "
        "raw_spread=%+.1f raw_total=%.1f",
        blended_spread, blended_total, home_win_prob * 100,
        raw_spread, raw_total,
    )

    return result


def run_stat_model_as_ensemble_entry(game_data: dict) -> dict | None:
    """Wrap run_stat_model output to match the ensemble runner's result format.

    Returns the same dict shape as runner.run_single_model():
        {"model_key": "stat_anchor", "parsed": {...}, "temperature": 0, "cost": 0}
    """
    parsed = run_stat_model(game_data)
    if parsed is None:
        return None
    return {
        "model_key": STAT_MODEL_KEY,
        "parsed": parsed,
        "temperature": 0.0,  # deterministic -- no temperature concept
        "cost": 0.0,         # no API cost
    }
