"""Profit-boost conversion scanner.

A profit boost multiplies the *winnings* portion of a bet by `1 + boost_pct/100`.
Applied to one leg of a two-way market and hedged with cash at the opposite
side on a DIFFERENT book, the boost can manufacture a guaranteed-profit pair
(synthetic arb) where the un-boosted pair would have positive hold.

Math (per stake $S on boosted leg A, hedge $H on leg B):

  Boosted decimal of A: r_A_boost = 1 + (decimal_A − 1) × (1 + boost_pct/100)
  Equal-profit hedge:   H = S × (1 + r_A_boost) / (1 + r_B)
  Net profit (either side wins):
                        P = S × (r_A_boost × r_B − 1) / (1 + r_B)
  Total stake:          T = S + H = S × (2 + r_A_boost + r_B) / (1 + r_B)
  Conversion %:         P / T × 100  =  (r_A_boost × r_B − 1) / (2 + r_A_boost + r_B) × 100

Equivalent in implied-prob terms:

  imp_A_boost = 1 / (1 + r_A_boost)
  imp_B       = 1 / (1 + r_B)
  Boosted hold % = (imp_A_boost + imp_B − 1) / (imp_A_boost + imp_B) × 100

Negative hold ⇔ positive conversion ⇔ guaranteed profit.

Differs from `arbitrage`/`low_hold` in that the boost is what produces the
arb — without it, these pairs would be at typical retail hold. Differs from
`free_bet` in that the user keeps their stake (cash bet, not a free bet),
so conversion math uses (decimal − 1) for both legs symmetrically rather
than treating the boosted leg as paying winnings only.

Prices passed in are already commission-adjusted by `rows_to_games`.
"""
from __future__ import annotations

from .arbitrage import _find_market
from .devig import american_to_decimal, american_to_implied_prob
from .pairing import collect_spread_pairs, collect_total_pairs


def decimal_to_american(decimal: float) -> int:
    """Inverse of `devig.american_to_decimal`. Rounds to the nearest int.
    Returns 0 for invalid inputs (decimal <= 1.0)."""
    win = decimal - 1.0
    if win <= 0.0:
        return 0
    if win >= 1.0:
        return int(round(win * 100.0))
    return -int(round(100.0 / win))


def boost_american(american: int, boost_pct: float) -> int:
    """Apply a profit-boost percentage to an American odds line."""
    if american == 0 or boost_pct <= 0.0:
        return american
    decimal = american_to_decimal(american)
    boosted_decimal = 1.0 + (decimal - 1.0) * (1.0 + boost_pct / 100.0)
    return decimal_to_american(boosted_decimal)


def _payout_ratio(american: int) -> float:
    """Decimal odds minus 1 — i.e., $ won per $1 staked."""
    return american / 100.0 if american > 0 else 100.0 / -american


def _filter_prices(
    outcome: dict, books_filter: set[str] | None
) -> list[dict]:
    prices = outcome.get("prices") or []
    if books_filter is None:
        return list(prices)
    return [p for p in prices if p["bookmaker_key"] in books_filter]


def _boosted_payout_ratio(american: int, boost_pct: float) -> float:
    """Boosted payout ratio = original_ratio × (1 + boost_pct/100)."""
    return _payout_ratio(american) * (1.0 + boost_pct / 100.0)


