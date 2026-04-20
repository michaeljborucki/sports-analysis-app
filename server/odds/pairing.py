"""Shared pairing helpers for scanners (arbitrage, low-hold, free-bet, EV).

The scanners all need to pair complementary outcomes in a market so they can
compare implied probabilities. Two-way markets have the subtlety that:

1. **Spreads pair by SIGNED point, not |point|.** Home at -3 is complementary
   to Away at +3 (Nuggets by 3+ vs Wolves losing by <3). Pairing Home at -3
   with Away at -3 is NOT an arb — both teams covering the spread is
   mutually exclusive but not complementary. When alt lines post both
   orientations, a naïve bucket on |point| produces false positives.

2. **Main and alt markets share outcomes.** Over at 220.5 on DraftKings may
   appear in `totals` while Over at 220.5 on BetMGM appears in
   `alternate_totals`. Both represent the same logical bet — prices must be
   merged into a single outcome, not overwritten.

Helpers here normalize both issues. Callers feed `rows_to_games` output.
"""
from __future__ import annotations

from collections import defaultdict


DEFAULT_SPREAD_MARKETS = ("spreads", "alternate_spreads")


def _find_market(game: dict, key: str) -> dict | None:
    for m in game.get("markets", []):
        if m.get("market_key") == key:
            return m
    return None


def _outcome_point(out: dict) -> float | None:
    """Every price under an outcome shares the same point (rows_to_games groups
    that way). Pick the point off the first price, with best_price as a
    fallback."""
    if out.get("best_price") and out["best_price"].get("point") is not None:
        return out["best_price"]["point"]
    prices = out.get("prices") or []
    if prices and prices[0].get("point") is not None:
        return prices[0]["point"]
    return None
DEFAULT_TOTAL_MARKETS = ("totals", "alternate_totals")


def _merge_outcome_prices(a: dict, b: dict) -> dict:
    """Return a copy of outcome `a` with `b`'s prices appended. Used when the
    same logical bet appears in multiple markets (e.g. main + alt).

    Preserves `outcome_name` from `a` (they're equal by construction); drops
    the stale `best_price`/`consensus_price_american` fields since they're
    recomputed downstream anyway."""
    return {
        "outcome_name": a["outcome_name"],
        "prices": list(a.get("prices", [])) + list(b.get("prices", [])),
    }


def collect_spread_pairs(
    game: dict,
    market_keys: tuple[str, ...] = DEFAULT_SPREAD_MARKETS,
) -> list[tuple[float, dict, dict]]:
    """Return `(|point|, home_side, away_side)` tuples where home_side and
    away_side have COMPLEMENTARY signed points.

    For each |X| where the pairing is possible, emits up to two tuples (one
    per orientation):
      - `(X, home@-X, away@+X)` — Home favored by X
      - `(X, home@+X, away@-X)` — Away favored by X

    Prices from all `market_keys` markets are merged, so a book posting a
    line in `alternate_spreads` is visible alongside books posting it in
    `spreads`.
    """
    home = game["home_team"]
    away = game["away_team"]

    # (team_name, signed_point) → merged outcome
    buckets: dict[tuple[str, float], dict] = {}
    for mk in market_keys:
        m = _find_market(game, mk)
        if not m:
            continue
        for o in m["outcomes"]:
            pt = _outcome_point(o)
            if pt is None:
                continue
            name = o["outcome_name"]
            if name not in (home, away):
                continue
            key = (name, round(pt, 1))
            if key in buckets:
                buckets[key] = _merge_outcome_prices(buckets[key], o)
            else:
                buckets[key] = dict(o)

    out: list[tuple[float, dict, dict]] = []
    seen: set[tuple[float, int]] = set()  # (|X|, home_sign) to dedupe
    for (team, pt), home_outcome in buckets.items():
        if team != home:
            continue
        mirror = buckets.get((away, round(-pt, 1)))
        if mirror is None:
            continue
        abs_pt = round(abs(pt), 1)
        home_sign = 0 if pt == 0 else (1 if pt > 0 else -1)
        orient_key = (abs_pt, home_sign)
        if orient_key in seen:
            continue
        seen.add(orient_key)
        out.append((abs_pt, home_outcome, mirror))
    # Stable sort so output is deterministic: by |X| ascending, then home_sign.
    out.sort(key=lambda t: (t[0], 0 if t[1] is buckets.get((home, -t[0])) else 1))
    return out


def collect_total_pairs(
    game: dict,
    market_keys: tuple[str, ...] = DEFAULT_TOTAL_MARKETS,
) -> list[tuple[float, dict, dict]]:
    """Return `(point, over_outcome, under_outcome)` tuples. Prices from all
    `market_keys` markets are merged so a book posting Over 7.5 in `totals`
    and another posting it in `alternate_totals` both contribute."""
    buckets: dict[tuple[str, float], dict] = {}
    for mk in market_keys:
        m = _find_market(game, mk)
        if not m:
            continue
        for o in m["outcomes"]:
            pt = _outcome_point(o)
            if pt is None:
                continue
            name = o["outcome_name"]
            if name not in ("Over", "Under"):
                continue
            key = (name, round(pt, 1))
            if key in buckets:
                buckets[key] = _merge_outcome_prices(buckets[key], o)
            else:
                buckets[key] = dict(o)

    by_pt: dict[float, dict[str, dict]] = defaultdict(dict)
    for (name, pt), o in buckets.items():
        by_pt[pt][name] = o
    out: list[tuple[float, dict, dict]] = []
    for pt, sides in sorted(by_pt.items()):
        if "Over" in sides and "Under" in sides:
            out.append((pt, sides["Over"], sides["Under"]))
    return out
