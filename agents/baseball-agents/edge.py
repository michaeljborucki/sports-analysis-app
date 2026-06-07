"""Edge detection and Kelly criterion sizing for all 5 bet types."""
import logging
from math import exp, factorial, lgamma, log
import re

from calibrate import apply_calibration
from config import (
    BET_FILTERS,
    EDGE_THRESHOLDS,
    KELLY_FRACTION,
)
from scrapers.odds import OddsData, american_to_implied_prob, power_devig

logger = logging.getLogger("mirofish.edge")


_LINE_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _extract_line_from_side(side: str) -> float | None:
    """Extract the numeric line value from a side string like 'over 1.5' or 'Player Name under 0.5'."""
    if not side:
        return None
    matches = _LINE_RE.findall(str(side))
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def _passes_bet_filter(bet: dict) -> bool:
    """Apply per-bet-type filters from config.BET_FILTERS.

    Returns True if the bet should be kept, False if it should be dropped.
    Bet types not in BET_FILTERS pass through unchanged.
    """
    filt = BET_FILTERS.get(bet.get("bet_type"))
    if not filt:
        return True

    if filt.get("disabled"):
        return False

    edge = float(bet.get("edge", 0))
    if "min_edge" in filt and edge < filt["min_edge"]:
        return False
    if "max_edge" in filt and edge >= filt["max_edge"]:
        return False

    side = str(bet.get("side", "")).lower()
    if "side_contains" in filt:
        needles = [n.lower() for n in filt["side_contains"]]
        if not any(n in side for n in needles):
            return False

    if "line_in" in filt:
        line = _extract_line_from_side(side)
        if line is None or line not in filt["line_in"]:
            return False

    odds = int(bet.get("odds", 0))
    if "odds_min" in filt and odds < filt["odds_min"]:
        return False
    if "odds_max" in filt and odds > filt["odds_max"]:
        return False

    return True


def apply_bet_filters(bets: list[dict]) -> list[dict]:
    """Filter a list of bets through BET_FILTERS, logging any drops."""
    if not bets:
        return bets
    kept = []
    dropped_by_type: dict[str, int] = {}
    for bet in bets:
        if _passes_bet_filter(bet):
            kept.append(bet)
        else:
            bt = bet.get("bet_type", "?")
            dropped_by_type[bt] = dropped_by_type.get(bt, 0) + 1
    if dropped_by_type:
        logger.info("BET_FILTERS dropped %d bets: %s",
                    sum(dropped_by_type.values()),
                    ", ".join(f"{k}={v}" for k, v in dropped_by_type.items()))
    return kept


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


def _sized_kelly(prob: float, dec: float) -> float:
    """Apply Kelly criterion with quarter-Kelly fraction."""
    return round(kelly_criterion(prob, dec) * KELLY_FRACTION, 4)


def _passes_worst_case_filter(sim_prob: float, raw_own: float, raw_other: float) -> tuple[bool, float]:
    """Worst-case devig: assumes all vig is assigned to our side.

    worst_case_implied = 1 - raw_other (other side's raw prob is their true prob).
    Bet only passes if sim_prob exceeds this pessimistic implied probability.
    """
    worst_case_implied = 1 - raw_other
    worst_case_edge = sim_prob - worst_case_implied
    return worst_case_edge > 0, round(worst_case_edge, 4)


