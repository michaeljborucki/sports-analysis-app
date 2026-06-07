"""Edge detection and Kelly criterion sizing for all bet types.

Market probability is computed as a consensus across all available sportsbooks
using power-method devigging, providing a more accurate "true" market probability
than any single book's odds.
"""
import json
import os
from config import EDGE_THRESHOLDS, KELLY_FRACTION, DATA_DIR
from scrapers.odds import american_to_implied_prob

_overrides_cache = None

def _load_overrides() -> dict:
    """Load edge threshold overrides from data/edge_overrides.json (cached)."""
    global _overrides_cache
    if _overrides_cache is not None:
        return _overrides_cache
    path = os.path.join(DATA_DIR, "edge_overrides.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                _overrides_cache = json.load(f)
        except (json.JSONDecodeError, IOError):
            _overrides_cache = {}
    else:
        _overrides_cache = {}
    return _overrides_cache


def get_edge_threshold(bet_type: str) -> float | None:
    """Get effective edge threshold. Returns None if bet type is disabled."""
    overrides = _load_overrides()
    if bet_type in overrides:
        val = overrides[bet_type]
        return val  # None means disabled, float means override
    return EDGE_THRESHOLDS.get(bet_type, 0.05)


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


def _predicted_score_str(sim: dict) -> str:
    """Extract predicted score as 'away-home' string, or '' if unavailable."""
    ps = sim.get("predictions", {}).get("predicted_score", {})
    if ps and "home" in ps and "away" in ps:
        return f"{ps['away']}-{ps['home']}"
    return ""


def _get_implied(odds: dict, key: str, fallback: float = 0.5) -> float:
    """Get consensus implied prob from odds dict, falling back to single-book devig."""
    return odds.get("implied_probs", {}).get(key, fallback)


def _passes_worst_case(sim_prob: float, odds: dict, worst_key: str) -> bool:
    """Secondary filter: reject bet if edge <= 0 under worst-case (least favorable book).

    For each market, the worst-case implied prob is the HIGHEST devigged probability
    across all sportsbooks. If our model probability doesn't exceed even the most
    aggressive book's line, the bet is too risky.
    """
    worst = odds.get("implied_probs", {}).get(worst_key)
    if worst is None:
        return True  # No worst-case data available, don't filter
    return sim_prob > worst


def check_moneyline_edge(sim: dict, odds: dict) -> dict | None:
    """Check for moneyline value on either side."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = get_edge_threshold("moneyline")
    if threshold is None:
        return None
    proj = _predicted_score_str(sim)

    # Use multi-book consensus implied probability
    home_market = _get_implied(odds, "ml_home")
    away_market = _get_implied(odds, "ml_away")

    # Check home
    home_prob = ml_pred.get("home_win_prob", 0)
    home_edge = home_prob - home_market

    # Check away
    away_prob = ml_pred.get("away_win_prob", 0)
    away_edge = away_prob - away_market

    # Take the side with more edge (worst-case filter: must beat the least favorable book)
    if home_edge >= threshold and home_edge >= away_edge and _passes_worst_case(home_prob, odds, "ml_home_worst"):
        dec = american_to_decimal(ml_odds["home"])
        return {
            "bet_type": "moneyline",
            "side": "home",
            "odds": ml_odds["home"],
            "sim_prob": home_prob,
            "market_prob": round(home_market, 4),
            "edge": round(home_edge, 4),
            "kelly_pct": round(kelly_criterion(home_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
            "projected": proj,
        }
    if away_edge >= threshold and _passes_worst_case(away_prob, odds, "ml_away_worst"):
        dec = american_to_decimal(ml_odds["away"])
        return {
            "bet_type": "moneyline",
            "side": "away",
            "odds": ml_odds["away"],
            "sim_prob": away_prob,
            "market_prob": round(away_market, 4),
            "edge": round(away_edge, 4),
            "kelly_pct": round(kelly_criterion(away_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
            "projected": proj,
        }

    return None


def check_spread_edge(sim: dict, odds: dict) -> dict | None:
    """Check for spread value. Determines favorite by spread point, not position."""
    sp_pred = sim.get("predictions", {}).get("spread", {})
    sp_odds = odds.get("spread", {})
    if not sp_pred or not sp_odds:
        return None

    threshold = get_edge_threshold("spread")
    if threshold is None:
        return None
    fav_prob = sp_pred.get("favorite_cover_prob", 0)
    proj = _predicted_score_str(sim)

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

    # Derive probability from predicted score margin if available
    predicted_score = sim.get("predictions", {}).get("predicted_score", {})
    if predicted_score and "home" in predicted_score and "away" in predicted_score:
        predicted_margin = predicted_score["home"] - predicted_score["away"]
        if home_is_fav:
            delta = predicted_margin - abs(home_point)
        else:
            delta = -predicted_margin - abs(home_point)
        fav_prob = min(max(0.5 + delta * 0.04, 0.01), 0.99)

    # Use multi-book consensus implied probability for spread
    if home_is_fav:
        fav_market = _get_implied(odds, "spread_home")
        dog_market = _get_implied(odds, "spread_away")
        fav_worst_key = "spread_home_worst"
        dog_worst_key = "spread_away_worst"
    else:
        fav_market = _get_implied(odds, "spread_away")
        dog_market = _get_implied(odds, "spread_home")
        fav_worst_key = "spread_away_worst"
        dog_worst_key = "spread_home_worst"

    fav_edge = fav_prob - fav_market
    dog_edge = (1 - fav_prob) - dog_market

    if fav_edge >= threshold and fav_edge >= dog_edge and _passes_worst_case(fav_prob, odds, fav_worst_key):
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "spread",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_market, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": sp_pred.get("confidence", "medium"),
            "projected": proj,
        }
    if dog_edge >= threshold and _passes_worst_case(1 - fav_prob, odds, dog_worst_key):
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "spread",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_market, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": sp_pred.get("confidence", "medium"),
            "projected": proj,
        }

    return None


def check_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total (over/under) value."""
    total_pred = sim.get("predictions", {}).get("total", {})
    total_odds = odds.get("total", {})
    if not total_pred or not total_odds:
        return None

    threshold = get_edge_threshold("total")
    if threshold is None:
        return None
    projected_total = total_pred.get("projected_total", "")

    line = total_odds.get("line", "?")
    over_odds = total_odds.get("over_odds", -110)
    under_odds = total_odds.get("under_odds", -110)

    # Derive probability from projected total vs line if available
    if projected_total and line != "?":
        try:
            delta = float(projected_total) - float(line)
            over_prob = min(max(0.5 + delta * 0.05, 0.01), 0.99)
        except (ValueError, TypeError):
            over_prob = total_pred.get("over_prob", 0)
    else:
        over_prob = total_pred.get("over_prob", 0)
    under_prob = 1 - over_prob

    over_market = _get_implied(odds, "total_over")
    under_market = _get_implied(odds, "total_under")

    over_edge = over_prob - over_market
    under_edge = under_prob - under_market

    if over_edge >= threshold and over_edge >= under_edge and _passes_worst_case(over_prob, odds, "total_over_worst"):
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_market, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
            "projected": projected_total,
        }
    if under_edge >= threshold and _passes_worst_case(under_prob, odds, "total_under_worst"):
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_market, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": total_pred.get("confidence", "medium"),
            "projected": projected_total,
        }

    return None


