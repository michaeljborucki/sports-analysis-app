"""Compare Monte Carlo distributions to sportsbook prop lines."""
import logging
import requests
from config import ODDS_API_KEY, ODDS_API_BASE, EDGE_THRESHOLDS, KELLY_FRACTION
from calibrate import apply_calibration
from edge import american_to_implied_prob, american_to_decimal, kelly_criterion, _sized_kelly, _passes_worst_case_filter, apply_bet_filters
from scrapers.odds import power_devig, _american_to_decimal

logger = logging.getLogger("mirofish.props")

# Cap prop probabilities to reflect unmodeled tail risk the MC sim
# does not capture: injuries mid-start, ejections, early strategic
# hooks, rain delays, suspended games. Together these bound the
# realistic confidence for any prop bet at ~97-98%.
PROP_PROB_FLOOR = 0.02
PROP_PROB_CEIL = 0.98

# Market-shrinkage guardrail (2026-06-03). With the batter-prop isotonic
# calibrators dropped, prop probabilities now run uncalibrated, and the raw
# model is systematically overconfident (e.g. raw under-1.5 H+R+RBI ~0.81 vs
# ~0.50 realized). Blending the model probability toward the no-vig market
# prior anchors it — shrinking phantom edges and Kelly stakes alike. The
# weight is the share placed on the market; raise it if forward calibration
# shows persistent overconfidence, lower it as the model earns trust.
MARKET_BLEND_WEIGHT = 0.35


def _shrink_to_market(model_prob: float, market_prob: float,
                      weight: float = MARKET_BLEND_WEIGHT) -> float:
    """Blend a model probability toward the no-vig market prior."""
    return (1.0 - weight) * model_prob + weight * market_prob

PROP_MARKETS = (
    "pitcher_strikeouts,pitcher_earned_runs,pitcher_outs,pitcher_hits_allowed,"
    "batter_total_bases,batter_rbis,batter_hits,batter_runs_scored,"
    "batter_hits_runs_rbis,batter_strikeouts"
)

# Map API market key → (MC stat key, is_pitcher)
PROP_MAPPING = {
    "pitcher_strikeouts": ("k", True),
    "pitcher_earned_runs": ("er", True),
    "pitcher_outs": ("outs", True),
    "pitcher_hits_allowed": ("h", True),
    "batter_total_bases": ("tb", False),
    "batter_rbis": ("rbi", False),
    "batter_hits": ("h", False),
    "batter_runs_scored": ("r", False),
    "batter_hits_runs_rbis": ("h_r_rbi", False),
    "batter_strikeouts": ("k", False),
}


def distribution_to_over_prob(distribution: list[float], line: float) -> float:
    """Calculate P(over line) from a discrete distribution.

    distribution[i] = P(stat == i)
    P(over 5.5) = sum(distribution[6:])

    Probabilities are clamped to [PROP_PROB_FLOOR, PROP_PROB_CEIL]
    whenever the line sits inside the modeled range — empirical MC
    can put 100% of samples on one side of a soft line (e.g.
    pitcher_outs over 14.5 when every sim finishes the 5th inning),
    but real props carry ~2-3% unmodeled tail risk (injury, ejection,
    early hook, weather). If the line sits outside the modeled range
    entirely we return 0.0 — that's a "no signal" flag, not a 0% claim.
    """
    if not distribution:
        return 0.0
    threshold_idx = int(line) + 1  # e.g., line=5.5 → need 6+, so index 6
    if threshold_idx >= len(distribution):
        return 0.0
    raw = sum(distribution[threshold_idx:])
    return max(PROP_PROB_FLOOR, min(PROP_PROB_CEIL, raw))


def check_prop_edge(
    distribution: list[float],
    line: float,
    over_odds: int,
    under_odds: int,
    threshold: float,
    bet_type: str,
    player_name: str,
) -> dict | None:
    """Check for edge on a single prop using power devig + worst-case filter."""
    over_prob = distribution_to_over_prob(distribution, line)
    under_prob = 1 - over_prob

    over_prob = apply_calibration(over_prob, bet_type, "over")
    under_prob = apply_calibration(under_prob, bet_type, "under")

    raw_over = american_to_implied_prob(over_odds)
    raw_under = american_to_implied_prob(under_odds)
    over_implied, under_implied = power_devig(raw_over, raw_under)

    # Market-shrinkage guardrail: anchor the (uncalibrated) model toward the
    # no-vig market prior before computing edge and Kelly sizing.
    over_prob = _shrink_to_market(over_prob, over_implied)
    under_prob = _shrink_to_market(under_prob, under_implied)

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        passes, wc_edge = _passes_worst_case_filter(over_prob, raw_over, raw_under)
        if not passes:
            return None
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": bet_type,
            "side": f"{player_name} over {line}",
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
            "side": f"{player_name} under {line}",
            "odds": under_odds,
            "sim_prob": round(under_prob, 4),
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "worst_case_edge": wc_edge,
            "kelly_pct": _sized_kelly(under_prob, dec),
            "confidence": "medium",
        }
    return None