def check_moneyline_edge(sim: dict, odds: dict) -> dict | None:
    """Check for moneyline value on either side."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = EDGE_THRESHOLDS["moneyline"]

    # Check home
    home_prob = ml_pred.get("home_win_prob", 0)
    home_prob = apply_calibration(home_prob, "moneyline")
    home_implied = odds.get("implied_probs", {}).get("ml_home", 0)
    home_edge = home_prob - home_implied

    # Check away
    away_prob = ml_pred.get("away_win_prob", 0)
    away_prob = apply_calibration(away_prob, "moneyline")
    away_implied = odds.get("implied_probs", {}).get("ml_away", 0)
    away_edge = away_prob - away_implied

    # Raw implied probs for worst-case filter
    raw_home = american_to_implied_prob(ml_odds["home"])
    raw_away = american_to_implied_prob(ml_odds["away"])

    # Take the side with more edge
    if home_edge >= threshold and home_edge >= away_edge:
        passes, wc_edge = _passes_worst_case_filter(home_prob, raw_home, raw_away)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["home"])
        return {
            "bet_type": "moneyline",
            "side": "home",
            "odds": ml_odds["home"],
            "sim_prob": home_prob,
            "market_prob": home_implied,
            "edge": round(home_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(home_prob, dec),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(away_prob, raw_away, raw_home)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["away"])
        return {
            "bet_type": "moneyline",
            "side": "away",
            "odds": ml_odds["away"],
            "sim_prob": away_prob,
            "market_prob": away_implied,
            "edge": round(away_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(away_prob, dec),
            "confidence": ml_pred.get("confidence", "medium"),
        }

    return None


def check_run_line_edge(sim: dict, odds: dict) -> dict | None:
    """Check for run line value. Determines favorite by spread point, not position."""
    rl_pred = sim.get("predictions", {}).get("run_line", {})
    rl_odds = odds.get("run_line", {})
    if not rl_pred or not rl_odds:
        return None

    threshold = EDGE_THRESHOLDS["run_line"]
    fav_prob = rl_pred.get("favorite_cover_prob", 0)
    fav_prob = apply_calibration(fav_prob, "run_line")

    # Determine which side is the favorite based on spread point
    home_point = rl_odds.get("home", -1.5)
    home_odds = rl_odds.get("home_odds", -110)
    away_odds = rl_odds.get("away_odds", -110)

    # The side with the negative point (-1.5) is the favorite
    home_is_fav = home_point < 0

    if home_is_fav:
        fav_odds = home_odds
        dog_odds = away_odds
        fav_label = f"home {home_point}"
        dog_label = f"away {rl_odds.get('away', 1.5)}"
    else:
        fav_odds = away_odds
        dog_odds = home_odds
        fav_label = f"away {rl_odds.get('away', -1.5)}"
        dog_label = f"home {home_point}"

    raw_fav = american_to_implied_prob(fav_odds)
    raw_dog = american_to_implied_prob(dog_odds)
    fav_implied, dog_implied = power_devig(raw_fav, raw_dog)

    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    if fav_edge >= threshold and fav_edge >= dog_edge:
        passes, wc_edge = _passes_worst_case_filter(fav_prob, raw_fav, raw_dog)
        if not passes:
            return None
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "run_line",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_implied, 4),
            "edge": round(fav_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(fav_prob, dec),
            "confidence": rl_pred.get("confidence", "medium"),
        }
    elif dog_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(1 - fav_prob, raw_dog, raw_fav)
        if not passes:
            return None
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "run_line",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_implied, 4),
            "edge": round(dog_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(1 - fav_prob, dec),
            "confidence": rl_pred.get("confidence", "medium"),
        }

    return None


def check_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total (over/under) value.

    Uses negbin from predicted scores when available (consistent with team totals),
    falls back to LLM's over_prob/under_prob otherwise.
    """
    total_pred = sim.get("predictions", {}).get("total", {})
    total_odds = odds.get("total", {})
    if not total_pred or not total_odds:
        return None

    threshold = EDGE_THRESHOLDS["total"]
    line = total_odds.get("line")

    # Prefer negbin from predicted scores (consistent with team total methodology)
    ps = sim.get("predictions", {}).get("predicted_score", {})
    if ps and "home" in ps and "away" in ps and line is not None:
        projected_total = float(ps["home"]) + float(ps["away"])
        # dispersion=2.1 matches the function default and MLB empirical var/mean.
        # Simulation measures 2.02 on league-average inputs. Prior value 1.8
        # produced narrower-than-reality CDF tails, inflating edge on unders.
        over_prob = _negbin_over_prob(projected_total, line)
        under_prob = 1 - over_prob
    else:
        over_prob = total_pred.get("over_prob", 0)
        under_prob = total_pred.get("under_prob", 0)

    # Bias is handled at the MC layer (advance-prob tuning) and per-side
    # isotonic calibration. The post-LLM TOTAL_UNDER_BIAS_CORRECTION was
    # removed 2026-05-04 — once calibration shipped it stopped flipping side
    # calls and risked double-correction.

    over_prob = apply_calibration(over_prob, "total", "over")
    under_prob = apply_calibration(under_prob, "total", "under")

    over_odds = total_odds.get("over_odds", -110)
    under_odds = total_odds.get("under_odds", -110)
    raw_over = american_to_implied_prob(over_odds)
    raw_under = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_over, raw_under)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    line = total_odds.get("line", "?")

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_over, raw_under)
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
            "kelly_pct": _sized_kelly(over_prob, dec),
            "confidence": total_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_under, raw_over)
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
            "kelly_pct": _sized_kelly(under_prob, dec),
            "confidence": total_pred.get("confidence", "medium"),
        }

    return None