def _best_conversion_for_direction(
    boost_side: dict,
    hedge_side: dict,
    hedge_books_filter: set[str] | None,
    boost_books_filter: set[str] | None,
    boost_pct: float,
    min_boost_odds: int,
) -> tuple[dict, dict, float, float] | None:
    """For one direction (boost_side as the boosted leg), find the
    (boost_book, hedge_book) pair with the highest conversion. Returns
    (boost_price, hedge_price, conversion_pct, hold_pct) or None.

    `boost_books_filter` restricts only the boosted leg — use this to
    enforce "the boost token is at coral33 so coral33 MUST be the boost
    leg." Boost-side and hedge-side books must differ.
    """
    boost_candidate_books = boost_books_filter
    if boost_candidate_books is not None and hedge_books_filter is not None:
        boost_candidate_books = boost_candidate_books & hedge_books_filter
    elif boost_candidate_books is None:
        boost_candidate_books = hedge_books_filter

    boost_prices = [
        p for p in _filter_prices(boost_side, boost_candidate_books)
        if p["price_american"] >= min_boost_odds
    ]
    hedge_prices = _filter_prices(hedge_side, hedge_books_filter)
    if not boost_prices or not hedge_prices:
        return None

    best: tuple[dict, dict, float, float] | None = None
    for bp in boost_prices:
        r_boost = _boosted_payout_ratio(bp["price_american"], boost_pct)
        # Implied prob of the boosted leg = 1 / (1 + r_boost).
        imp_boost = 1.0 / (1.0 + r_boost)
        for hp in hedge_prices:
            if hp["bookmaker_key"] == bp["bookmaker_key"]:
                continue  # legs must land at different books
            r_hedge = _payout_ratio(hp["price_american"])
            imp_hedge = american_to_implied_prob(hp["price_american"])
            sum_imp = imp_boost + imp_hedge
            if sum_imp <= 0.0:
                continue
            hold_pct = (sum_imp - 1.0) / sum_imp * 100.0
            # Conversion % = (r_boost × r_hedge - 1) / (2 + r_boost + r_hedge) × 100.
            denom = 2.0 + r_boost + r_hedge
            if denom <= 0.0:
                continue
            conv_pct = (r_boost * r_hedge - 1.0) / denom * 100.0
            if best is None or conv_pct > best[2]:
                best = (bp, hp, conv_pct, hold_pct)
    return best


def _pair_best_boost(
    side_a: dict,
    side_b: dict,
    hedge_books_filter: set[str] | None,
    boost_books_filter: set[str] | None,
    boost_pct: float,
    min_boost_odds: int,
) -> tuple[dict, dict, dict, dict, float, float] | None:
    """Try both directions (A or B as the boosted leg). Returns
    (boost_outcome, boost_price, hedge_outcome, hedge_price, conversion_pct,
    hold_pct) or None."""
    a_as_boost = _best_conversion_for_direction(
        side_a, side_b,
        hedge_books_filter, boost_books_filter, boost_pct, min_boost_odds,
    )
    b_as_boost = _best_conversion_for_direction(
        side_b, side_a,
        hedge_books_filter, boost_books_filter, boost_pct, min_boost_odds,
    )

    best: tuple[dict, dict, dict, dict, float, float] | None = None
    if a_as_boost is not None:
        bp, hp, conv, hold = a_as_boost
        best = (side_a, bp, side_b, hp, conv, hold)
    if b_as_boost is not None:
        bp, hp, conv, hold = b_as_boost
        if best is None or conv > best[4]:
            best = (side_b, bp, side_a, hp, conv, hold)
    return best


