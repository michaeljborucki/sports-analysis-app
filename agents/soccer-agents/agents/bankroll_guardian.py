"""Bankroll guardian: daily exposure cap + drawdown circuit breaker + Kelly annealer.

Runs as a pre-bet gate. Stateless — reads the bet log each call.

Rules (tunable in BANKROLL_RULES below):
  - Kelly annealer: trailing 7d P&L ≤ -10u → multiply all kelly stakes by 0.5
                    trailing 7d P&L ≤ -15u → multiply by 0.25
  - Daily exposure cap: sum of today's kelly_pct capped at 5% of bankroll;
    overflow → proportional rescale.
  - Circuit breaker: trailing 7d P&L ≤ -20u → block all new bets (return empty).
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

import pandas as pd

from tracker import load_bets

logger = logging.getLogger("mirofish.bankroll_guardian")

BANKROLL_RULES = {
    "daily_exposure_cap_pct": 0.05,       # 5% of bankroll per day
    "soft_drawdown_threshold_u": -10.0,   # trigger 0.5x Kelly
    "soft_drawdown_multiplier": 0.5,
    "hard_drawdown_threshold_u": -15.0,   # trigger 0.25x Kelly
    "hard_drawdown_multiplier": 0.25,
    "circuit_breaker_threshold_u": -20.0, # block all new bets
    "rolling_window_days": 7,
}


def _trailing_profit(df: pd.DataFrame, days: int) -> float:
    if df.empty or "date" not in df:
        return 0.0
    cutoff = pd.Timestamp(date.today() - timedelta(days=days))
    parsed = pd.to_datetime(df["date"], errors="coerce")
    recent = df[parsed >= cutoff]
    profits = pd.to_numeric(recent.get("profit"), errors="coerce").dropna()
    return float(profits.sum())


def compute_bankroll_state() -> dict:
    """Compute current guardian state (multiplier, circuit breaker, exposure)."""
    df = load_bets()
    rules = BANKROLL_RULES
    trailing = _trailing_profit(df, rules["rolling_window_days"])

    multiplier = 1.0
    status = "normal"
    if trailing <= rules["circuit_breaker_threshold_u"]:
        multiplier = 0.0
        status = "circuit_breaker"
    elif trailing <= rules["hard_drawdown_threshold_u"]:
        multiplier = rules["hard_drawdown_multiplier"]
        status = "hard_drawdown"
    elif trailing <= rules["soft_drawdown_threshold_u"]:
        multiplier = rules["soft_drawdown_multiplier"]
        status = "soft_drawdown"

    today = date.today().isoformat()
    today_bets = df[df["date"] == today]
    today_exposure = pd.to_numeric(today_bets.get("kelly_pct"), errors="coerce").dropna().sum()

    return {
        "trailing_profit_u": round(trailing, 2),
        "kelly_multiplier": multiplier,
        "status": status,
        "today_exposure_pct": round(float(today_exposure), 4),
        "daily_cap_pct": rules["daily_exposure_cap_pct"],
    }


def gate_bets(bets: list[dict]) -> list[dict]:
    """Apply guardian rules to a slate of bets. Mutates and returns in place.

    Input bets already have post-correlation kelly_pct. This pass:
      1. Multiplies by the drawdown multiplier (kelly_annealed).
      2. If sum exceeds remaining daily capacity, proportionally rescales.
      3. Returns [] if circuit breaker is tripped.
    """
    if not bets:
        return bets

    state = compute_bankroll_state()
    if state["status"] == "circuit_breaker":
        logger.warning(
            "BANKROLL CIRCUIT BREAKER: trailing 7d P&L = %.2fu (<= %.1fu). Blocking %d bet(s).",
            state["trailing_profit_u"],
            BANKROLL_RULES["circuit_breaker_threshold_u"], len(bets),
        )
        return []

    mult = state["kelly_multiplier"]
    if mult != 1.0:
        logger.warning(
            "Bankroll guardian: drawdown status=%s, trailing=%.2fu → scaling Kelly by %.2fx",
            state["status"], state["trailing_profit_u"], mult,
        )

    remaining = max(0.0, state["daily_cap_pct"] - state["today_exposure_pct"])
    for bet in bets:
        bet["kelly_pct_pre_guardian"] = bet.get("kelly_pct", 0)
        bet["kelly_pct"] = round(float(bet.get("kelly_pct", 0)) * mult, 4)

    batch_sum = sum(float(b.get("kelly_pct", 0)) for b in bets)
    if batch_sum > remaining > 0 and batch_sum > 0:
        scale = remaining / batch_sum
        logger.warning(
            "Daily exposure cap: batch=%.3f, remaining=%.3f → rescaling by %.2fx",
            batch_sum, remaining, scale,
        )
        for bet in bets:
            bet["kelly_pct"] = round(float(bet.get("kelly_pct", 0)) * scale, 4)
    elif remaining <= 0:
        logger.warning(
            "Daily exposure cap reached (%.3f of %.3f) — blocking new bets",
            state["today_exposure_pct"], state["daily_cap_pct"],
        )
        return []

    return bets