def check_f5_ml_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First 5 Innings moneyline value."""
    f5_pred = sim.get("predictions", {}).get("first_5", {})
    if not f5_pred:
        return None

    threshold = EDGE_THRESHOLDS["first_5_ml"]

    f5_ml = odds.get("f5_moneyline", {})
    if not f5_ml:
        return None

    home_odds = f5_ml.get("home", -110)
    away_odds = f5_ml.get("away", -110)
    raw_h = american_to_implied_prob(home_odds)
    raw_a = american_to_implied_prob(away_odds)
    h_implied, a_implied = power_devig(raw_h, raw_a)

    h_prob = f5_pred.get("f5_home_win_prob", 0)
    a_prob = f5_pred.get("f5_away_win_prob", 0)
    h_prob = apply_calibration(h_prob, "first_5_ml")
    a_prob = apply_calibration(a_prob, "first_5_ml")
    h_edge = h_prob - h_implied
    a_edge = a_prob - a_implied

    if h_edge >= threshold and h_edge >= a_edge:
        passes, wc_edge = _passes_worst_case_filter(h_prob, raw_h, raw_a)
        if not passes:
            return None
        dec = american_to_decimal(home_odds)
        return {
            "bet_type": "first_5_ml",
            "side": "home F5 ML",
            "odds": home_odds,
            "sim_prob": h_prob,
            "market_prob": round(h_implied, 4),
            "edge": round(h_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(h_prob, dec),
            "confidence": f5_pred.get("confidence", "medium"),
        }
    elif a_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(a_prob, raw_a, raw_h)
        if not passes:
            return None
        dec = american_to_decimal(away_odds)
        return {
            "bet_type": "first_5_ml",
            "side": "away F5 ML",
            "odds": away_odds,
            "sim_prob": a_prob,
            "market_prob": round(a_implied, 4),
            "edge": round(a_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(a_prob, dec),
            "confidence": f5_pred.get("confidence", "medium"),
        }

    return None


def check_f5_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First 5 Innings over/under value using projected total vs line heuristic."""
    f5_pred = sim.get("predictions", {}).get("first_5", {})
    if not f5_pred:
        return None

    f5_total_odds = odds.get("f5_total", {})
    if not f5_total_odds:
        return None

    projected = f5_pred.get("f5_projected_total")
    if projected is None:
        return None

    line = f5_total_odds.get("line")
    if line is None:
        return None

    threshold = EDGE_THRESHOLDS["first_5_total"]

    over_odds = f5_total_odds.get("over_odds", -110)
    under_odds = f5_total_odds.get("under_odds", -110)
    raw_over = american_to_implied_prob(over_odds)
    raw_under = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_over, raw_under)

    over_prob = _negbin_over_prob(float(projected), line, dispersion=1.5)
    under_prob = 1 - over_prob
    over_prob = apply_calibration(over_prob, "first_5_total", "over")
    under_prob = apply_calibration(under_prob, "first_5_total", "under")

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_over, raw_under)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "first_5_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(over_prob, dec),
            "confidence": f5_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_under, raw_over)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "first_5_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(under_prob, dec),
            "confidence": f5_pred.get("confidence", "medium"),
        }

    return None