def check_h1_ml_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First Half moneyline value."""
    h1_pred = sim.get("predictions", {}).get("first_half", {})
    if not h1_pred:
        return None

    threshold = get_edge_threshold("first_half_ml")
    if threshold is None:
        return None

    h1_ml = odds.get("h1_moneyline", {})
    if not h1_ml:
        return None

    proj = _predicted_score_str(sim)

    home_odds = h1_ml.get("home", -110)
    away_odds = h1_ml.get("away", -110)

    h_prob = h1_pred.get("h1_home_win_prob", 0)
    a_prob = h1_pred.get("h1_away_win_prob", 0)
    h_market = _get_implied(odds, "h1_ml_home")
    a_market = _get_implied(odds, "h1_ml_away")
    h_edge = h_prob - h_market
    a_edge = a_prob - a_market

    if h_edge >= threshold and h_edge >= a_edge and _passes_worst_case(h_prob, odds, "h1_ml_home_worst"):
        dec = american_to_decimal(home_odds)
        return {
            "bet_type": "first_half_ml",
            "side": "home H1 ML",
            "odds": home_odds,
            "sim_prob": h_prob,
            "market_prob": round(h_market, 4),
            "edge": round(h_edge, 4),
            "kelly_pct": round(kelly_criterion(h_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
            "projected": proj,
        }
    if a_edge >= threshold and _passes_worst_case(a_prob, odds, "h1_ml_away_worst"):
        dec = american_to_decimal(away_odds)
        return {
            "bet_type": "first_half_ml",
            "side": "away H1 ML",
            "odds": away_odds,
            "sim_prob": a_prob,
            "market_prob": round(a_market, 4),
            "edge": round(a_edge, 4),
            "kelly_pct": round(kelly_criterion(a_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
            "projected": proj,
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

    threshold = get_edge_threshold("first_half_total")
    if threshold is None:
        return None

    over_odds = h1_total_odds.get("over_odds", -110)
    under_odds = h1_total_odds.get("under_odds", -110)

    # Heuristic: estimate probability from projected vs line delta
    # Each point delta roughly corresponds to ~5% probability shift from 50%
    delta = projected - line
    over_prob = min(max(0.5 + delta * 0.05, 0.01), 0.99)
    under_prob = 1 - over_prob

    over_market = _get_implied(odds, "h1_total_over")
    under_market = _get_implied(odds, "h1_total_under")

    over_edge = over_prob - over_market
    under_edge = under_prob - under_market

    if over_edge >= threshold and over_edge >= under_edge and _passes_worst_case(over_prob, odds, "h1_total_over_worst"):
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "first_half_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_market, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
            "projected": projected,
        }
    if under_edge >= threshold and _passes_worst_case(under_prob, odds, "h1_total_under_worst"):
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "first_half_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_market, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
            "projected": projected,
        }

    return None


def check_first_half_spread_edge(sim: dict, odds: dict) -> dict | None:
    """Check for First Half spread value."""
    h1_pred = sim.get("predictions", {}).get("first_half", {})
    h1_spread = odds.get("h1_spread", {})
    if not h1_pred or not h1_spread:
        return None

    threshold = get_edge_threshold("first_half_spread")
    if threshold is None:
        return None
    fav_prob = h1_pred.get("h1_favorite_cover_prob", 0)
    proj = _predicted_score_str(sim)

    home_point = h1_spread.get("home", 0)
    home_odds = h1_spread.get("home_odds", -110)
    away_odds = h1_spread.get("away_odds", -110)

    home_is_fav = home_point < 0

    if home_is_fav:
        fav_odds = home_odds
        dog_odds = away_odds
        fav_label = f"home H1 {home_point}"
        dog_label = f"away H1 {h1_spread.get('away', 0)}"
    else:
        fav_odds = away_odds
        dog_odds = home_odds
        fav_label = f"away H1 {h1_spread.get('away', 0)}"
        dog_label = f"home H1 {home_point}"

    if home_is_fav:
        fav_market = _get_implied(odds, "h1_spread_home")
        dog_market = _get_implied(odds, "h1_spread_away")
        fav_worst_key = "h1_spread_home_worst"
        dog_worst_key = "h1_spread_away_worst"
    else:
        fav_market = _get_implied(odds, "h1_spread_away")
        dog_market = _get_implied(odds, "h1_spread_home")
        fav_worst_key = "h1_spread_away_worst"
        dog_worst_key = "h1_spread_home_worst"

    fav_edge = fav_prob - fav_market
    dog_edge = (1 - fav_prob) - dog_market

    if fav_edge >= threshold and fav_edge >= dog_edge and _passes_worst_case(fav_prob, odds, fav_worst_key):
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "first_half_spread",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_market, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
            "projected": proj,
        }
    if dog_edge >= threshold and _passes_worst_case(1 - fav_prob, odds, dog_worst_key):
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "first_half_spread",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_market, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": h1_pred.get("confidence", "medium"),
            "projected": proj,
        }

    return None


def check_q1_ml_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Q1 moneyline value."""
    q1_pred = sim.get("predictions", {}).get("q1", {})
    q1_ml = odds.get("q1_moneyline", {})
    if not q1_pred or not q1_ml:
        return None

    threshold = get_edge_threshold("q1_ml")
    if threshold is None:
        return None
    proj = _predicted_score_str(sim)

    home_odds = q1_ml.get("home", -110)
    away_odds = q1_ml.get("away", -110)

    h_prob = q1_pred.get("q1_home_win_prob", 0)
    a_prob = q1_pred.get("q1_away_win_prob", 0)
    h_market = _get_implied(odds, "q1_ml_home")
    a_market = _get_implied(odds, "q1_ml_away")
    h_edge = h_prob - h_market
    a_edge = a_prob - a_market

    if h_edge >= threshold and h_edge >= a_edge and _passes_worst_case(h_prob, odds, "q1_ml_home_worst"):
        dec = american_to_decimal(home_odds)
        return {
            "bet_type": "q1_ml",
            "side": "home Q1 ML",
            "odds": home_odds,
            "sim_prob": h_prob,
            "market_prob": round(h_market, 4),
            "edge": round(h_edge, 4),
            "kelly_pct": round(kelly_criterion(h_prob, dec) * KELLY_FRACTION, 4),
            "confidence": q1_pred.get("confidence", "medium"),
            "projected": proj,
        }
    if a_edge >= threshold and _passes_worst_case(a_prob, odds, "q1_ml_away_worst"):
        dec = american_to_decimal(away_odds)
        return {
            "bet_type": "q1_ml",
            "side": "away Q1 ML",
            "odds": away_odds,
            "sim_prob": a_prob,
            "market_prob": round(a_market, 4),
            "edge": round(a_edge, 4),
            "kelly_pct": round(kelly_criterion(a_prob, dec) * KELLY_FRACTION, 4),
            "confidence": q1_pred.get("confidence", "medium"),
            "projected": proj,
        }

    return None