def get_prop_odds(event_id: str) -> dict:
    """Fetch player prop odds for a game from The Odds API.

    Returns: {market_key: {player_name: {"line": X, "over_odds": X, "under_odds": X}}}
    """
    url = f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,us2,eu,uk",
        "markets": PROP_MARKETS,
        "oddsFormat": "american",
    }

    result = {}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return result

        data = resp.json()
        for bk in data.get("bookmakers", []):
            for market in bk.get("markets", []):
                market_key = market["key"]
                if market_key not in result:
                    result[market_key] = {}

                # Group outcomes by (player, line) to avoid mixing alternate lines
                player_line_outcomes = {}
                for outcome in market.get("outcomes", []):
                    desc = outcome.get("description", "")
                    line = outcome.get("point", 0)
                    key = (desc, line)
                    if key not in player_line_outcomes:
                        player_line_outcomes[key] = {"line": line}
                    if outcome["name"] == "Over":
                        player_line_outcomes[key]["over_odds"] = outcome["price"]
                    elif outcome["name"] == "Under":
                        player_line_outcomes[key]["under_odds"] = outcome["price"]

                # Best-line selection: keep best odds per player, same line only
                for (player_name, line), odds in player_line_outcomes.items():
                    if "over_odds" not in odds or "under_odds" not in odds:
                        continue
                    existing = result[market_key].get(player_name)
                    if existing is None:
                        result[market_key][player_name] = odds
                    elif existing["line"] == line:
                        # Same line: keep best odds per side
                        if _american_to_decimal(odds["over_odds"]) > _american_to_decimal(existing.get("over_odds", -110)):
                            existing["over_odds"] = odds["over_odds"]
                        if _american_to_decimal(odds["under_odds"]) > _american_to_decimal(existing.get("under_odds", -110)):
                            existing["under_odds"] = odds["under_odds"]
                    else:
                        # Different line: keep the one with more liquid market (lower vig)
                        old_vig = american_to_implied_prob(existing["over_odds"]) + american_to_implied_prob(existing["under_odds"])
                        new_vig = american_to_implied_prob(odds["over_odds"]) + american_to_implied_prob(odds["under_odds"])
                        if new_vig < old_vig:
                            result[market_key][player_name] = odds

    except Exception as e:
        logger.error("Props odds fetch failed for %s: %s", event_id, e)

    return result


def analyze_all_props(mc_results: dict, prop_odds: dict) -> list[dict]:
    """Check all prop edges for a game.

    Maps players between MC results (by ID) and odds (by name).
    """
    from scrapers.player_stats import resolve_player

    bets = []
    pitcher_dists = mc_results.get("pitcher_distributions", {})
    batter_dists = mc_results.get("batter_distributions", {})

    for market_key, players in prop_odds.items():
        mapping = PROP_MAPPING.get(market_key)
        if not mapping:
            continue
        stat_key, is_pitcher = mapping
        threshold = EDGE_THRESHOLDS.get(market_key, 0.05)

        for player_name, odds_data in players.items():
            line = odds_data.get("line")
            over_odds = odds_data.get("over_odds")
            under_odds = odds_data.get("under_odds")
            if line is None or over_odds is None or under_odds is None:
                continue

            # Find player's distribution
            player_id = resolve_player(player_name)
            if player_id is None:
                continue

            dists = pitcher_dists if is_pitcher else batter_dists
            player_dist = dists.get(player_id, {})
            distribution = player_dist.get(stat_key, [])
            if not distribution:
                continue

            result = check_prop_edge(
                distribution=distribution,
                line=line,
                over_odds=over_odds,
                under_odds=under_odds,
                threshold=threshold,
                bet_type=market_key,
                player_name=player_name,
            )
            if result:
                bets.append(result)
                logger.info("Prop edge: %s %s | edge=%.3f", market_key, result["side"], result["edge"])

    return apply_bet_filters(bets)