def _negbin_over_prob(predicted: float, line: float, dispersion: float = 2.1) -> float:
    """Calculate P(over line) using negative binomial CDF.

    Baseball run scoring is overdispersed. Uses the mean/dispersion
    parameterization: r = mean² / (variance - mean), p = (variance - mean) / variance.
    Default dispersion 2.1 matches MLB variance/mean ratio (~2.1-2.2).
    """
    if predicted <= 0:
        return 0.01
    variance = dispersion * predicted
    if variance <= predicted:
        variance = predicted + 0.01  # fallback: slightly overdispersed
    r = predicted ** 2 / (variance - predicted)
    p_success = (variance - predicted) / variance  # probability parameter for NB

    # CDF via log-space for numerical stability
    k_max = int(line)
    cdf = 0.0
    for k in range(k_max + 1):
        # P(X=k) = C(k+r-1, k) * p^k * (1-p)^r  (using log-gamma)
        log_pmf = (
            lgamma(k + r) - lgamma(k + 1) - lgamma(r)
            + k * (log(p_success) if p_success > 0 else -700)
            + r * (log(1 - p_success) if p_success < 1 else -700)
        )
        cdf += exp(log_pmf)
    return max(0.01, min(0.99, 1 - cdf))


def check_team_total_edge(sim: dict, odds: OddsData, side: str) -> dict | None:
    """Check team total edge for home or away."""
    predicted = sim.get("predictions", {}).get("predicted_score", {}).get(side)
    tt = odds.team_total_home if side == "home" else odds.team_total_away
    if not predicted or not tt or "line" not in tt:
        return None

    bet_type = f"team_total_{side}"
    threshold = EDGE_THRESHOLDS.get(bet_type, 0.05)
    line = tt["line"]

    over_prob = _negbin_over_prob(float(predicted), line)
    under_prob = 1 - over_prob

    # Park effects influence BOTH teams equally — any post-LLM correction must
    # be symmetric. The previous home-only TEAM_TOTAL_HOME_OVER_BIAS_CORRECTION
    # was removed 2026-05-04 after producing 100% LOCK picks at hitters' parks
    # (it was stacking on top of already low-scoring MC distributions).

    over_prob = apply_calibration(over_prob, bet_type, "over")
    under_prob = apply_calibration(under_prob, bet_type, "under")

    over_odds = tt.get("over_odds", -110)
    under_odds = tt.get("under_odds", -110)
    raw_over = american_to_implied_prob(over_odds)
    raw_under = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_over, raw_under)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_over, raw_under)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": bet_type,
            "side": f"{side} over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(over_prob, dec),
            "confidence": "medium",
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_under, raw_over)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": bet_type,
            "side": f"{side} under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(under_prob, dec),
            "confidence": "medium",
        }
    return None


