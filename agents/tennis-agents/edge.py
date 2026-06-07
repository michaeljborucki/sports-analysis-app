"""Edge detection and Kelly criterion sizing for tennis bet types."""
import logging
import statistics
from calibrate import apply_calibration
from config import (
    EDGE_THRESHOLDS, TOUR_CONFIG,
    CONVICTION_MIN_MODELS, CONVICTION_MIN_EDGE, CONVICTION_KELLY_MULT,
)
from scrapers.odds import american_to_implied_prob, power_devig

logger = logging.getLogger("mirofish.edge")

CONFIDENCE_MULTIPLIER = {"high": 1.0, "medium": 0.7, "low": 0.4}
MAX_KELLY_PCT = 0.05  # Never risk more than 5% of bankroll on one bet


def american_to_decimal(odds: int) -> float:
    if odds < 0:
        return round(100 / abs(odds) + 1, 4)
    return round(odds / 100 + 1, 4)


def kelly_criterion(prob: float, decimal_odds: float) -> float:
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


def check_moneyline_edge(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = EDGE_THRESHOLDS["moneyline"]
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]

    a_prob_raw = ml_pred.get("player_a_win_prob", 0)
    b_prob_raw = ml_pred.get("player_b_win_prob", 0)
    a_prob = apply_calibration(a_prob_raw, "moneyline")
    b_prob = apply_calibration(b_prob_raw, "moneyline")

    a_implied = odds.get("implied_probs", {}).get("player_a", 0)
    a_edge = a_prob - a_implied
    b_implied = odds.get("implied_probs", {}).get("player_b", 0)
    b_edge = b_prob - b_implied

    confidence = ml_pred.get("confidence", "medium")
    conf_mult = CONFIDENCE_MULTIPLIER.get(confidence, 0.7)

    raw_a = american_to_implied_prob(ml_odds["player_a"])
    raw_b = american_to_implied_prob(ml_odds["player_b"])

    if a_edge >= threshold and a_edge >= b_edge:
        passes, wc_edge = _passes_worst_case_filter(a_prob, raw_a, raw_b)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["player_a"])
        kelly_pct = round(kelly_criterion(a_prob, dec) * kelly_frac * conf_mult, 4)
        kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
        return {
            "bet_type": "moneyline", "side": "player_a",
            "odds": ml_odds["player_a"], "sim_prob": a_prob,
            "sim_prob_raw": round(float(a_prob_raw), 4),
            "market_prob": a_implied, "edge": round(a_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_pct,
            "confidence": confidence,
        }
    elif b_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(b_prob, raw_b, raw_a)
        if not passes:
            return None
        dec = american_to_decimal(ml_odds["player_b"])
        kelly_pct = round(kelly_criterion(b_prob, dec) * kelly_frac * conf_mult, 4)
        kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
        return {
            "bet_type": "moneyline", "side": "player_b",
            "odds": ml_odds["player_b"], "sim_prob": b_prob,
            "sim_prob_raw": round(float(b_prob_raw), 4),
            "market_prob": b_implied, "edge": round(b_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_pct,
            "confidence": confidence,
        }
    return None


def check_game_handicap_edge(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    gh_pred = sim.get("predictions", {}).get("game_handicap", {})
    gh_odds = odds.get("game_handicap", {})
    if not gh_pred or not gh_odds:
        return None

    threshold = EDGE_THRESHOLDS["game_handicap"]
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]
    fav_prob_raw = gh_pred.get("favorite_cover_prob", 0)
    fav_prob = apply_calibration(fav_prob_raw, "game_handicap")

    a_point = gh_odds.get("player_a_point", 0)
    a_odds = gh_odds.get("player_a_odds", -110)
    b_odds = gh_odds.get("player_b_odds", -110)

    a_is_fav = a_point < 0
    fav_odds = a_odds if a_is_fav else b_odds
    dog_odds = b_odds if a_is_fav else a_odds
    fav_label = f"player_a {a_point}" if a_is_fav else f"player_b {gh_odds.get('player_b_point', 0)}"
    dog_label = f"player_b {gh_odds.get('player_b_point', 0)}" if a_is_fav else f"player_a {a_point}"

    raw_fav = american_to_implied_prob(fav_odds)
    raw_dog = american_to_implied_prob(dog_odds)
    fav_implied, dog_implied = power_devig(raw_fav, raw_dog)

    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    confidence = gh_pred.get("confidence", "medium")
    conf_mult = CONFIDENCE_MULTIPLIER.get(confidence, 0.7)

    if fav_edge >= threshold and fav_edge >= dog_edge:
        passes, wc_edge = _passes_worst_case_filter(fav_prob, raw_fav, raw_dog)
        if not passes:
            return None
        dec = american_to_decimal(fav_odds)
        kelly_pct = round(kelly_criterion(fav_prob, dec) * kelly_frac * conf_mult, 4)
        kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
        return {
            "bet_type": "game_handicap", "side": fav_label,
            "odds": fav_odds, "sim_prob": fav_prob,
            "sim_prob_raw": round(float(fav_prob_raw), 4),
            "market_prob": round(fav_implied, 4), "edge": round(fav_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_pct,
            "confidence": confidence,
        }
    elif dog_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(1 - fav_prob, raw_dog, raw_fav)
        if not passes:
            return None
        dec = american_to_decimal(dog_odds)
        kelly_pct = round(kelly_criterion(1 - fav_prob, dec) * kelly_frac * conf_mult, 4)
        kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
        return {
            "bet_type": "game_handicap", "side": dog_label,
            "odds": dog_odds, "sim_prob": round(1 - fav_prob, 4),
            "sim_prob_raw": round(1 - float(fav_prob_raw), 4),
            "market_prob": round(dog_implied, 4), "edge": round(dog_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_pct,
            "confidence": confidence,
        }
    return None


def check_total_games_edge(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    tg_pred = sim.get("predictions", {}).get("total_games", {})
    tg_odds = odds.get("total_games", {})
    if not tg_pred or not tg_odds:
        return None

    threshold = EDGE_THRESHOLDS["total_games"]
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]

    over_prob_raw = tg_pred.get("over_prob", 0)
    under_prob_raw = tg_pred.get("under_prob", 0)
    over_prob = apply_calibration(over_prob_raw, "total_games")
    under_prob = apply_calibration(under_prob_raw, "total_games")
    over_odds = tg_odds.get("over_odds", -110)
    under_odds = tg_odds.get("under_odds", -110)
    raw_o = american_to_implied_prob(over_odds)
    raw_u = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_o, raw_u)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied
    line = tg_odds.get("line", "?")

    confidence = tg_pred.get("confidence", "medium")
    conf_mult = CONFIDENCE_MULTIPLIER.get(confidence, 0.7)

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_o, raw_u)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        kelly_pct = round(kelly_criterion(over_prob, dec) * kelly_frac * conf_mult, 4)
        kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
        return {
            "bet_type": "total_games", "side": f"over {line}",
            "odds": over_odds, "sim_prob": over_prob,
            "sim_prob_raw": round(float(over_prob_raw), 4),
            "market_prob": round(over_implied, 4), "edge": round(over_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_pct,
            "confidence": confidence,
        }
    elif under_edge >= threshold:
        passes, wc_edge = _passes_worst_case_filter(under_prob, raw_u, raw_o)
        if not passes:
            return None
        dec = american_to_decimal(under_odds)
        kelly_pct = round(kelly_criterion(under_prob, dec) * kelly_frac * conf_mult, 4)
        kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
        return {
            "bet_type": "total_games", "side": f"under {line}",
            "odds": under_odds, "sim_prob": under_prob,
            "sim_prob_raw": round(float(under_prob_raw), 4),
            "market_prob": round(under_implied, 4), "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": kelly_pct,
            "confidence": confidence,
        }
    return None


def _conviction_agreement(model_probs: dict, market_prob: float, bet_type: str,
                           min_edge: float = CONVICTION_MIN_EDGE) -> tuple[float | None, int]:
    """Count models whose (calibrated) prob beats market_prob by ``min_edge``.

    Returns ``(agreeing_prob_median, count)`` if count ≥ CONVICTION_MIN_MODELS,
    else ``(None, count)``. Used by the Option B fallback — see
    ``config.CONVICTION_MIN_MODELS``.
    """
    if not model_probs:
        return None, 0
    agreeing = []
    for raw_prob in model_probs.values():
        try:
            p = apply_calibration(float(raw_prob), bet_type)
        except (TypeError, ValueError):
            continue
        if (p - market_prob) >= min_edge:
            agreeing.append(p)
    if len(agreeing) >= CONVICTION_MIN_MODELS:
        return round(statistics.median(agreeing), 4), len(agreeing)
    return None, len(agreeing)


def _conviction_bet(bet_type: str, side: str, odds_american: int,
                    sim_prob: float, sim_prob_raw: float, market_prob: float,
                    tour: str, agreeing_count: int,
                    raw_own: float, raw_other: float,
                    confidence: str = "medium") -> dict | None:
    """Build an individual-conviction fallback bet dict. Returns None if the
    worst-case-vig filter still rejects it."""
    passes, wc_edge = _passes_worst_case_filter(sim_prob, raw_own, raw_other)
    if not passes:
        return None
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]
    conf_mult = CONFIDENCE_MULTIPLIER.get(confidence, 0.7)
    dec = american_to_decimal(odds_american)
    kelly_pct = round(
        kelly_criterion(sim_prob, dec) * kelly_frac * conf_mult * CONVICTION_KELLY_MULT,
        4,
    )
    kelly_pct = min(kelly_pct, MAX_KELLY_PCT)
    return {
        "bet_type": bet_type, "side": side,
        "odds": odds_american, "sim_prob": round(float(sim_prob), 4),
        "sim_prob_raw": round(float(sim_prob_raw), 4),
        "market_prob": round(float(market_prob), 4),
        "edge": round(sim_prob - market_prob, 4),
        "worst_case_edge": wc_edge,
        "kelly_pct": kelly_pct,
        "confidence": confidence,
        "source": "individual_conviction",
        "conviction_models": agreeing_count,
    }


def check_moneyline_conviction(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    per_model = ml_pred.get("_per_model_medians", {})
    a_model_probs = per_model.get("player_a_win_prob", {})
    if not ml_odds or not a_model_probs:
        return None

    a_implied = odds.get("implied_probs", {}).get("player_a", 0)
    b_implied = odds.get("implied_probs", {}).get("player_b", 0)
    # Per-model B-side probs = 1 - A-side prob (they sum to 1 per model).
    b_model_probs = {mk: 1 - p for mk, p in a_model_probs.items()}

    a_prob, a_count = _conviction_agreement(a_model_probs, a_implied, "moneyline")
    b_prob, b_count = _conviction_agreement(b_model_probs, b_implied, "moneyline")

    raw_a = american_to_implied_prob(ml_odds["player_a"])
    raw_b = american_to_implied_prob(ml_odds["player_b"])
    confidence = ml_pred.get("confidence", "medium")

    # Tie-break: whichever side has more agreeing models wins. If tied in
    # count, take the larger edge side. If still tied, abstain.
    if a_prob and (not b_prob or a_count > b_count or
                   (a_count == b_count and (a_prob - a_implied) >= (b_prob - b_implied))):
        # Use median of agreeing models as the raw prob (pre-calibration was
        # applied inside _conviction_agreement so a_prob is already calibrated).
        raw_from_models = statistics.median(
            p for p in a_model_probs.values() if apply_calibration(p, "moneyline") - a_implied >= CONVICTION_MIN_EDGE
        )
        return _conviction_bet(
            "moneyline", "player_a", ml_odds["player_a"],
            sim_prob=a_prob, sim_prob_raw=raw_from_models,
            market_prob=a_implied, tour=tour, agreeing_count=a_count,
            raw_own=raw_a, raw_other=raw_b, confidence=confidence,
        )
    if b_prob:
        raw_from_models = statistics.median(
            (1 - p) for p in a_model_probs.values()
            if apply_calibration(1 - p, "moneyline") - b_implied >= CONVICTION_MIN_EDGE
        )
        return _conviction_bet(
            "moneyline", "player_b", ml_odds["player_b"],
            sim_prob=b_prob, sim_prob_raw=raw_from_models,
            market_prob=b_implied, tour=tour, agreeing_count=b_count,
            raw_own=raw_b, raw_other=raw_a, confidence=confidence,
        )
    return None


def check_game_handicap_conviction(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    gh_pred = sim.get("predictions", {}).get("game_handicap", {})
    gh_odds = odds.get("game_handicap", {})
    per_model = gh_pred.get("_per_model_medians", {})
    fav_model_probs = per_model.get("favorite_cover_prob", {})
    if not gh_odds or not fav_model_probs:
        return None

    a_point = gh_odds.get("player_a_point", 0)
    a_odds = gh_odds.get("player_a_odds", -110)
    b_odds = gh_odds.get("player_b_odds", -110)
    a_is_fav = a_point < 0
    fav_odds = a_odds if a_is_fav else b_odds
    dog_odds = b_odds if a_is_fav else a_odds
    fav_label = f"player_a {a_point}" if a_is_fav else f"player_b {gh_odds.get('player_b_point', 0)}"
    dog_label = f"player_b {gh_odds.get('player_b_point', 0)}" if a_is_fav else f"player_a {a_point}"

    raw_fav = american_to_implied_prob(fav_odds)
    raw_dog = american_to_implied_prob(dog_odds)
    fav_implied, dog_implied = power_devig(raw_fav, raw_dog)

    dog_model_probs = {mk: 1 - p for mk, p in fav_model_probs.items()}
    fav_prob, fav_count = _conviction_agreement(fav_model_probs, fav_implied, "game_handicap")
    dog_prob, dog_count = _conviction_agreement(dog_model_probs, dog_implied, "game_handicap")
    confidence = gh_pred.get("confidence", "medium")

    if fav_prob and (not dog_prob or fav_count > dog_count or
                     (fav_count == dog_count and (fav_prob - fav_implied) >= (dog_prob - dog_implied))):
        raw_from_models = statistics.median(
            p for p in fav_model_probs.values()
            if apply_calibration(p, "game_handicap") - fav_implied >= CONVICTION_MIN_EDGE
        )
        return _conviction_bet(
            "game_handicap", fav_label, fav_odds,
            sim_prob=fav_prob, sim_prob_raw=raw_from_models,
            market_prob=fav_implied, tour=tour, agreeing_count=fav_count,
            raw_own=raw_fav, raw_other=raw_dog, confidence=confidence,
        )
    if dog_prob:
        raw_from_models = statistics.median(
            (1 - p) for p in fav_model_probs.values()
            if apply_calibration(1 - p, "game_handicap") - dog_implied >= CONVICTION_MIN_EDGE
        )
        return _conviction_bet(
            "game_handicap", dog_label, dog_odds,
            sim_prob=dog_prob, sim_prob_raw=raw_from_models,
            market_prob=dog_implied, tour=tour, agreeing_count=dog_count,
            raw_own=raw_dog, raw_other=raw_fav, confidence=confidence,
        )
    return None


def check_total_games_conviction(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    tg_pred = sim.get("predictions", {}).get("total_games", {})
    tg_odds = odds.get("total_games", {})
    per_model = tg_pred.get("_per_model_medians", {})
    over_model_probs = per_model.get("over_prob", {})
    if not tg_odds or not over_model_probs:
        return None

    over_odds = tg_odds.get("over_odds", -110)
    under_odds = tg_odds.get("under_odds", -110)
    raw_o = american_to_implied_prob(over_odds)
    raw_u = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_o, raw_u)
    line = tg_odds.get("line", "?")

    # Prefer explicit under_prob per-model medians if present; else derive.
    under_model_probs = per_model.get("under_prob") or {mk: 1 - p for mk, p in over_model_probs.items()}

    over_prob, over_count = _conviction_agreement(over_model_probs, over_implied, "total_games")
    under_prob, under_count = _conviction_agreement(under_model_probs, under_implied, "total_games")
    confidence = tg_pred.get("confidence", "medium")

    if over_prob and (not under_prob or over_count > under_count or
                     (over_count == under_count and (over_prob - over_implied) >= (under_prob - under_implied))):
        raw_from_models = statistics.median(
            p for p in over_model_probs.values()
            if apply_calibration(p, "total_games") - over_implied >= CONVICTION_MIN_EDGE
        )
        return _conviction_bet(
            "total_games", f"over {line}", over_odds,
            sim_prob=over_prob, sim_prob_raw=raw_from_models,
            market_prob=over_implied, tour=tour, agreeing_count=over_count,
            raw_own=raw_o, raw_other=raw_u, confidence=confidence,
        )
    if under_prob:
        raw_from_models = statistics.median(
            p for p in under_model_probs.values()
            if apply_calibration(p, "total_games") - under_implied >= CONVICTION_MIN_EDGE
        )
        return _conviction_bet(
            "total_games", f"under {line}", under_odds,
            sim_prob=under_prob, sim_prob_raw=raw_from_models,
            market_prob=under_implied, tour=tour, agreeing_count=under_count,
            raw_own=raw_u, raw_other=raw_o, confidence=confidence,
        )
    return None


def analyze_all_edges(sim: dict, odds: dict, tour: str = "atp") -> list[dict]:
    bets = []
    checkers = [
        ("moneyline",     check_moneyline_edge,     check_moneyline_conviction),
        ("game_handicap", check_game_handicap_edge, check_game_handicap_conviction),
        ("total_games",   check_total_games_edge,   check_total_games_conviction),
    ]
    for name, primary, fallback in checkers:
        result = primary(sim, odds, tour=tour)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f kelly=%.4f",
                         name, result["side"], result["edge"], result["kelly_pct"])
            continue
        # Option B — individual-model-conviction fallback.
        result = fallback(sim, odds, tour=tour)
        if result:
            bets.append(result)
            logger.info(
                "Conviction fallback: %s %s | edge=%.3f (%d models agree) kelly=%.4f",
                name, result["side"], result["edge"],
                result.get("conviction_models", 0), result["kelly_pct"],
            )
        else:
            logger.debug("Edge check %s: no value (primary + fallback)", name)
    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets


def _bet_filter_reason(bet: dict, rules: dict) -> str | None:
    """Return a short reason string if ``bet`` fails any rule, else None."""
    if rules.get("disabled"):
        return "bet_type disabled"
    try:
        edge = float(bet.get("edge", 0) or 0)
    except (TypeError, ValueError):
        edge = 0.0
    min_e = rules.get("min_edge")
    if min_e is not None and edge < float(min_e):
        return f"edge {edge:.3f} below min_edge {min_e}"
    max_e = rules.get("max_edge")
    if max_e is not None and edge > float(max_e):
        return f"edge {edge:.3f} above max_edge {max_e}"
    side_contains = rules.get("side_contains")
    if side_contains:
        side = str(bet.get("side", "")).lower()
        if not any(str(s).lower() in side for s in side_contains):
            return f"side '{bet.get('side')}' not in side_contains {side_contains}"
    odds_min = rules.get("odds_min")
    if odds_min is not None:
        try:
            if int(bet.get("odds")) < int(odds_min):
                return f"odds below odds_min {odds_min}"
        except (TypeError, ValueError):
            pass
    odds_max = rules.get("odds_max")
    if odds_max is not None:
        try:
            if int(bet.get("odds")) > int(odds_max):
                return f"odds above odds_max {odds_max}"
        except (TypeError, ValueError):
            pass
    line_in = rules.get("line_in")
    if line_in:
        side_str = str(bet.get("side", ""))
        tokens = side_str.split()
        line_val = None
        if len(tokens) >= 2:
            try:
                line_val = float(tokens[1])
            except ValueError:
                pass
        if line_val is None or line_val not in [float(x) for x in line_in]:
            return f"line not in line_in {line_in}"
    return None


def apply_bet_filters(bets: list[dict]) -> list[dict]:
    """Drop bets that fail per-type rules in ``config.BET_FILTERS``.

    Called AFTER ``analyze_all_edges`` and BEFORE ``log_bet``. Rejections are
    logged at INFO level so pipeline output shows why a flagged bet didn't land.
    Bet types absent from BET_FILTERS pass through unchanged.
    """
    from config import BET_FILTERS
    out = []
    for bet in bets:
        rules = BET_FILTERS.get(bet.get("bet_type"))
        if not rules:
            out.append(bet)
            continue
        reason = _bet_filter_reason(bet, rules)
        if reason is None:
            out.append(bet)
        else:
            logger.info(
                "FILTERED %s %s @ %s (edge=%s): %s",
                bet.get("bet_type"), bet.get("side", "?"), bet.get("odds", "?"),
                bet.get("edge"), reason,
            )
    return out
