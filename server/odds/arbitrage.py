"""Arbitrage scanner.

Identifies markets where the sum of implied probabilities across the best-
priced legs is < 1.0, meaning a risk-free positive-ROI split bet exists.
Prices consumed here are already commission-adjusted by `rows_to_games`; the
scanner treats them as net effective payouts.

Coverage:
  - h2h (2-way for US sports, 3-way for soccer with a "Draw" outcome)
  - spreads + alternate_spreads   (paired by complementary signed points)
  - totals + alternate_totals     (paired by point)

3-way arbs require at least 2 distinct books across the 3 legs — three legs
at one book is just the book's vig and never positive.
Player props are skipped (no two-sided pairing across books for individual
player Over/Under at the same point — handled by the EV scanner instead).
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


def _clamp_total_stake(
    sizes: list[float | None], stake_pcts: list[float],
) -> float | None:
    """Largest total stake that respects every leg's fillable depth.

    For each leg, the max total = size / (stake_pct / 100). The
    overall clamp is the min across legs. If any leg's size is None
    (unknown — typical for sportsbook rows), we can't clamp: return
    None so the UI doesn't display a misleading cap.
    """
    if any(s is None for s in sizes):
        return None
    caps: list[float] = []
    for size, pct in zip(sizes, stake_pcts):
        if pct <= 0:
            return None
        caps.append(float(size) / (pct / 100.0))
    if not caps:
        return None
    return round(min(caps), 2)


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
    stake_a_pct = imp_a / total * 100.0
    stake_b_pct = imp_b / total * 100.0
    a_size = best_a.get("max_stake_dollars")
    b_size = best_b.get("max_stake_dollars")
    max_total = _clamp_total_stake([a_size, b_size], [stake_a_pct, stake_b_pct])
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,       # "h2h" | "spreads" | "totals"
        "point": point,
        "roi_pct": roi * 100.0,
        "max_total_stake_dollars": max_total,
        "sides": [
            {
                "outcome_name": side_a["outcome_name"],
                "book": best_a["bookmaker_key"],
                "price_american": best_a["price_american"],
                "point": best_a.get("point"),
                "stake_pct": stake_a_pct,
                "max_stake_dollars": a_size,
            },
            {
                "outcome_name": side_b["outcome_name"],
                "book": best_b["bookmaker_key"],
                "price_american": best_b["price_american"],
                "point": best_b.get("point"),
                "stake_pct": stake_b_pct,
                "max_stake_dollars": b_size,
            },
        ],
    }


def _try_three_way(
    sides: list[dict],
    books_filter: set[str] | None,
) -> tuple[list[dict], float] | None:
    """Same as `_try_pair` but for 3-outcome markets (soccer h2h: home/draw/
    away). Returns (best_prices_in_input_order, roi_frac) if an arb exists.

    The "different book per leg" rule we apply to 2-way markets is relaxed —
    for 3-way, requiring 3 distinct books would miss real arbs that need
    only 2 books (one book offers the longest two sides at +odds, another
    the third). We require **at least 2 distinct books across the 3 legs**.
    """
    bests: list[dict] = []
    for s in sides:
        b = _best_visible(s, books_filter)
        if not b:
            return None
        bests.append(b)
    distinct_books = {b["bookmaker_key"] for b in bests}
    if len(distinct_books) < 2:
        return None  # all three legs at one book → just the book's vig
    total = sum(american_to_implied_prob(b["price_american"]) for b in bests)
    if total >= 1.0:
        return None
    roi = 1.0 / total - 1.0
    return bests, roi


def _emit_three_way(
    game: dict,
    market_kind: str,
    sides: list[dict],
    bests: list[dict],
    roi: float,
) -> dict:
    imps = [american_to_implied_prob(b["price_american"]) for b in bests]
    total = sum(imps)
    stake_pcts = [imp / total * 100.0 for imp in imps]
    sizes = [b.get("max_stake_dollars") for b in bests]
    max_total = _clamp_total_stake(sizes, stake_pcts)
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,
        "point": None,
        "roi_pct": roi * 100.0,
        "max_total_stake_dollars": max_total,
        "sides": [
            {
                "outcome_name": s["outcome_name"],
                "book": b["bookmaker_key"],
                "price_american": b["price_american"],
                "point": b.get("point"),
                "stake_pct": imp / total * 100.0,
                "max_stake_dollars": b.get("max_stake_dollars"),
            }
            for s, b, imp in zip(sides, bests, imps)
        ],
    }


def scan_game_arbs(
    game: dict, books_filter: set[str] | None = None
) -> list[dict]:
    out: list[dict] = []

    # --- H2H ---------------------------------------------------------------
    h2h = _find_market(game, "h2h")
    h2h_outcomes = h2h.get("outcomes", []) if h2h else []
    if len(h2h_outcomes) == 2:
        a, b = h2h_outcomes
        pair = _try_pair(a, b, books_filter)
        if pair:
            best_a, best_b, roi = pair
            out.append(_emit(game, "h2h", None, a, b, best_a, best_b, roi))
    elif len(h2h_outcomes) == 3:
        # Soccer-style 3-way (home/draw/away) — order doesn't matter for
        # the math, but keep input order so the emitted `sides` row stays
        # consistent across cycles.
        result = _try_three_way(h2h_outcomes, books_filter)
        if result is not None:
            bests, roi = result
            out.append(_emit_three_way(game, "h2h", h2h_outcomes, bests, roi))

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