def _check_innings_spread_edge(sim: dict, odds: OddsData, period: str,
                                bet_type: str, spread_field: str,
                                lead_home_key: str, lead_away_key: str,
                                tie_key: str) -> dict | None:
    """Generic innings spread checker. Ties go to +0.5 side."""
    pred = sim.get("predictions", {}).get(period, {})
    spread = getattr(odds, spread_field, {})
    if not pred or not spread:
        return None

    threshold = EDGE_THRESHOLDS.get(bet_type, 0.05)

    home_lead = pred.get(lead_home_key, 0)
    away_lead = pred.get(lead_away_key, 0)
    tie_prob = pred.get(tie_key, 0)

    # -0.5 side: must be leading (tie = loss)
    # +0.5 side: leading OR tied (tie = win)
    home_minus_prob = apply_calibration(home_lead, bet_type)
    away_plus_prob = apply_calibration(away_lead + tie_prob, bet_type)
    away_minus_prob = apply_calibration(away_lead, bet_type)
    home_plus_prob = apply_calibration(home_lead + tie_prob, bet_type)

    home_odds_val = spread.get("home_odds", -110)
    away_odds_val = spread.get("away_odds", -110)
    raw_h = american_to_implied_prob(home_odds_val)
    raw_a = american_to_implied_prob(away_odds_val)
    h_implied, a_implied = power_devig(raw_h, raw_a)

    # Determine which side has the -0.5 (favorite)
    home_point = spread.get("home", -0.5)
    if home_point < 0:
        # Home is -0.5 favorite
        home_edge = home_minus_prob - h_implied
        away_edge = away_plus_prob - a_implied
        home_label = f"home {home_point}"
        away_label = f"away +{abs(spread.get('away', 0.5))}"
        home_prob = home_minus_prob
        away_prob = away_plus_prob
    else:
        # Away is -0.5 favorite
        home_edge = home_plus_prob - h_implied
        away_edge = away_minus_prob - a_implied
        home_label = f"home +{home_point}"
        away_label = f"away {spread.get('away', -0.5)}"
        home_prob = home_plus_prob
        away_prob = away_minus_prob

    if home_edge >= threshold and home_edge >= away_edge:
        passes, wc_edge = _passes_worst_case_filter(home_prob, raw_h, raw_a)
        if not passes:
            return None
        dec = american_to_decimal(home_odds_val)
        return {
            "bet_type": bet_type,
            "side": home_label,
            "odds": home_odds_val,
            "sim_prob": round(home_prob, 4),
            "market_prob": round(h_implied, 4),
            "edge": round(home_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(home_prob, dec),
            "confidence": pred.get("confidence", "medium"),
        }
    elif away_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(away_prob, raw_a, raw_h)
        if not passes:
            return None
        dec = american_to_decimal(away_odds_val)
        return {
            "bet_type": bet_type,
            "side": away_label,
            "odds": away_odds_val,
            "sim_prob": round(away_prob, 4),
            "market_prob": round(a_implied, 4),
            "edge": round(away_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(away_prob, dec),
            "confidence": pred.get("confidence", "medium"),
        }
    return None


def check_f5_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    return _check_innings_spread_edge(
        sim, odds, "first_5", "first_5_rl", "f5_spread",
        "f5_home_lead_prob", "f5_away_lead_prob", "f5_tie_prob")


def check_nrfi_edge(sim: dict, odds: OddsData) -> dict | None:
    """NRFI: under 0.5 runs in first inning."""
    pred = sim.get("predictions", {}).get("first_inning", {})
    f1_total = odds.f1_total
    if not pred or not f1_total:
        return None

    line = f1_total.get("line")
    if line != 0.5:
        logger.warning("Skipping NRFI: F1 total line is %s, expected 0.5", line)
        return None

    threshold = EDGE_THRESHOLDS.get("nrfi", 0.06)
    nrfi_prob = pred.get("nrfi_prob", 0)
    yrfi_prob = 1 - nrfi_prob
    nrfi_prob = apply_calibration(nrfi_prob, "nrfi")
    yrfi_prob = apply_calibration(yrfi_prob, "nrfi")

    under_odds = f1_total.get("under_odds", -110)  # NRFI
    over_odds = f1_total.get("over_odds", -110)      # YRFI
    raw_nrfi = american_to_implied_prob(under_odds)
    raw_yrfi = american_to_implied_prob(over_odds)
    nrfi_implied, yrfi_implied = power_devig(raw_nrfi, raw_yrfi)

    nrfi_edge = nrfi_prob - nrfi_implied
    yrfi_edge = yrfi_prob - yrfi_implied

    if nrfi_edge >= threshold and nrfi_edge >= yrfi_edge:
        passes, wc_edge = _passes_worst_case_filter(nrfi_prob, raw_nrfi, raw_yrfi)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "nrfi",
            "side": "NRFI",
            "odds": under_odds,
            "sim_prob": round(nrfi_prob, 4),
            "market_prob": round(nrfi_implied, 4),
            "edge": round(nrfi_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(nrfi_prob, dec),
            "confidence": pred.get("confidence", "medium"),
        }
    elif yrfi_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(yrfi_prob, raw_yrfi, raw_nrfi)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "nrfi",
            "side": "YRFI",
            "odds": over_odds,
            "sim_prob": round(yrfi_prob, 4),
            "market_prob": round(yrfi_implied, 4),
            "edge": round(yrfi_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(yrfi_prob, dec),
            "confidence": pred.get("confidence", "medium"),
        }
    return None


def check_f1_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    return _check_innings_spread_edge(
        sim, odds, "first_inning", "first_1_rl", "f1_spread",
        "f1_home_lead_prob", "f1_away_lead_prob", "f1_tie_prob")


def check_f3_ml_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 moneyline — same pattern as F5 ML."""
    f3_pred = sim.get("predictions", {}).get("first_3", {})
    f3_ml = odds.f3_moneyline
    if not f3_pred or not f3_ml:
        return None

    threshold = EDGE_THRESHOLDS.get("first_3_ml", 0.05)
    home_odds = f3_ml.get("home", -110)
    away_odds = f3_ml.get("away", -110)
    raw_h = american_to_implied_prob(home_odds)
    raw_a = american_to_implied_prob(away_odds)
    h_implied, a_implied = power_devig(raw_h, raw_a)

    h_prob = f3_pred.get("f3_home_win_prob", 0)
    a_prob = f3_pred.get("f3_away_win_prob", 0)
    h_prob = apply_calibration(h_prob, "first_3_ml")
    a_prob = apply_calibration(a_prob, "first_3_ml")
    h_edge = h_prob - h_implied
    a_edge = a_prob - a_implied

    if h_edge >= threshold and h_edge >= a_edge:
        passes, wc_edge = _passes_worst_case_filter(h_prob, raw_h, raw_a)
        if not passes:
            return None
        dec = american_to_decimal(home_odds)
        return {
            "bet_type": "first_3_ml",
            "side": "home F3 ML",
            "odds": home_odds,
            "sim_prob": h_prob,
            "market_prob": round(h_implied, 4),
            "edge": round(h_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(h_prob, dec),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    elif a_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(a_prob, raw_a, raw_h)
        if not passes:
            return None
        dec = american_to_decimal(away_odds)
        return {
            "bet_type": "first_3_ml",
            "side": "away F3 ML",
            "odds": away_odds,
            "sim_prob": a_prob,
            "market_prob": round(a_implied, 4),
            "edge": round(a_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(a_prob, dec),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    return None


def check_f3_total_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 total — same pattern as F5 total with Poisson."""
    f3_pred = sim.get("predictions", {}).get("first_3", {})
    f3_total = odds.f3_total
    if not f3_pred or not f3_total:
        return None

    projected = f3_pred.get("f3_projected_total")
    if projected is None:
        return None
    line = f3_total.get("line")
    if line is None:
        return None

    threshold = EDGE_THRESHOLDS.get("first_3_total", 0.05)
    over_prob = _negbin_over_prob(float(projected), line, dispersion=1.3)
    under_prob = 1 - over_prob
    over_prob = apply_calibration(over_prob, "first_3_total")
    under_prob = apply_calibration(under_prob, "first_3_total")

    over_odds = f3_total.get("over_odds", -110)
    under_odds = f3_total.get("under_odds", -110)
    raw_over = american_to_implied_prob(over_odds)
    raw_under = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_over, raw_under)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_over, raw_under)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "first_3_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(over_prob, dec),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_under, raw_over)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "first_3_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(under_prob, dec),
            "confidence": f3_pred.get("confidence", "medium"),
        }
    return None


