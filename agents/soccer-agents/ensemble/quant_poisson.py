"""Non-LLM quant voter: bivariate Poisson with Dixon-Coles low-score correction.

Competes alongside the 6 LLM panel models as a 7th voter. Exploits soccer's
Poisson-distributed goal count plus the well-documented draw-clustering
adjustment. Runs in <1ms per match so it's effectively free.

References:
  Dixon & Coles (1997). Modelling Association Football Scores and Inefficiencies
  in the Football Betting Market. Applied Statistics, 46(2), 265-280.
"""
from __future__ import annotations
import logging
import math

logger = logging.getLogger("mirofish.ensemble.quant_poisson")

MAX_GOALS = 8  # truncation; contribution beyond this is < 1e-6
DIXON_COLES_RHO = -0.15  # draw-clustering; negative values inflate 0-0 / 1-1


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _dc_tau(h: int, a: int, lam_h: float, lam_a: float, rho: float) -> float:
    """Dixon-Coles low-score correction factor."""
    if h == 0 and a == 0:
        return 1 - lam_h * lam_a * rho
    if h == 0 and a == 1:
        return 1 + lam_h * rho
    if h == 1 and a == 0:
        return 1 + lam_a * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def _score_matrix(lam_h: float, lam_a: float, rho: float = DIXON_COLES_RHO) -> list[list[float]]:
    """Full joint P(home=h, away=a) matrix with Dixon-Coles."""
    mat = [[0.0] * (MAX_GOALS + 1) for _ in range(MAX_GOALS + 1)]
    total = 0.0
    for h in range(MAX_GOALS + 1):
        p_h = _poisson_pmf(h, lam_h)
        for a in range(MAX_GOALS + 1):
            p_a = _poisson_pmf(a, lam_a)
            mat[h][a] = p_h * p_a * _dc_tau(h, a, lam_h, lam_a, rho)
            total += mat[h][a]
    if total > 0:
        for h in range(MAX_GOALS + 1):
            for a in range(MAX_GOALS + 1):
                mat[h][a] /= total
    return mat


def _ah_cover_prob(mat: list[list[float]], home_handicap: float) -> tuple[float, float]:
    """P(home covers handicap) and P(away covers -handicap). Splits pushes."""
    p_home = 0.0
    p_away = 0.0
    p_push = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            margin = (h - a) + home_handicap
            if margin > 1e-9:
                p_home += mat[h][a]
            elif margin < -1e-9:
                p_away += mat[h][a]
            else:
                p_push += mat[h][a]
    p_home += p_push / 2
    p_away += p_push / 2
    return round(p_home, 4), round(p_away, 4)


def _total_prob(mat: list[list[float]], line: float) -> tuple[float, float]:
    """P(over) and P(under) for a goal total line."""
    p_over = 0.0
    p_under = 0.0
    p_push = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            goals = h + a
            if goals > line:
                p_over += mat[h][a]
            elif goals < line:
                p_under += mat[h][a]
            else:
                p_push += mat[h][a]
    p_over += p_push / 2
    p_under += p_push / 2
    return round(p_over, 4), round(p_under, 4)


def _btts_prob(mat: list[list[float]]) -> tuple[float, float]:
    """P(both teams score) and its complement."""
    p_yes = 0.0
    for h in range(1, MAX_GOALS + 1):
        for a in range(1, MAX_GOALS + 1):
            p_yes += mat[h][a]
    p_no = 1.0 - p_yes
    return round(p_yes, 4), round(p_no, 4)


def _expected_lambdas(home_xg: float, away_xg: float,
                      home_xga: float, away_xga: float,
                      home_advantage: float) -> tuple[float, float]:
    """Blend a team's xG-for with the opponent's xGA. Apply home-advantage tilt."""
    lam_h = (home_xg + away_xga) / 2.0
    lam_a = (away_xg + home_xga) / 2.0
    tilt = 1.0 + home_advantage
    lam_h *= tilt
    lam_a *= max(0.1, 2.0 - tilt)
    lam_h = max(0.15, min(5.0, lam_h))
    lam_a = max(0.15, min(5.0, lam_a))
    return lam_h, lam_a


def predict(match_data: dict, home_advantage: float = 0.10) -> dict | None:
    """Build a synthetic ensemble-result dict for the Poisson voter.

    Returns a dict shaped like an LLM `parsed` result so the existing
    consensus/weighting machinery handles it unchanged. Returns None if
    required inputs are missing.
    """
    odds = match_data.get("odds", {})
    home_xg = _num(match_data.get("home_xg", {}).get("xg_per_match"))
    away_xg = _num(match_data.get("away_xg", {}).get("xg_per_match"))
    home_xga = _num(match_data.get("home_xg", {}).get("xga_per_match"))
    away_xga = _num(match_data.get("away_xg", {}).get("xga_per_match"))

    if None in (home_xg, away_xg, home_xga, away_xga):
        logger.debug("Quant Poisson skipped: missing xG inputs")
        return None

    ah = odds.get("asian_handicap", {}) or {}
    total = odds.get("total", {}) or {}
    home_handicap = _num(ah.get("home")) or -0.5
    total_line = _num(total.get("line")) or 2.5

    lam_h, lam_a = _expected_lambdas(home_xg, away_xg, home_xga, away_xga, home_advantage)
    mat = _score_matrix(lam_h, lam_a)

    home_cover, away_cover = _ah_cover_prob(mat, home_handicap)
    over_p, under_p = _total_prob(mat, total_line)
    btts_yes, btts_no = _btts_prob(mat)

    ah_side = "home" if home_cover >= away_cover else "away"
    total_side = "over" if over_p >= under_p else "under"
    btts_side = "yes" if btts_yes >= btts_no else "no"

    logger.info(
        "Quant Poisson: λ_h=%.2f λ_a=%.2f | AH(%.2f): %s %.3f | O/U %.1f: over %.3f | BTTS: yes %.3f",
        lam_h, lam_a, home_handicap, ah_side, max(home_cover, away_cover),
        total_line, over_p, btts_yes,
    )

    return {
        "predictions": {
            "asian_handicap": {
                "home_cover_prob": home_cover,
                "away_cover_prob": away_cover,
                "value_side": ah_side,
                "confidence": "medium",
            },
            "total": {
                "over_prob": over_p,
                "under_prob": under_p,
                "projected_goals": round(lam_h + lam_a, 2),
                "value_side": total_side,
                "confidence": "medium",
            },
            "btts": {
                "btts_yes_prob": btts_yes,
                "btts_no_prob": btts_no,
                "value_side": btts_side,
                "confidence": "medium",
            },
            "predicted_score": {"home": round(lam_h), "away": round(lam_a)},
        },
        "key_factors": [
            f"quant_poisson: λ_h={lam_h:.2f}, λ_a={lam_a:.2f}, DC ρ={DIXON_COLES_RHO}",
        ],
    }


def _num(v) -> float | None:
    if v is None or v == "" or v == "N/A":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def synthetic_run_result(match_data: dict, home_advantage: float = 0.10) -> dict | None:
    """Wrap predict() in the shape run_single_model returns."""
    parsed = predict(match_data, home_advantage)
    if not parsed:
        return None
    return {
        "model_key": "quant_poisson",
        "parsed": parsed,
        "temperature": 0.0,
        "cost": 0.0,
        "raw": "",
    }
