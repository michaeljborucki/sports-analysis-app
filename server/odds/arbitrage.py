"""Arbitrage scanner.

Identifies markets where the sum of implied probabilities across the best-
priced legs is < 1.0, meaning a risk-free positive-ROI split bet exists.
Prices consumed here are already commission-adjusted by `rows_to_games`; the
scanner treats them as net effective payouts.

Coverage mirrors the EV scanner: every complete two- or three-way bucket,
including period markets, team totals, and player props. Main and alternate
spreads/totals are merged per period suffix before pairing.

3-way arbs require at least 2 distinct books across the 3 legs — three legs
at one book is just the book's vig and never positive.
"""
from __future__ import annotations

from .devig import american_to_implied_prob
from .pairing import collect_spread_pairs, collect_total_pairs
from .venues import OPT_IN_BOOKS, book_allowed, venue


def _ev_pairing_helpers():
    """Import EV's market taxonomy lazily to avoid module-init coupling."""
    from .ev import (
        _base_market, _buckets, _expect_outcome_count, _outcome_key,
        _period_suffix,
    )
    return _base_market, _buckets, _expect_outcome_count, _outcome_key, _period_suffix


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


def _ranked_visible(
    outcome: dict, books_filter: set[str] | None
) -> list[dict]:
    """This outcome's allowed prices, best payout first. Opt-in books
    (novig_maker) only count when the filter names them — see venues.py."""
    prices = [
        p for p in (outcome.get("prices") or [])
        if book_allowed(p["bookmaker_key"], books_filter)
    ]
    return sorted(prices, key=lambda p: _payout_multiplier(p["price_american"]), reverse=True)


def _best_visible(
    outcome: dict, books_filter: set[str] | None
) -> dict | None:
    """Pick the best American-odds price from this outcome, optionally
    restricted to a book-allowlist."""
    ranked = _ranked_visible(outcome, books_filter)
    return ranked[0] if ranked else None


# How deep to look past each side's best price when the two bests share a
# venue (e.g. a Novig maker quote vs a Novig take on the other side).
_PAIR_DEPTH = 4


def best_cross_venue_pair(
    side_a: dict, side_b: dict, books_filter: set[str] | None,
) -> tuple[dict, dict] | None:
    """Best-priced (a, b) whose books are on different venues.

    Same venue is never a real two-way: a book's own two sides carry its
    vig, and a Novig maker quote against a Novig take is just your bid vs
    the book. Without opt-in books this reduces to "best vs best, distinct
    book" exactly as before.
    """
    ranked_a = _ranked_visible(side_a, books_filter)[:_PAIR_DEPTH]
    ranked_b = _ranked_visible(side_b, books_filter)[:_PAIR_DEPTH]
    if not ranked_a or not ranked_b:
        return None
    if venue(ranked_a[0]["bookmaker_key"]) != venue(ranked_b[0]["bookmaker_key"]):
        return ranked_a[0], ranked_b[0]
    if not any(p["bookmaker_key"] in OPT_IN_BOOKS for p in (ranked_a[0], ranked_b[0])):
        # Two ordinary books colliding = the same book on both sides;
        # keep the long-standing behavior (no pair) rather than reaching
        # for second-best prices.
        return None
    best: tuple[float, dict, dict] | None = None
    for pa in ranked_a:
        for pb in ranked_b:
            if venue(pa["bookmaker_key"]) == venue(pb["bookmaker_key"]):
                continue
            total = (american_to_implied_prob(pa["price_american"])
                     + american_to_implied_prob(pb["price_american"]))
            if best is None or total < best[0]:
                best = (total, pa, pb)
    return None if best is None else (best[1], best[2])


def _try_pair(
    side_a: dict,
    side_b: dict,
    books_filter: set[str] | None,
) -> tuple[dict, dict, float] | None:
    """Return (best_price_a, best_price_b, roi_frac) if an arb exists."""
    pair = best_cross_venue_pair(side_a, side_b, books_filter)
    if pair is None:
        return None
    best_a, best_b = pair
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
                "wager_type": best_a.get("wager_type"),
                "counterpart_price_american": best_a.get("counterpart_price_american"),
            },
            {
                "outcome_name": side_b["outcome_name"],
                "book": best_b["bookmaker_key"],
                "price_american": best_b["price_american"],
                "point": best_b.get("point"),
                "stake_pct": stake_b_pct,
                "max_stake_dollars": b_size,
                "wager_type": best_b.get("wager_type"),
                "counterpart_price_american": best_b.get("counterpart_price_american"),
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
    distinct_books = {venue(b["bookmaker_key"]) for b in bests}
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
                "wager_type": b.get("wager_type"),
                "counterpart_price_american": b.get("counterpart_price_american"),
            }
            for s, b, imp in zip(sides, bests, imps)
        ],
    }


def scan_game_arbs(
    game: dict, books_filter: set[str] | None = None
) -> list[dict]:
    out: list[dict] = []

    base_market, buckets, expect_count, outcome_key, period_suffix = _ev_pairing_helpers()
    spread_suffixes: set[str] = set()
    total_suffixes: set[str] = set()
    for market in game.get("markets") or []:
        mk = market.get("market_key", "")
        base = base_market(mk)
        suffix = period_suffix(mk)
        if base in ("spreads", "alternate_spreads"):
            spread_suffixes.add(suffix)
        elif base in ("totals", "alternate_totals"):
            total_suffixes.add(suffix)

    handled: set[str] = set()
    for suffix in spread_suffixes:
        main_mk, alt_mk = f"spreads{suffix}", f"alternate_spreads{suffix}"
        for abs_pt, side_a, side_b in collect_spread_pairs(game, (main_mk, alt_mk)):
            pair = _try_pair(side_a, side_b, books_filter)
            if pair:
                best_a, best_b, roi = pair
                out.append(_emit(game, main_mk, abs_pt, side_a, side_b, best_a, best_b, roi))
        handled.update((main_mk, alt_mk))

    for suffix in total_suffixes:
        main_mk, alt_mk = f"totals{suffix}", f"alternate_totals{suffix}"
        for pt, side_a, side_b in collect_total_pairs(game, (main_mk, alt_mk)):
            pair = _try_pair(side_a, side_b, books_filter)
            if pair:
                best_a, best_b, roi = pair
                out.append(_emit(game, main_mk, pt, side_a, side_b, best_a, best_b, roi))
        handled.update((main_mk, alt_mk))

    # EV-compatible generic path: H2H, team totals, props, periods, and any
    # other market whose bucket contains a complete two- or three-way set.
    for market in game.get("markets") or []:
        mk = market.get("market_key")
        if not mk or mk in handled:
            continue
        keyed = {outcome_key(o): o for o in market.get("outcomes") or []}
        expected = expect_count(mk, {k: {} for k in keyed})
        for _bucket, keys in buckets(mk, list(keyed)).items():
            if len(keys) != expected:
                continue
            sides = [keyed[k] for k in keys]
            point = keys[0][1] if all(k[1] == keys[0][1] for k in keys) else None
            if expected == 2:
                pair = _try_pair(sides[0], sides[1], books_filter)
                if pair:
                    best_a, best_b, roi = pair
                    out.append(_emit(game, mk, point, sides[0], sides[1], best_a, best_b, roi))
            else:
                result = _try_three_way(sides, books_filter)
                if result:
                    bests, roi = result
                    emitted = _emit_three_way(game, mk, sides, bests, roi)
                    emitted["point"] = point
                    out.append(emitted)

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