def check_f3_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    return _check_innings_spread_edge(
        sim, odds, "first_3", "first_3_rl", "f3_spread",
        "f3_home_lead_prob", "f3_away_lead_prob", "f3_tie_prob")


def analyze_all_edges(sim: dict, odds) -> list[dict]:
    """Run all edge checks for a single game.

    Args:
        odds: OddsData instance or plain dict (backwards compatible).
    """
    bets = []

    # If odds is a plain dict (legacy), wrap key fields for backwards compat
    if isinstance(odds, dict):
        # Legacy path: existing 5 checkers with dict access
        legacy_checkers = [
            ("moneyline", check_moneyline_edge),
            ("run_line", check_run_line_edge),
            ("total", check_total_edge),
            ("first_5_ml", check_f5_ml_edge),
            ("first_5_total", check_f5_total_edge),
        ]
        for name, checker in legacy_checkers:
            result = checker(sim, odds)
            if result:
                bets.append(result)
                logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])
        return bets

    # New path: OddsData instance — run all 12 checkers
    # Existing 5 (convert OddsData to dict for backwards compat)
    odds_dict = {
        "moneyline": odds.moneyline,
        "run_line": odds.run_line,
        "total": odds.total,
        "f5_moneyline": odds.f5_moneyline,
        "f5_total": odds.f5_total,
        "implied_probs": odds.implied_probs,
    }
    legacy_checkers = [
        ("moneyline", check_moneyline_edge),
        ("run_line", check_run_line_edge),
        ("total", check_total_edge),
        ("first_5_ml", check_f5_ml_edge),
        ("first_5_total", check_f5_total_edge),
    ]
    for name, checker in legacy_checkers:
        result = checker(sim, odds_dict)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])

    # Phase 1 new checkers (use OddsData directly)
    new_checkers = [
        ("team_total_home", lambda s, o: check_team_total_edge(s, o, "home")),
        ("team_total_away", lambda s, o: check_team_total_edge(s, o, "away")),
        ("first_5_rl", check_f5_rl_edge),
        ("nrfi", check_nrfi_edge),
        ("first_3_ml", check_f3_ml_edge),
        ("first_3_total", check_f3_total_edge),
        ("first_3_rl", check_f3_rl_edge),
    ]
    for name, checker in new_checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f", name, result["side"], result["edge"])

    # Derive moneyline from run line when ML didn't fire independently
    bet_types_found = {b["bet_type"] for b in bets}
    if "run_line" in bet_types_found and "moneyline" not in bet_types_found:
        rl_bet = next(b for b in bets if b["bet_type"] == "run_line")
        rl_prob = rl_bet["sim_prob"]
        # P(win) >= P(cover -1.5), so use RL prob as conservative ML floor
        # Boost by ~8% (avg gap between ML win% and RL cover% in MLB)
        derived_ml_prob = min(0.95, rl_prob + 0.08)
        # Determine which side the RL bet is on
        rl_side = rl_bet["side"]
        is_home = "home" in rl_side
        ml_key = "home" if is_home else "away"
        ml_odds_val = odds_dict.get("moneyline", {}).get(ml_key)
        ml_implied = odds_dict.get("implied_probs", {}).get(f"ml_{ml_key}", 0)
        if ml_odds_val and ml_implied:
            ml_edge = derived_ml_prob - ml_implied
            if ml_edge >= EDGE_THRESHOLDS["moneyline"]:
                raw_ml = american_to_implied_prob(ml_odds_val)
                raw_other = american_to_implied_prob(
                    odds_dict["moneyline"].get("away" if is_home else "home", -110)
                )
                passes, wc_edge = _passes_worst_case_filter(derived_ml_prob, raw_ml, raw_other)
                if passes:
                    dec = american_to_decimal(ml_odds_val)
                    bets.append({
                        "bet_type": "moneyline",
                        "side": ml_key,
                        "odds": ml_odds_val,
                        "sim_prob": round(derived_ml_prob, 4),
                        "market_prob": ml_implied,
                        "edge": round(ml_edge, 4),
                        "worst_case_edge": wc_edge,
                        "kelly_pct": _sized_kelly(derived_ml_prob, dec),
                        "confidence": rl_bet.get("confidence", "medium"),
                    })
                    logger.info("Derived ML from RL: %s @ %d | edge=%.3f", ml_key, ml_odds_val, ml_edge)

    # Cap suspicious edges — MLB markets are ~98% efficient, real edges are 2-8%
    MAX_EDGE = 0.15
    for bet in bets:
        if bet["edge"] > MAX_EDGE:
            logger.warning(
                "Capping edge for %s %s: %.1f%% -> %.1f%%",
                bet["bet_type"], bet["side"], bet["edge"] * 100, MAX_EDGE * 100,
            )
            bet["edge"] = MAX_EDGE
            # Recalculate kelly with capped probability
            capped_prob = bet["market_prob"] + MAX_EDGE
            dec = american_to_decimal(bet["odds"])
            bet["kelly_pct"] = _sized_kelly(capped_prob, dec)

    # Limit correlated bets: keep best 2 from {team_total_home, team_total_away,
    # first_3_total, total} per game to avoid redundant exposure
    run_cluster_types = {"team_total_home", "team_total_away", "first_3_total", "total"}
    cluster_bets = [b for b in bets if b["bet_type"] in run_cluster_types]
    if len(cluster_bets) > 2:
        cluster_bets.sort(key=lambda b: b["edge"], reverse=True)
        drop = {id(b) for b in cluster_bets[2:]}
        bets = [b for b in bets if id(b) not in drop]
        logger.info("Correlated bet limit: kept top 2 of %d run-cluster bets", len(cluster_bets))

    bets = apply_bet_filters(bets)

    logger.info("Edge analysis: %d bet types have value", len(bets))
    return bets
