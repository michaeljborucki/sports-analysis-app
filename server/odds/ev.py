"""Positive expected-value (+EV) scanner.

For every offered outcome price across every book, compare to a "fair"
probability derived from a sharp anchor and emit +EV opportunities when the
offered odds beat fair.

Fair-probability source order:
  1. Pinnacle no-vig — devig Pinnacle's price for the same (market, outcome).
     Primary for mainlines (ML, spreads, totals, team totals, periods).
  2. Consensus no-vig — median of per-book devigged probabilities across
     sharp books (falls back to all books when <2 sharp books post).
     Primary for player props and anything Pinnacle doesn't cover.

Prices consumed here are already commission-adjusted by `rows_to_games`, so
the EV is computed against effective (net) payouts.

Industry defaults:
  - Multiplicative devig (OddsJam / Unabated default)
  - Quarter-Kelly reported alongside full Kelly
  - Stale offered prices dropped (>60s)
  - Longshot cutoff at +800 to avoid devig-model noise
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from .devig import (
    american_to_decimal,
    american_to_implied_prob,
    devig_n_way,
    devig_two_way,
    implied_to_american,
)
from .pairing import collect_spread_pairs, collect_total_pairs


# Books trusted as sharp anchors. Pinnacle is the canonical price-discovery
# venue; BetOnline and LowVig are sharp-adjacent offshores. All three appear
# in our BOOK_ORDER. The Odds API reliably provides Pinnacle for majors; the
# others are fallbacks when Pinnacle is absent (mostly props).
SHARP_BOOKS: frozenset[str] = frozenset({
    "pinnacle", "betonlineag", "lowvig",
})

# Confidence cap — EV above this is almost always stale or mispriced data.
HIGH_EV_CONFIDENCE_CUTOFF = 0.15   # 15% ROI

# Period suffixes that should devig identically to their base market —
# h2h_h1 pairs outcomes like h2h, spreads_q1 like spreads. Covers:
#   - basketball halves/quarters: _h1 _h2 _q1..q4
#   - hockey periods:             _p1 _p2 _p3
#   - baseball innings:           _1st_N_innings  (Odds API canonical) and _fN
_PERIOD_SUFFIX_RE = re.compile(
    r"_(?:h[12]|q[1-4]|p[1-3]|1st_\d+_innings|f\d+)$"
)

# Treated as 3-way for devig (n=3). All others are 2-way by default.
THREE_WAY_BASES = {"h2h_3_way"}


def _base_market(market_key: str) -> str:
    """Strip period suffix: h2h_h1 → h2h, spreads_q1 → spreads. Preserves
    alternate_* and player prop keys unchanged."""
    return _PERIOD_SUFFIX_RE.sub("", market_key)


def _period_suffix(market_key: str) -> str:
    """Return the period suffix like '_h1', '_q2', '_1st_5_innings', or ''."""
    m = _PERIOD_SUFFIX_RE.search(market_key)
    return m.group(0) if m else ""


def _is_three_way(market_key: str) -> bool:
    return _base_market(market_key) in THREE_WAY_BASES


def _pair_bucket(market_key: str, outcome_key: tuple[str, float | None]) -> object:
    """Grouping key that identifies which outcomes devig together.

    Logic per market family:
      - h2h, h2h_3_way (+ period suffixes): all outcomes in one bucket.
      - totals / alternate_totals: group by point (Over/Under share it).
      - spreads / alternate_spreads: group by |point| (Home -X pairs with
        Away +X).
      - team_totals / alternate_team_totals: group by (team_prefix, point)
        since each team has its own Over/Under pair.
      - Player props (anything else with "Over"/"Under" outcomes at same
        point): group by (market_key, point).
    """
    name, point = outcome_key
    base = _base_market(market_key)
    if base in ("h2h", "h2h_3_way"):
        return ("h2h", None)
    if base == "totals":
        return ("totals", point)
    if base == "alternate_totals":
        return ("alternate_totals", point)
    if base == "spreads":
        return ("spreads", None if point is None else round(abs(point), 1))
    if base == "alternate_spreads":
        return ("alternate_spreads", None if point is None else round(abs(point), 1))
    if base in ("team_totals", "alternate_team_totals"):
        prefix = name
        for suf in (" Over", " Under"):
            if name.endswith(suf):
                prefix = name[: -len(suf)]
                break
        return (base, prefix, point)
    if base.startswith(("player_", "pitcher_", "batter_")):
        # Outcome_name is encoded as "<Player Name> Over|Under|Yes|No" by
        # normalize.py's _encode_outcome_name. Peel off the side to get the
        # player identity; pair Over/Under (or Yes/No) for the same player.
        for suf in (" Over", " Under", " Yes", " No"):
            if name.endswith(suf):
                player = name[: -len(suf)]
                return (base, player, point)
        # Categorical / single-sided outcomes (e.g. method_of_first_basket) —
        # each is its own bucket, which won't pair for 2-way devig.
        return (base, name, point)
    # Catch-all: group by (market, point).
    return (market_key, point)


def _age_seconds(price: dict, now: datetime) -> float:
    fa = price.get("fetched_at")
    if fa is None:
        return 0.0
    if isinstance(fa, str):
        fa = datetime.fromisoformat(fa.replace("Z", "+00:00"))
    if fa.tzinfo is None:
        fa = fa.replace(tzinfo=timezone.utc)
    return max(0.0, (now - fa).total_seconds())


def _outcome_key(out: dict) -> tuple[str, float | None]:
    """Stable key for matching outcomes across books: (name, rounded point).
    Points are rounded to 1dp to handle floating-point jitter between books."""
    pt = None
    prices = out.get("prices") or []
    if prices and prices[0].get("point") is not None:
        pt = round(float(prices[0]["point"]), 1)
    elif out.get("best_price") and out["best_price"].get("point") is not None:
        pt = round(float(out["best_price"]["point"]), 1)
    return (out["outcome_name"], pt)


def _prices_by_book(outcome: dict) -> dict[str, dict]:
    """Map bookmaker_key → price dict for this outcome. One entry per book;
    if a book posts multiple prices we keep the first (our cache dedupes via
    PK so this is effectively 1-to-1)."""
    out: dict[str, dict] = {}
    for p in outcome.get("prices") or []:
        bk = p["bookmaker_key"]
        if bk not in out:
            out[bk] = p
    return out


def _collect_market_outcomes(
    market: dict,
) -> dict[tuple[str, float | None], dict[str, dict]]:
    """For each (outcome_name, point) tuple in this market, gather prices per
    book. Returns {outcome_key -> {book -> price_dict}}."""
    by_outcome: dict[tuple[str, float | None], dict[str, dict]] = {}
    for o in market.get("outcomes") or []:
        key = _outcome_key(o)
        by_outcome[key] = _prices_by_book(o)
    return by_outcome


def _stale(price: dict, now: datetime, limit_s: float) -> bool:
    return _age_seconds(price, now) > limit_s


def _buckets(
    market_key: str,
    outcome_keys: list[tuple[str, float | None]],
) -> dict[object, list[tuple[str, float | None]]]:
    """Group outcome_keys by their pairing bucket per _pair_bucket."""
    groups: dict[object, list[tuple[str, float | None]]] = defaultdict(list)
    for k in outcome_keys:
        groups[_pair_bucket(market_key, k)].append(k)
    return groups


def _expect_outcome_count(
    market_key: str,
    by_outcome: dict[tuple[str, float | None], dict[str, dict]],
) -> int:
    """How many outcomes per bucket should we require to devig together?

    h2h_3_way and explicit 3-way bases → always 3.
    Soccer h2h returns 3 outcomes (home/draw/away) under the plain `h2h`
    key — detected by the presence of a "Draw" outcome name.
    Everything else is 2-way (over/under, two-team h2h, spread pairs).
    """
    if _is_three_way(market_key):
        return 3
    if any(name == "Draw" for (name, _pt) in by_outcome.keys()):
        return 3
    return 2


def _pinnacle_fair(
    by_outcome: dict[tuple[str, float | None], dict[str, dict]],
    market_key: str,
    now: datetime,
    stale_seconds: float,
) -> dict[tuple[str, float | None], float] | None:
    """Devig Pinnacle's prices. Returns {outcome_key -> fair_prob} or None if
    Pinnacle isn't fully present for this market's grouping."""
    expect_n = _expect_outcome_count(market_key, by_outcome)
    three_way = expect_n == 3
    buckets = _buckets(market_key, list(by_outcome.keys()))

    probs: dict[tuple[str, float | None], float] = {}
    for _bucket, keys in buckets.items():
        if len(keys) != expect_n:
            continue
        prices: list[int] = []
        ordered_keys: list[tuple[str, float | None]] = []
        bail = False
        for k in keys:
            p = by_outcome[k].get("pinnacle")
            if not p or _stale(p, now, stale_seconds):
                bail = True
                break
            prices.append(int(p["price_american"]))
            ordered_keys.append(k)
        if bail:
            continue
        if three_way:
            fair = devig_n_way(prices)
        else:
            fp1, fp2 = devig_two_way(prices[0], prices[1])
            fair = [fp1, fp2]
        for k, p in zip(ordered_keys, fair):
            probs[k] = p

    return probs or None


def _consensus_fair(
    by_outcome: dict[tuple[str, float | None], dict[str, dict]],
    market_key: str,
    now: datetime,
    stale_seconds: float,
    sharp_books: frozenset[str],
) -> tuple[dict[tuple[str, float | None], float], int] | None:
    """Per-book devig then take median across books. Returns
    ({outcome_key -> fair_prob}, anchor_book_count) or None if insufficient
    data. Falls back from sharp-only to all-books when <2 sharp books cover
    the market."""
    expect_n = _expect_outcome_count(market_key, by_outcome)
    three_way = expect_n == 3
    buckets = _buckets(market_key, list(by_outcome.keys()))

    def _gather(books_set: frozenset[str] | set[str] | None):
        per_outcome: dict[tuple[str, float | None], list[float]] = defaultdict(list)
        contributing_books: set[str] = set()
        for _bucket, keys in buckets.items():
            if len(keys) != expect_n:
                continue
            # Find books that post every outcome in this bucket (non-stale).
            book_sides: dict[str, list[tuple[tuple[str, float | None], int]]] = defaultdict(list)
            for k in keys:
                for bk, pr in by_outcome[k].items():
                    if books_set is not None and bk not in books_set:
                        continue
                    if _stale(pr, now, stale_seconds):
                        continue
                    book_sides[bk].append((k, int(pr["price_american"])))
            for bk, entries in book_sides.items():
                if len(entries) != expect_n:
                    continue
                # Preserve bucket's key order.
                by_k = dict(entries)
                prices = [by_k[k] for k in keys]
                if three_way:
                    fair = devig_n_way(prices)
                else:
                    fp1, fp2 = devig_two_way(prices[0], prices[1])
                    fair = [fp1, fp2]
                for k, fp in zip(keys, fair):
                    per_outcome[k].append(fp)
                contributing_books.add(bk)
        return per_outcome, contributing_books

    per_outcome, books = _gather(sharp_books)
    if len(books) < 2:
        per_outcome, books = _gather(None)
        if len(books) < 2:
            return None

    probs = {k: median(vs) for k, vs in per_outcome.items() if vs}
    if not probs:
        return None
    return probs, len(books)


def _kelly_full(ev_frac: float, decimal_odds: float) -> float:
    """Kelly fraction for given edge (as fraction, not %) and decimal odds.
    Returns fraction of bankroll to bet. Clips negatives to 0."""
    denom = decimal_odds - 1.0
    if denom <= 0:
        return 0.0
    return max(0.0, ev_frac / denom)


def _two_way_pair_ev_rows(
    game: dict,
    market_kind: str,
    point_for_display: float | None,
    side_a: dict,
    side_b: dict,
    now: datetime,
    books_filter: set[str] | None,
    sharp_books: frozenset[str],
    min_ev_pct: float,
    max_longshot_american: int,
    stale_seconds: float,
    arb_keys: set[tuple] | None,
) -> list[dict]:
    """Emit EV rows for a single complementary 2-way pair (spreads or totals).
    Handles both orientations of spreads correctly by construction — the pair
    comes from `collect_spread_pairs` which guarantees complementary signed
    points.
    """
    a_by_book = _prices_by_book(side_a)
    b_by_book = _prices_by_book(side_b)

    # Pinnacle no-vig first
    source: str | None = None
    anchor_count = 0
    fair_a: float | None = None
    fair_b: float | None = None
    pin_a = a_by_book.get("pinnacle")
    pin_b = b_by_book.get("pinnacle")
    if (
        pin_a and pin_b
        and not _stale(pin_a, now, stale_seconds)
        and not _stale(pin_b, now, stale_seconds)
    ):
        fair_a, fair_b = devig_two_way(
            int(pin_a["price_american"]), int(pin_b["price_american"]),
        )
        source = "pinnacle"
        anchor_count = 1
    else:
        # Consensus: per-book devig (sharp first, then all)
        for candidate in (sharp_books, None):
            fa_vals: list[float] = []
            fb_vals: list[float] = []
            used: set[str] = set()
            for bk, pa in a_by_book.items():
                if candidate is not None and bk not in candidate:
                    continue
                if _stale(pa, now, stale_seconds):
                    continue
                pb = b_by_book.get(bk)
                if pb is None or _stale(pb, now, stale_seconds):
                    continue
                fa, fb = devig_two_way(
                    int(pa["price_american"]), int(pb["price_american"]),
                )
                fa_vals.append(fa)
                fb_vals.append(fb)
                used.add(bk)
            if len(used) >= 2:
                fair_a = median(fa_vals)
                fair_b = median(fb_vals)
                source = "consensus"
                anchor_count = len(used)
                break
        if fair_a is None or fair_b is None:
            return []

    ops: list[dict] = []
    for side_outcome, side_prices, p_true in (
        (side_a, a_by_book, fair_a),
        (side_b, b_by_book, fair_b),
    ):
        if p_true <= 0.0 or p_true >= 1.0:
            continue
        for book, price in side_prices.items():
            if _stale(price, now, stale_seconds):
                continue
            if source == "pinnacle" and book == "pinnacle":
                continue
            if books_filter is not None and book not in books_filter:
                continue
            american = int(price["price_american"])
            if american > max_longshot_american:
                continue
            dec = american_to_decimal(american)
            ev_frac = p_true * (dec - 1.0) - (1.0 - p_true)
            if ev_frac * 100.0 < min_ev_pct:
                continue
            kelly_full_frac = _kelly_full(ev_frac, dec)
            confidence = "low" if ev_frac > HIGH_EV_CONFIDENCE_CUTOFF else "normal"

            # also_in_arb lookup
            also_in_arb = False
            if arb_keys is not None:
                arb_market = _canonical_arb_market(market_kind)
                if arb_market == "spreads":
                    arb_pt = (
                        None if point_for_display is None
                        else round(abs(point_for_display), 1)
                    )
                elif arb_market == "totals":
                    arb_pt = (
                        None if point_for_display is None
                        else round(point_for_display, 1)
                    )
                else:
                    arb_pt = None
                also_in_arb = (game["event_id"], arb_market, arb_pt) in arb_keys

            # Signed point for display comes from the outcome's own prices.
            outcome_point = None
            if side_outcome.get("prices") and side_outcome["prices"][0].get("point") is not None:
                outcome_point = side_outcome["prices"][0]["point"]

            ops.append({
                "sport_key": game.get("sport_key", "mlb"),
                "event_id": game["event_id"],
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "commence_time": game["commence_time"],
                "market_kind": market_kind,
                "point": outcome_point,
                "outcome_name": side_outcome["outcome_name"],
                "book": book,
                "offered_price_american": american,
                "fair_price_american": implied_to_american(p_true),
                "fair_probability": p_true,
                "ev_pct": ev_frac * 100.0,
                "kelly_full_pct": kelly_full_frac * 100.0,
                "kelly_quarter_pct": kelly_full_frac * 25.0,
                "source": source,
                "anchor_book_count": anchor_count,
                "offered_age_s": int(_age_seconds(price, now)),
                "also_in_arb": also_in_arb,
                "confidence": confidence,
                "wager_type": price.get("wager_type"),
            })
    return ops


def scan_game_ev(
    game: dict,
    now: datetime,
    books_filter: set[str] | None,
    sharp_books: frozenset[str],
    min_ev_pct: float,
    max_longshot_american: int,
    stale_seconds: float,
    arb_keys: set[tuple] | None,
) -> list[dict]:
    ops: list[dict] = []

    # --- Spreads / totals via shared pairing helper (handles main + alt +
    # period variants). Generic bucket logic can't safely handle alt_spreads
    # because it doesn't enforce complementary signed points.
    spread_suffixes: set[str] = set()
    total_suffixes: set[str] = set()
    for m in game.get("markets") or []:
        mk = m.get("market_key", "")
        base = _base_market(mk)
        suffix = _period_suffix(mk)
        if base in ("spreads", "alternate_spreads"):
            spread_suffixes.add(suffix)
        elif base in ("totals", "alternate_totals"):
            total_suffixes.add(suffix)

    handled_markets: set[str] = set()

    for suffix in spread_suffixes:
        main_mk = f"spreads{suffix}"
        alt_mk = f"alternate_spreads{suffix}"
        market_keys = (main_mk, alt_mk)
        for abs_pt, home_side, away_side in collect_spread_pairs(
            game, market_keys=market_keys,
        ):
            ops.extend(_two_way_pair_ev_rows(
                game, main_mk, abs_pt, home_side, away_side,
                now=now, books_filter=books_filter, sharp_books=sharp_books,
                min_ev_pct=min_ev_pct,
                max_longshot_american=max_longshot_american,
                stale_seconds=stale_seconds, arb_keys=arb_keys,
            ))
        handled_markets.add(main_mk)
        handled_markets.add(alt_mk)

    for suffix in total_suffixes:
        main_mk = f"totals{suffix}"
        alt_mk = f"alternate_totals{suffix}"
        market_keys = (main_mk, alt_mk)
        for pt, over_side, under_side in collect_total_pairs(
            game, market_keys=market_keys,
        ):
            ops.extend(_two_way_pair_ev_rows(
                game, main_mk, pt, over_side, under_side,
                now=now, books_filter=books_filter, sharp_books=sharp_books,
                min_ev_pct=min_ev_pct,
                max_longshot_american=max_longshot_american,
                stale_seconds=stale_seconds, arb_keys=arb_keys,
            ))
        handled_markets.add(main_mk)
        handled_markets.add(alt_mk)

    # --- Generic path for h2h, team_totals, player props, and any period
    # variants of those. Now also handles 3-way markets — soccer h2h
    # (home/draw/away) goes through here, and `_pinnacle_fair` /
    # `_consensus_fair` infer expect_n=3 dynamically when a "Draw" outcome
    # is present (or when the key is in THREE_WAY_BASES).
    for market in game.get("markets") or []:
        market_key = market.get("market_key")
        if not market_key or market_key in handled_markets:
            continue

        by_outcome = _collect_market_outcomes(market)
        if not by_outcome:
            continue

        source = "pinnacle"
        anchor_count = 1
        fair = _pinnacle_fair(by_outcome, market_key, now, stale_seconds)
        if fair is None:
            res = _consensus_fair(
                by_outcome, market_key, now, stale_seconds, sharp_books,
            )
            if res is None:
                continue
            fair, anchor_count = res
            source = "consensus"

        for out_key, books_prices in by_outcome.items():
            p_true = fair.get(out_key)
            if p_true is None or p_true <= 0.0 or p_true >= 1.0:
                continue
            for book, price in books_prices.items():
                if _stale(price, now, stale_seconds):
                    continue
                if source == "pinnacle" and book == "pinnacle":
                    # Don't emit "Pinnacle +X%" — that's the anchor.
                    continue
                if books_filter is not None and book not in books_filter:
                    continue
                american = int(price["price_american"])
                if american > max_longshot_american:
                    continue
                dec = american_to_decimal(american)
                ev_frac = p_true * (dec - 1.0) - (1.0 - p_true)
                if ev_frac * 100.0 < min_ev_pct:
                    continue
                kelly_full_frac = _kelly_full(ev_frac, dec)
                confidence = "low" if ev_frac > HIGH_EV_CONFIDENCE_CUTOFF else "normal"

                point = out_key[1]
                also_in_arb = False
                if arb_keys is not None:
                    arb_market = _canonical_arb_market(market_key)
                    if arb_market == "spreads":
                        arb_pt = None if point is None else round(abs(point), 1)
                    elif arb_market == "totals":
                        arb_pt = None if point is None else round(point, 1)
                    else:
                        arb_pt = None
                    also_in_arb = (game["event_id"], arb_market, arb_pt) in arb_keys

                ops.append({
                    "sport_key": game.get("sport_key", "mlb"),
                    "event_id": game["event_id"],
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "commence_time": game["commence_time"],
                    "market_kind": market_key,
                    "point": point,
                    "outcome_name": out_key[0],
                    "book": book,
                    "offered_price_american": american,
                    "fair_price_american": implied_to_american(p_true),
                    "fair_probability": p_true,
                    "ev_pct": ev_frac * 100.0,
                    "kelly_full_pct": kelly_full_frac * 100.0,
                    "kelly_quarter_pct": kelly_full_frac * 25.0,
                    "source": source,
                    "anchor_book_count": anchor_count,
                    "offered_age_s": int(_age_seconds(price, now)),
                    "also_in_arb": also_in_arb,
                    "confidence": confidence,
                    "wager_type": price.get("wager_type"),
                })
    return ops


def _canonical_arb_market(market_key: str) -> str:
    """Arbitrage scanner collapses alternate_* into the main market_kind when
    emitting. Mirror that for the also_in_arb tag."""
    if market_key in ("spreads", "alternate_spreads"):
        return "spreads"
    if market_key in ("totals", "alternate_totals"):
        return "totals"
    return market_key


def scan_all_ev(
    games: list[dict],
    now: datetime,
    books_filter: set[str] | None = None,
    sharp_books: frozenset[str] | None = None,
    min_ev_pct: float = 1.0,
    max_longshot_american: int = 800,
    stale_seconds: float = 60.0,
    arb_keys: set[tuple] | None = None,
    max_results: int | None = None,
    sort: str = "desc",
) -> list[dict]:
    """Entry point used by the API layer. Expects `games` to be the output
    of `rows_to_games` (so prices are already commission-adjusted).

    sort='desc' (default): best +EV first — use for finding plays to take.
    sort='asc': worst first — use with min_ev_pct < 0 to surface fade
                candidates (the cap would otherwise always prefer positives).
    sort='bidir': half most-positive, half most-negative — use when the
                user wants both tails in one response."""
    sharp = SHARP_BOOKS if sharp_books is None else frozenset(sharp_books)
    ops: list[dict] = []
    for g in games:
        ops.extend(scan_game_ev(
            g, now=now,
            books_filter=books_filter,
            sharp_books=sharp,
            min_ev_pct=min_ev_pct,
            max_longshot_american=max_longshot_american,
            stale_seconds=stale_seconds,
            arb_keys=arb_keys,
        ))
    if sort == "asc":
        ops.sort(key=lambda o: (o["ev_pct"], o["commence_time"]))
    elif sort == "bidir" and max_results is not None:
        # Half the cap from the top, half from the bottom.
        ops.sort(key=lambda o: (-o["ev_pct"], o["commence_time"]))
        half = max(1, max_results // 2)
        top = ops[:half]
        bottom = ops[-half:][::-1]  # reverse so worst-first
        # Dedupe in case the two halves overlap on a small dataset.
        seen = set()
        merged: list[dict] = []
        for o in top + bottom:
            key = id(o)
            if key in seen:
                continue
            seen.add(key)
            merged.append(o)
        ops = merged
        # Skip the max_results cap below — we've already sized.
        return ops
    else:
        ops.sort(key=lambda o: (-o["ev_pct"], o["commence_time"]))
    if max_results is not None and len(ops) > max_results:
        ops = ops[:max_results]
    return ops
