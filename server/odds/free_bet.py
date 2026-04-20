"""Free-bet conversion scanner.

A free bet pays only profit on a win (stake not returned). To extract as much
cash as possible regardless of outcome, place the free bet on one side and
hedge the other side at a different book.

  F × r_A   (free-bet payout on A win)
  H × r_B   (hedge payout on B win)
  H         (hedge stake lost on A win)

Equal-profit hedge: H = F × r_A / (1 + r_B)
Net profit        = F × r_A × r_B / (1 + r_B)
Conversion rate   = r_A × r_B / (1 + r_B)  =  r_A × (1 - implied_B)

Where r_X = payout ratio of side X = decimal_odds - 1 = 1/implied - 1.

Prices passed in are already commission-adjusted by `rows_to_games`.
"""
from __future__ import annotations

from .arbitrage import _find_market
from .devig import american_to_implied_prob
from .pairing import collect_spread_pairs, collect_total_pairs


def _payout_ratio(american: int) -> float:
    return american / 100.0 if american > 0 else 100.0 / -american


def _filter_prices(
    outcome: dict, books_filter: set[str] | None
) -> list[dict]:
    prices = outcome.get("prices") or []
    if books_filter is None:
        return list(prices)
    return [p for p in prices if p["bookmaker_key"] in books_filter]


def _best_conversion_for_direction(
    free_side: dict,
    hedge_side: dict,
    books_filter: set[str] | None,
    min_free_odds: int,
) -> tuple[dict, dict, float] | None:
    """For one direction (free_side as the free-bet leg, hedge_side as the
    hedge), find the (book_free, book_hedge) combo with book_free != book_hedge
    that maximizes conversion."""
    free_prices = [
        p for p in _filter_prices(free_side, books_filter)
        if p["price_american"] >= min_free_odds
    ]
    hedge_prices = _filter_prices(hedge_side, books_filter)
    if not free_prices or not hedge_prices:
        return None

    best: tuple[dict, dict, float] | None = None
    for fp in free_prices:
        r_free = _payout_ratio(fp["price_american"])
        for hp in hedge_prices:
            if hp["bookmaker_key"] == fp["bookmaker_key"]:
                continue  # must use two different books
            r_hedge = _payout_ratio(hp["price_american"])
            conv = r_free * r_hedge / (1.0 + r_hedge)
            if best is None or conv > best[2]:
                best = (fp, hp, conv)
    return best


def _pair_best_free_bet(
    side_a: dict,
    side_b: dict,
    books_filter: set[str] | None,
    min_free_odds: int,
) -> tuple[dict, dict, dict, dict, float] | None:
    """Try both directions (A or B as the free-bet leg); return the best
    combination. Returns (free_outcome, free_price, hedge_outcome, hedge_price,
    conversion_rate) or None."""
    a_as_free = _best_conversion_for_direction(
        side_a, side_b, books_filter, min_free_odds
    )
    b_as_free = _best_conversion_for_direction(
        side_b, side_a, books_filter, min_free_odds
    )

    best: tuple[dict, dict, dict, dict, float] | None = None
    if a_as_free is not None:
        fp, hp, conv = a_as_free
        best = (side_a, fp, side_b, hp, conv)
    if b_as_free is not None:
        fp, hp, conv = b_as_free
        if best is None or conv > best[4]:
            best = (side_b, fp, side_a, hp, conv)
    return best


def _emit(
    game: dict,
    market_kind: str,
    point: float | None,
    free_outcome: dict,
    free_price: dict,
    hedge_outcome: dict,
    hedge_price: dict,
    conv: float,
) -> dict:
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,
        "point": point,
        "conversion_pct": conv * 100.0,
        # How much to hedge per $100 free-bet face value
        "hedge_stake_per_100": (
            100.0 * _payout_ratio(free_price["price_american"])
            / (1.0 + _payout_ratio(hedge_price["price_american"]))
        ),
        "free_leg": {
            "outcome_name": free_outcome["outcome_name"],
            "book": free_price["bookmaker_key"],
            "price_american": free_price["price_american"],
            "point": free_price.get("point"),
        },
        "hedge_leg": {
            "outcome_name": hedge_outcome["outcome_name"],
            "book": hedge_price["bookmaker_key"],
            "price_american": hedge_price["price_american"],
            "point": hedge_price.get("point"),
        },
    }


def scan_game_free_bets(
    game: dict,
    books_filter: set[str] | None,
    min_free_odds: int,
) -> list[dict]:
    out: list[dict] = []

    # H2H
    h2h = _find_market(game, "h2h")
    if h2h and len(h2h.get("outcomes", [])) == 2:
        a, b = h2h["outcomes"]
        pair = _pair_best_free_bet(a, b, books_filter, min_free_odds)
        if pair:
            fo, fp, ho, hp, conv = pair
            out.append(_emit(game, "h2h", None, fo, fp, ho, hp, conv))

    # Spreads — pair by complementary signed points (main + alt merged)
    for abs_pt, home_side, away_side in collect_spread_pairs(game):
        pair = _pair_best_free_bet(
            home_side, away_side, books_filter, min_free_odds
        )
        if pair:
            fo, fp, ho, hp, conv = pair
            out.append(_emit(game, "spreads", abs_pt, fo, fp, ho, hp, conv))

    # Totals — pair Over and Under at same point (main + alt merged)
    for pt, over_side, under_side in collect_total_pairs(game):
        pair = _pair_best_free_bet(
            over_side, under_side, books_filter, min_free_odds
        )
        if pair:
            fo, fp, ho, hp, conv = pair
            out.append(_emit(game, "totals", pt, fo, fp, ho, hp, conv))

    return out


def scan_all_free_bets(
    games: list[dict],
    books_filter: set[str] | None = None,
    min_free_odds: int = 100,
) -> list[dict]:
    """Returns free-bet conversion opportunities sorted by conversion desc."""
    ops: list[dict] = []
    for g in games:
        ops.extend(scan_game_free_bets(g, books_filter, min_free_odds))
    ops.sort(key=lambda o: -o["conversion_pct"])
    return ops
