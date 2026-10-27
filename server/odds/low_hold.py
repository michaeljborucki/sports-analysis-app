"""Low-hold scanner.

A "low-hold" line is a complete two- or three-way market where the best
available prices across books sum to a small overround — the book's cut is
near zero, meaning the market is tightly priced. Negative hold is an arb;
those rows are intentionally included here and display as positive edge.

Hold % = (sum_implied - 1) / sum_implied × 100
  -110 / -110 → sum 1.0476, hold 4.55%  (typical retail)
  -105 / -105 → sum 1.0244, hold 2.38%  (sharp market)

Prices passed in are already commission-adjusted by `rows_to_games`.
"""
from __future__ import annotations

from .arbitrage import _best_visible, _find_market, best_cross_venue_pair
from .venues import venue
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
    pair = best_cross_venue_pair(side_a, side_b, books_filter)
    if pair is None:
        return None
    best_a, best_b = pair
    imp_a = american_to_implied_prob(best_a["price_american"])
    imp_b = american_to_implied_prob(best_b["price_american"])
    total = imp_a + imp_b
    # Negative hold is arbitrage. Keep it in the low-hold continuum so this
    # view spans negative edge (vig) through zero to positive edge (arb).
    hold = _hold_pct(imp_a, imp_b)
    if hold > max_hold_pct:
        return None
    return best_a, best_b, hold


def _try_low_hold_n_way(
    sides: list[dict], books_filter: set[str] | None, max_hold_pct: float,
) -> tuple[list[dict], float] | None:
    bests = [_best_visible(side, books_filter) for side in sides]
    if any(best is None for best in bests):
        return None
    concrete = [best for best in bests if best is not None]
    if len({venue(best["bookmaker_key"]) for best in concrete}) < 2:
        return None
    total = sum(american_to_implied_prob(best["price_american"]) for best in concrete)
    hold = (total - 1.0) / total * 100.0
    if hold > max_hold_pct:
        return None
    return concrete, hold


def _emit_n_way(game: dict, market_kind: str, point: float | None,
                sides: list[dict], bests: list[dict], hold: float) -> dict:
    emitted = _emit(game, market_kind, point, sides[0], sides[1], bests[0], bests[1], hold)
    emitted["sides"] = [
        {
            "outcome_name": side["outcome_name"],
            "book": best["bookmaker_key"],
            "price_american": best["price_american"],
            "point": best.get("point"),
            "wager_type": best.get("wager_type"),
            "counterpart_price_american": best.get("counterpart_price_american"),
            "max_stake_dollars": best.get("max_stake_dollars"),
        }
        for side, best in zip(sides, bests)
    ]
    return emitted


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
                "wager_type": best_a.get("wager_type"),
                "counterpart_price_american": best_a.get("counterpart_price_american"),
                "max_stake_dollars": best_a.get("max_stake_dollars"),
            },
            {
                "outcome_name": side_b["outcome_name"],
                "book": best_b["bookmaker_key"],
                "price_american": best_b["price_american"],
                "point": best_b.get("point"),
                "wager_type": best_b.get("wager_type"),
                "counterpart_price_american": best_b.get("counterpart_price_american"),
                "max_stake_dollars": best_b.get("max_stake_dollars"),
            },
        ],
    }


def scan_game_low_hold(
    game: dict,
    books_filter: set[str] | None,
    max_hold_pct: float,
) -> list[dict]:
    out: list[dict] = []

    from .arbitrage import _ev_pairing_helpers
    base_market, buckets, expect_count, outcome_key, period_suffix = _ev_pairing_helpers()
    spread_suffixes: set[str] = set()
    total_suffixes: set[str] = set()
    for market in game.get("markets") or []:
        mk = market.get("market_key", "")
        base, suffix = base_market(mk), period_suffix(mk)
        if base in ("spreads", "alternate_spreads"):
            spread_suffixes.add(suffix)
        elif base in ("totals", "alternate_totals"):
            total_suffixes.add(suffix)

    handled: set[str] = set()
    for suffix in spread_suffixes:
        main_mk, alt_mk = f"spreads{suffix}", f"alternate_spreads{suffix}"
        for pt, a, b in collect_spread_pairs(game, (main_mk, alt_mk)):
            pair = _try_low_hold_pair(a, b, books_filter, max_hold_pct)
            if pair:
                best_a, best_b, hold = pair
                out.append(_emit(game, main_mk, pt, a, b, best_a, best_b, hold))
        handled.update((main_mk, alt_mk))
    for suffix in total_suffixes:
        main_mk, alt_mk = f"totals{suffix}", f"alternate_totals{suffix}"
        for pt, a, b in collect_total_pairs(game, (main_mk, alt_mk)):
            pair = _try_low_hold_pair(a, b, books_filter, max_hold_pct)
            if pair:
                best_a, best_b, hold = pair
                out.append(_emit(game, main_mk, pt, a, b, best_a, best_b, hold))
        handled.update((main_mk, alt_mk))

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
            result = _try_low_hold_n_way(sides, books_filter, max_hold_pct)
            if result:
                bests, hold = result
                out.append(_emit_n_way(game, mk, point, sides, bests, hold))

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