def _emit(
    game: dict,
    market_kind: str,
    point: float | None,
    boost_outcome: dict,
    boost_price: dict,
    hedge_outcome: dict,
    hedge_price: dict,
    boost_pct: float,
    conversion_pct: float,
    hold_pct: float,
) -> dict:
    boosted_american = boost_american(boost_price["price_american"], boost_pct)
    return {
        "sport_key": game.get("sport_key", "mlb"),
        "event_id": game["event_id"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "commence_time": game["commence_time"],
        "market_kind": market_kind,
        "point": point,
        # Conversion = guaranteed profit / total stake. Negative when the
        # boost isn't large enough to overcome book hold.
        "conversion_pct": conversion_pct,
        # Boosted-pair hold. Mirrors the low_hold scanner's metric so the
        # workbench can compare boost-pair tightness to natural low-hold.
        # Negative hold = profitable conversion.
        "hold_pct": hold_pct,
        "boost_pct": boost_pct,
        # Per-$100 hedge stake: how much to put on the hedge for every $100
        # placed on the boosted leg. Same formula as free_bet but using
        # the BOOSTED payout ratio of the offered leg.
        "hedge_stake_per_100_boost": (
            100.0
            * (1.0 + _boosted_payout_ratio(boost_price["price_american"], boost_pct))
            / (1.0 + _payout_ratio(hedge_price["price_american"]))
        ),
        "boost_leg": {
            "outcome_name": boost_outcome["outcome_name"],
            "book": boost_price["bookmaker_key"],
            "original_price_american": boost_price["price_american"],
            "boosted_price_american": boosted_american,
            "point": boost_price.get("point"),
        },
        "hedge_leg": {
            "outcome_name": hedge_outcome["outcome_name"],
            "book": hedge_price["bookmaker_key"],
            "price_american": hedge_price["price_american"],
            "point": hedge_price.get("point"),
        },
    }


def scan_game_profit_boost(
    game: dict,
    hedge_books_filter: set[str] | None,
    boost_books_filter: set[str] | None,
    boost_pct: float,
    min_boost_odds: int,
    min_conversion_pct: float,
) -> list[dict]:
    out: list[dict] = []

    h2h = _find_market(game, "h2h")
    if h2h and len(h2h.get("outcomes", [])) == 2:
        a, b = h2h["outcomes"]
        pair = _pair_best_boost(
            a, b, hedge_books_filter, boost_books_filter,
            boost_pct, min_boost_odds,
        )
        if pair is not None:
            bo, bp, ho, hp, conv, hold = pair
            if conv >= min_conversion_pct:
                out.append(_emit(
                    game, "h2h", None, bo, bp, ho, hp,
                    boost_pct, conv, hold,
                ))

    for abs_pt, home_side, away_side in collect_spread_pairs(game):
        pair = _pair_best_boost(
            home_side, away_side, hedge_books_filter, boost_books_filter,
            boost_pct, min_boost_odds,
        )
        if pair is not None:
            bo, bp, ho, hp, conv, hold = pair
            if conv >= min_conversion_pct:
                out.append(_emit(
                    game, "spreads", abs_pt, bo, bp, ho, hp,
                    boost_pct, conv, hold,
                ))

    for pt, over_side, under_side in collect_total_pairs(game):
        pair = _pair_best_boost(
            over_side, under_side, hedge_books_filter, boost_books_filter,
            boost_pct, min_boost_odds,
        )
        if pair is not None:
            bo, bp, ho, hp, conv, hold = pair
            if conv >= min_conversion_pct:
                out.append(_emit(
                    game, "totals", pt, bo, bp, ho, hp,
                    boost_pct, conv, hold,
                ))

    return out


def scan_all_profit_boost(
    games: list[dict],
    hedge_books_filter: set[str] | None = None,
    boost_books_filter: set[str] | None = None,
    boost_pct: float = 30.0,
    min_boost_odds: int = -10_000,
    min_conversion_pct: float = 0.0,
) -> list[dict]:
    """Returns profit-boost conversion opportunities sorted by conversion
    percentage descending.

    hedge_books_filter: universe of books usable for either leg. Default
        None = any book.
    boost_books_filter: books the user has a boost token at; the BOOSTED
        leg will always land at one of these. Default None = use the hedge
        universe (no boost-specific restriction).
    boost_pct: percentage boost on winnings (default 30). 0 disables.
    min_boost_odds: floor for the boosted leg's ORIGINAL American price.
        Default -10000 = effectively unlimited; raise to e.g. +100 if the
        user only wants to boost on plus-odds lines.
    min_conversion_pct: only emit pairs whose guaranteed conversion %
        clears this threshold. Default 0 = surface every break-even-or-
        better pair (negative-hold pairs).
    """
    ops: list[dict] = []
    for g in games:
        ops.extend(
            scan_game_profit_boost(
                g, hedge_books_filter, boost_books_filter,
                boost_pct, min_boost_odds, min_conversion_pct,
            )
        )
    ops.sort(key=lambda o: -o["conversion_pct"])
    return ops
