"""Low-hold scanner.

A "low-hold" line is a two-way market where the best available prices across
books sum to a small overround — the book's cut is near zero, meaning the
market is tightly priced. Strictly positive hold (hold < 0 is an arb, which
lives on /arbitrage).

Hold % = (sum_implied - 1) / sum_implied × 100
  -110 / -110 → sum 1.0476, hold 4.55%  (typical retail)
  -105 / -105 → sum 1.0244, hold 2.38%  (sharp market)

Prices passed in are already commission-adjusted by `rows_to_games`.
"""
from __future__ import annotations

from .arbitrage import _best_visible, _find_market
from .devig import american_to_implied_prob
from .pairing import collect_spread_pairs, collect_total_pairs


def _hold_pct(imp_a: float, imp_b: float) -> float:
    total = imp_a + imp_b
    if total <= 0:
        return 0.0
    return (total - 1.0) / total * 100.0


def _try_low_hold_pair(
    side_a: dict,
    side_b: dict,
    books_filter: set[str] | None,
    max_hold_pct: float,
) -> tuple[dict, dict, float] | None:
    best_a = _best_visible(side_a, books_filter)
    best_b = _best_visible(side_b, books_filter)
    if not best_a or not best_b:
        return None
    if best_a["bookmaker_key"] == best_b["bookmaker_key"]:
        return None
    imp_a = american_to_implied_prob(best_a["price_american"])
    imp_b = american_to_implied_prob(best_b["price_american"])
    total = imp_a + imp_b
    if total < 1.0:
        return None  # strict arbitrage territory — belongs on /arbitrage
    # total == 1.0 → 0% hold (perfectly fair line). Inclusive here so the
    # low-hold page surfaces it as the cleanest possible no-vig pair.
    hold = _hold_pct(imp_a, imp_b)
    if hold > max_hold_pct:
        return None
    return best_a, best_b, hold


def _emit(
    game: dict,
    market_kind: str,
    point: float | None,
    side_a: dict,
    side_b: dict,
    best_a: dict,
    best_b: dict,
    hold: float,
) -> dict:
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,
        "point": point,
        "hold_pct": hold,
        "sides": [
            {
                "outcome_name": side_a["outcome_name"],
                "book": best_a["bookmaker_key"],
                "price_american": best_a["price_american"],
                "point": best_a.get("point"),
            },
            {
                "outcome_name": side_b["outcome_name"],
                "book": best_b["bookmaker_key"],
                "price_american": best_b["price_american"],
                "point": best_b.get("point"),
            },
        ],
    }


def scan_game_low_hold(
    game: dict,
    books_filter: set[str] | None,
    max_hold_pct: float,
) -> list[dict]:
    out: list[dict] = []

    # H2H
    h2h = _find_market(game, "h2h")
    if h2h and len(h2h.get("outcomes", [])) == 2:
        a, b = h2h["outcomes"]
        pair = _try_low_hold_pair(a, b, books_filter, max_hold_pct)
        if pair:
            best_a, best_b, hold = pair
            out.append(_emit(game, "h2h", None, a, b, best_a, best_b, hold))

    # Spreads — pair by complementary signed points (main + alt merged)
    for abs_pt, home_side, away_side in collect_spread_pairs(game):
        pair = _try_low_hold_pair(
            home_side, away_side, books_filter, max_hold_pct
        )
        if pair:
            best_a, best_b, hold = pair
            out.append(
                _emit(game, "spreads", abs_pt, home_side, away_side,
                      best_a, best_b, hold)
            )

    # Totals — pair Over and Under at same point (main + alt merged)
    for pt, over_side, under_side in collect_total_pairs(game):
        pair = _try_low_hold_pair(
            over_side, under_side, books_filter, max_hold_pct
        )
        if pair:
            best_a, best_b, hold = pair
            out.append(
                _emit(game, "totals", pt, over_side, under_side,
                      best_a, best_b, hold)
            )

    return out


def scan_all_low_hold(
    games: list[dict],
    books_filter: set[str] | None = None,
    max_hold_pct: float = 2.5,
) -> list[dict]:
    """Returns low-hold opportunities sorted by hold ascending (tightest
    first). Expects `games` to be commission-adjusted via `rows_to_games`."""
    ops: list[dict] = []
    for g in games:
        ops.extend(scan_game_low_hold(g, books_filter, max_hold_pct))
    ops.sort(key=lambda o: o["hold_pct"])
    return ops