def check_q1_spread_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Q1 spread value."""
    q1_pred = sim.get("predictions", {}).get("q1", {})
    q1_spread = odds.get("q1_spread", {})
    if not q1_pred or not q1_spread:
        return None

    threshold = get_edge_threshold("q1_spread")
    if threshold is None:
        return None
    fav_prob = q1_pred.get("q1_favorite_cover_prob", 0)
    proj = _predicted_score_str(sim)

    home_point = q1_spread.get("home", 0)
    home_odds = q1_spread.get("home_odds", -110)
    away_odds = q1_spread.get("away_odds", -110)

    home_is_fav = home_point < 0

    if home_is_fav:
        fav_odds = home_odds
        dog_odds = away_odds
        fav_label = f"home Q1 {home_point}"
        dog_label = f"away Q1 {q1_spread.get('away', 0)}"
    else:
        fav_odds = away_odds
        dog_odds = home_odds
        fav_label = f"away Q1 {q1_spread.get('away', 0)}"
        dog_label = f"home Q1 {home_point}"

    if home_is_fav:
        fav_market = _get_implied(odds, "q1_spread_home")
        dog_market = _get_implied(odds, "q1_spread_away")
        fav_worst_key = "q1_spread_home_worst"
        dog_worst_key = "q1_spread_away_worst"
    else:
        fav_market = _get_implied(odds, "q1_spread_away")
        dog_market = _get_implied(odds, "q1_spread_home")
        fav_worst_key = "q1_spread_away_worst"
        dog_worst_key = "q1_spread_home_worst"

    fav_edge = fav_prob - fav_market
    dog_edge = (1 - fav_prob) - dog_market

    if fav_edge >= threshold and fav_edge >= dog_edge and _passes_worst_case(fav_prob, odds, fav_worst_key):
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "q1_spread",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_market, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": q1_pred.get("confidence", "medium"),
            "projected": proj,
        }
    if dog_edge >= threshold and _passes_worst_case(1 - fav_prob, odds, dog_worst_key):
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "q1_spread",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_market, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * KELLY_FRACTION, 4),
            "confidence": q1_pred.get("confidence", "medium"),
            "projected": proj,
        }

    return None


def check_q1_total_edge(sim: dict, odds: dict) -> dict | None:
    """Check for Q1 over/under value using projected total vs line heuristic."""
    q1_pred = sim.get("predictions", {}).get("q1", {})
    if not q1_pred:
        return None

    q1_total_odds = odds.get("q1_total", {})
    if not q1_total_odds:
        return None

    projected = q1_pred.get("q1_projected_total")
    if projected is None:
        return None

    line = q1_total_odds.get("line")
    if line is None:
        return None

    threshold = get_edge_threshold("q1_total")
    if threshold is None:
        return None

    over_odds = q1_total_odds.get("over_odds", -110)
    under_odds = q1_total_odds.get("under_odds", -110)

    delta = projected - line
    over_prob = min(max(0.5 + delta * 0.05, 0.01), 0.99)
    under_prob = 1 - over_prob

    over_market = _get_implied(odds, "q1_total_over")
    under_market = _get_implied(odds, "q1_total_under")

    over_edge = over_prob - over_market
    under_edge = under_prob - under_market

    if over_edge >= threshold and over_edge >= under_edge and _passes_worst_case(over_prob, odds, "q1_total_over_worst"):
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "q1_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_market, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": q1_pred.get("confidence", "medium"),
            "projected": projected,
        }
    if under_edge >= threshold and _passes_worst_case(under_prob, odds, "q1_total_under_worst"):
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "q1_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_market, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": q1_pred.get("confidence", "medium"),
            "projected": projected,
        }

    return None


def check_quarter_total_edge(derived: dict, odds: dict, quarter: str) -> dict | None:
    """Check for Q2-Q4 over/under value using derived projected total vs line heuristic."""
    key = f"{quarter}_projected_total"
    projected = derived.get(key)
    if projected is None:
        return None

    q_total_odds = odds.get(f"{quarter}_total", {})
    if not q_total_odds:
        return None

    line = q_total_odds.get("line")
    if line is None:
        return None

    threshold = get_edge_threshold(f"{quarter}_total")
    if threshold is None:
        return None

    over_odds = q_total_odds.get("over_odds", -110)
    under_odds = q_total_odds.get("under_odds", -110)

    delta = projected - line
    over_prob = min(max(0.5 + delta * 0.05, 0.01), 0.99)
    under_prob = 1 - over_prob

    over_market = _get_implied(odds, f"{quarter}_total_over")
    under_market = _get_implied(odds, f"{quarter}_total_under")

    over_edge = over_prob - over_market
    under_edge = under_prob - under_market

    if over_edge >= threshold and over_edge >= under_edge and _passes_worst_case(over_prob, odds, f"{quarter}_total_over_worst"):
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": f"{quarter}_total",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_market, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": "medium",
            "projected": projected,
        }
    if under_edge >= threshold and _passes_worst_case(under_prob, odds, f"{quarter}_total_under_worst"):
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": f"{quarter}_total",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_market, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": "medium",
            "projected": projected,
        }

    return None


def check_team_total_edge(sim: dict, odds: dict, side: str) -> dict | None:
    """Check for team total over/under value. side is 'home' or 'away'."""
    tt_pred = sim.get("predictions", {}).get("team_totals", {})
    tt_odds = odds.get("team_totals", {}).get(side, {})
    if not tt_pred or not tt_odds:
        return None

    projected_key = f"{side}_projected"
    projected = tt_pred.get(projected_key)
    if projected is None:
        return None

    line = tt_odds.get("line")
    if line is None:
        return None

    threshold = get_edge_threshold(f"team_total_{side}")
    if threshold is None:
        return None

    over_odds = tt_odds.get("over_odds", -110)
    under_odds = tt_odds.get("under_odds", -110)

    delta = projected - line
    over_prob = min(max(0.5 + delta * 0.05, 0.01), 0.99)
    under_prob = 1 - over_prob

    over_market = _get_implied(odds, f"tt_{side}_over")
    under_market = _get_implied(odds, f"tt_{side}_under")

    over_edge = over_prob - over_market
    under_edge = under_prob - under_market

    if over_edge >= threshold and over_edge >= under_edge and _passes_worst_case(over_prob, odds, f"tt_{side}_over_worst"):
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": f"team_total_{side}",
            "side": f"{side} over {line}",
            "odds": over_odds,
            "sim_prob": round(over_prob, 4),
            "market_prob": round(over_market, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": "medium",
            "projected": projected,
        }
    if under_edge >= threshold and _passes_worst_case(under_prob, odds, f"tt_{side}_under_worst"):
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": f"team_total_{side}",
            "side": f"{side} under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_market, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": "medium",
            "projected": projected,
        }

    return None


# Mapping from prop_type to bet_type label
_PROP_BET_TYPE = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",
    "pra": "player_pra",
}


def check_player_prop_edge(prop_preds: dict, odds: dict, prop_type: str) -> list[dict]:
    """Check player prop edges for a given prop type. Returns list of bets."""
    bet_type_label = _PROP_BET_TYPE.get(prop_type, f"player_{prop_type}")
    threshold = get_edge_threshold(bet_type_label)
    if threshold is None:
        return []

    players_preds = prop_preds.get("player_props", {})
    players_odds = odds.get("player_props", {})

    results = []
    for player_name, player_preds in players_preds.items():
        prop_pred = player_preds.get(prop_type)
        if not prop_pred:
            continue

        player_odds = players_odds.get(player_name, {}).get(prop_type, {})
        if not player_odds:
            continue

        over_prob = prop_pred.get("over_prob", 0)
        projected_val = prop_pred.get("projected", "")

        over_odds_val = player_odds.get("over_odds", -110)
        under_odds_val = player_odds.get("under_odds", -110)
        line = player_odds.get("line")

        # Derive probability from projected value vs line if available
        if projected_val and line is not None:
            try:
                proj_float = float(projected_val)
                delta = proj_float - float(line)
                # Heuristic: probability shift per stat point differs by stat type
                multipliers = {
                    "points": 0.06, "rebounds": 0.12, "assists": 0.12,
                    "threes": 0.18, "pra": 0.04,
                }
                mult = multipliers.get(prop_type, 0.08)
                over_prob = min(max(0.5 + delta * mult, 0.01), 0.99)
            except (ValueError, TypeError):
                pass  # Fall back to model's over_prob
        under_prob = 1 - over_prob

        # Multi-book consensus implied prob for this player prop
        implied = odds.get("implied_probs", {})
        prop_key = f"prop_{prop_type}_{player_name}"
        over_market = implied.get(f"{prop_key}_over", 0.5)
        under_market = implied.get(f"{prop_key}_under", 0.5)

        over_edge = over_prob - over_market
        under_edge = under_prob - under_market

        if over_edge >= threshold and over_edge >= under_edge and _passes_worst_case(over_prob, odds, f"{prop_key}_over_worst"):
            dec = american_to_decimal(over_odds_val)
            results.append({
                "bet_type": bet_type_label,
                "player": player_name,
                "side": f"over {line}",
                "odds": over_odds_val,
                "sim_prob": over_prob,
                "market_prob": round(over_market, 4),
                "edge": round(over_edge, 4),
                "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
                "confidence": prop_pred.get("confidence", "medium"),
                "projected": projected_val,
            })
        elif under_edge >= threshold and _passes_worst_case(under_prob, odds, f"{prop_key}_under_worst"):
            dec = american_to_decimal(under_odds_val)
            results.append({
                "bet_type": bet_type_label,
                "player": player_name,
                "side": f"under {line}",
                "odds": under_odds_val,
                "sim_prob": under_prob,
                "market_prob": round(under_market, 4),
                "edge": round(under_edge, 4),
                "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
                "confidence": prop_pred.get("confidence", "medium"),
                "projected": projected_val,
            })

    return results


def analyze_prop_edges(prop_preds: dict, odds: dict) -> list[dict]:
    """Run player prop edge checks for all prop types. Returns combined list of bets."""
    prop_types = ["points", "rebounds", "assists", "threes", "pra"]
    bets = []
    for prop_type in prop_types:
        results = check_player_prop_edge(prop_preds, odds, prop_type)
        bets.extend(results)
    return bets


def optimize_with_alt_lines(bet: dict, alt_lines: list[dict]) -> dict:
    """Given a bet and list of alternate lines, return the one with highest Kelly fraction."""
    best = bet
    best_kelly = bet.get("kelly_pct", 0)

    for alt in alt_lines:
        alt_odds_val = alt.get("odds")
        alt_prob = alt.get("sim_prob", bet.get("sim_prob", 0))
        if alt_odds_val is None:
            continue
        dec = american_to_decimal(alt_odds_val)
        k = kelly_criterion(alt_prob, dec) * KELLY_FRACTION
        if k > best_kelly:
            best_kelly = k
            best = {**bet, **alt, "kelly_pct": round(k, 4)}

    return best


def analyze_all_edges(sim: dict, odds: dict, derived: dict = None) -> list[dict]:
    """Run all game-level edge checks. Returns 0-14 bet signals."""
    derived = derived or {}
    checkers = [
        check_moneyline_edge, check_spread_edge, check_total_edge,
        check_h1_ml_edge, check_h1_total_edge, check_first_half_spread_edge,
        check_q1_ml_edge, check_q1_spread_edge, check_q1_total_edge,
    ]
    bets = []
    for checker in checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)

    # Q2-Q4 (derived projections)
    for q in ["q2", "q3", "q4"]:
        result = check_quarter_total_edge(derived, odds, q)
        if result:
            bets.append(result)

    # Team totals
    for side in ["home", "away"]:
        result = check_team_total_edge(sim, odds, side)
        if result:
            bets.append(result)

    return bets
