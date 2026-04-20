"""Arbitrage scanner.

Identifies two-way markets where the sum of implied probabilities across the
best-priced sides is < 1.0, meaning a risk-free positive-ROI split bet exists.
Prices consumed here are already commission-adjusted by `rows_to_games`; the
scanner treats them as net effective payouts.

Scope v1: two-way markets only.
  - h2h
  - spreads + alternate_spreads   (paired by |point|)
  - totals + alternate_totals     (paired by point)

Three-way markets (soccer draws) and player props are skipped.
"""
from __future__ import annotations

from .devig import american_to_implied_prob
from .pairing import collect_spread_pairs, collect_total_pairs


def _payout_multiplier(american: int) -> float:
    return 1 + american / 100.0 if american > 0 else 1 + 100.0 / -american


def _find_market(game: dict, key: str) -> dict | None:
    for m in game.get("markets", []):
        if m.get("market_key") == key:
            return m
    return None


def _outcome_point(out: dict) -> float | None:
    """A MarketOutcome's single point value — every price under an outcome
    shares the same point (that's how normalize.py groups them)."""
    if out.get("best_price") and out["best_price"].get("point") is not None:
        return out["best_price"]["point"]
    prices = out.get("prices") or []
    if prices and prices[0].get("point") is not None:
        return prices[0]["point"]
    return None


def _best_visible(
    outcome: dict, books_filter: set[str] | None
) -> dict | None:
    """Pick the best American-odds price from this outcome, optionally
    restricted to a book-allowlist."""
    prices = outcome.get("prices") or []
    if books_filter is not None:
        prices = [p for p in prices if p["bookmaker_key"] in books_filter]
    if not prices:
        return None
    return max(prices, key=lambda p: _payout_multiplier(p["price_american"]))


def _try_pair(
    side_a: dict,
    side_b: dict,
    books_filter: set[str] | None,
) -> tuple[dict, dict, float] | None:
    """Return (best_price_a, best_price_b, roi_frac) if an arb exists."""
    best_a = _best_visible(side_a, books_filter)
    best_b = _best_visible(side_b, books_filter)
    if not best_a or not best_b:
        return None
    if best_a["bookmaker_key"] == best_b["bookmaker_key"]:
        # Same book: not a real arb — the book's vig makes total ≥ 1 by design.
        # (Can still happen when commission adjustments flip it; rare but skip.)
        return None
    imp_a = american_to_implied_prob(best_a["price_american"])
    imp_b = american_to_implied_prob(best_b["price_american"])
    total = imp_a + imp_b
    if total >= 1.0:
        return None
    roi = 1.0 / total - 1.0
    return best_a, best_b, roi


def _emit(
    game: dict,
    market_kind: str,
    point: float | None,
    side_a: dict,
    side_b: dict,
    best_a: dict,
    best_b: dict,
    roi: float,
) -> dict:
    imp_a = american_to_implied_prob(best_a["price_american"])
    imp_b = american_to_implied_prob(best_b["price_american"])
    total = imp_a + imp_b
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,       # "h2h" | "spreads" | "totals"
        "point": point,
        "roi_pct": roi * 100.0,
        "sides": [
            {
                "outcome_name": side_a["outcome_name"],
                "book": best_a["bookmaker_key"],
                "price_american": best_a["price_american"],
                "point": best_a.get("point"),
                "stake_pct": imp_a / total * 100.0,
            },
            {
                "outcome_name": side_b["outcome_name"],
                "book": best_b["bookmaker_key"],
                "price_american": best_b["price_american"],
                "point": best_b.get("point"),
                "stake_pct": imp_b / total * 100.0,
            },
        ],
    }


def scan_game_arbs(
    game: dict, books_filter: set[str] | None = None
) -> list[dict]:
    out: list[dict] = []

    # --- H2H ---------------------------------------------------------------
    h2h = _find_market(game, "h2h")
    if h2h and len(h2h.get("outcomes", [])) == 2:
        a, b = h2h["outcomes"]
        pair = _try_pair(a, b, books_filter)
        if pair:
            best_a, best_b, roi = pair
            out.append(_emit(game, "h2h", None, a, b, best_a, best_b, roi))

    # --- Spreads (main + alt) — pair by complementary signed points -------
    for abs_pt, home_side, away_side in collect_spread_pairs(game):
        pair = _try_pair(home_side, away_side, books_filter)
        if pair:
            best_a, best_b, roi = pair
            out.append(
                _emit(game, "spreads", abs_pt, home_side, away_side,
                      best_a, best_b, roi)
            )

    # --- Totals (main + alt) — pair Over and Under at same point ----------
    for pt, over_side, under_side in collect_total_pairs(game):
        pair = _try_pair(over_side, under_side, books_filter)
        if pair:
            best_a, best_b, roi = pair
            out.append(
                _emit(game, "totals", pt, over_side, under_side,
                      best_a, best_b, roi)
            )

    return out


def scan_all_arbs(
    games: list[dict], books_filter: set[str] | None = None
) -> list[dict]:
    """Entry point used by the API layer. Returns opportunities sorted by ROI
    descending. Expects `games` to already be commission-adjusted via
    `rows_to_games`."""
    ops: list[dict] = []
    for g in games:
        ops.extend(scan_game_arbs(g, books_filter))
    ops.sort(key=lambda o: -o["roi_pct"])
    return ops
