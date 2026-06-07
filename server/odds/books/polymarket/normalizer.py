"""Polymarket market → cache row normalizer.

Phase 2 — dispatches per parsed slug `kind`:
  - h2h           → US sports 2-way moneyline (2 rows / market)
  - spread        → alt-line ladder (2 rows / market)
  - total         → Over/Under ladder (2 rows / market)
  - player_prop   → NBA points O/U (2 rows / market — Over + Under from Yes/No)
  - soccer_3way   → 3 separate Y/N markets aggregated to 3 rows / event

The interesting per-market fields:
  - `outcomes`         : JSON string list of outcome labels
                         h2h:        team names    e.g. '["Spurs", "Thunder"]'
                         spread:     team names    e.g. '["Thunder", "Spurs"]'
                                                   [favored, underdog]
                         total:      O/U literals  e.g. '["Over", "Under"]'
                         3way:       Yes/No        e.g. '["Yes", "No"]'
                         player:     Yes/No
  - `bestAsk` / `bestBid`: top-of-book for the YES (first outcome) token.
                         Outcome prices are derived as
                         [bestAsk, 1 - bestBid] — the ASK each side
                         would pay to BUY. We don't read `outcomePrices`
                         because Gamma serializes that as the midpoint.
  - `clobTokenIds`     : JSON string list of CLOB asset_ids, parallel to outcomes
                         Each asset_id = one tradeable side. WS-side key.

Number encoding: `Npt5` = N.5 (decoded upstream by `slug_parser._decode_strike`).

The dispatcher is `normalize_events`. The soccer_3way path is special-cased:
each event has 3 separate binary markets (one per outcome) which we group
by event slug and emit as 3 rows once collected.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Callable

from .mapping import TEAM_CODE_TO_CANONICAL


logger = logging.getLogger(__name__)


BOOK_KEY = "polymarket"

# h2h / soccer 3-way / player-prop overround filter. Each outcome's
# outcomePrice is the implied probability; binary markets should sum to
# ≈1.00 with vig. >1.10 indicates stale / one-sided orderbook.
MAX_OVERROUND = 1.10

# Stricter ALT gate for spread/total ladder rungs. Many extreme strikes
# show price 0.98 / 0.02 — they sum near 1.0 but the off-side is no real
# offer. Drop strikes with either side below 1c.
MIN_OUTCOME_PROB = 0.01

# Spread / total ladders publish many rungs per event — accept higher
# overround on alts since the spread between yes_ask and no_ask is wider
# at the extreme strikes than at the mid.
MAX_OVERROUND_ALT = 1.15


POLYMARKET_TAKER_FEE = 0.05


def yes_to_american(p: float) -> int | None:
    """Convert a YES decimal price (0..1) to FEE-ADJUSTED American odds.

    Polymarket charges a 5% market-order (taker) fee per contract on the
    variance term `P * (1-P)`, so the true per-contract cost is
        cost = P + 0.05 * P * (1-P) = P * (1.05 - 0.05 * P)
    and realized profit on a winning contract is `1 - cost`. This
    function returns the American odds *implied by that effective cost*
    so EV/arb comparisons against bookmakers (whose vig is already
    embedded in the line) are apples-to-apples. Without the fee
    adjustment, the scanner surfaces phantom Polymarket edges that
    vanish at fill time.

    Verified empirically: 100 shares at yes_ask=0.69 → total cost
    $70.07, fee $1.07 — back-solves to F = 1.07 / (0.69*0.31*100) =
    0.0500. Second sample at yes_ask=0.58 → fee $1.22 → also 0.0500.

    Rounding is `math.floor` of the raw American value, which for both
    signs rounds *against the bettor* (favorites one notch more
    negative, underdogs one notch less positive) — matches the same
    conservative rounding the Kalshi normalizer uses.
    """
    if p <= 0 or p >= 1:
        return None
    cost = p + POLYMARKET_TAKER_FEE * p * (1 - p)
    profit = 1.0 - cost
    if profit <= 0:
        return None
    if cost > profit:
        return math.floor(-cost / profit * 100)
    return math.floor(profit / cost * 100)


def _parse_json_array(s) -> list | None:
    """Polymarket serializes outcomes/outcomePrices/clobTokenIds as JSON
    strings (not real arrays). Defensive parse — return None if anything
    weird."""
    if s is None:
        return None
    if isinstance(s, list):
        return s
    if not isinstance(s, str):
        return None
    try:
        parsed = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _noon_et_anchor(date_str: str) -> datetime | None:
    """Convert a `YYYY-MM-DD` slug date into noon-ET-as-UTC. The matcher
    uses a 12h window around this anchor so any same-day game on the
    cache side matches."""
    try:
        y, m, d = date_str.split("-")
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/New_York")
        except Exception:
            from datetime import timedelta as _td
            tz = timezone(-_td(hours=4))
        local = datetime(int(y), int(m), int(d), 12, 0, tzinfo=tz)
        return local.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _binary_market_passes_quality(
    prob_a: float | None,
    prob_b: float | None,
    *,
    max_overround: float = MAX_OVERROUND,
) -> bool:
    """Generic 2-outcome quality gate. Rejects:
      - non-finite prices
      - either side below MIN_OUTCOME_PROB (no real opposing offer)
      - either side >= 1.0 (impossible — would be a resolved market)
      - prob_a + prob_b > max_overround (stale book)
    """
    if prob_a is None or prob_b is None:
        return False
    if prob_a < MIN_OUTCOME_PROB or prob_b < MIN_OUTCOME_PROB:
        return False
    if prob_a >= 1.0 or prob_b >= 1.0:
        return False
    if (prob_a + prob_b) > max_overround:
        return False
    return True


# Backwards-compat alias for Phase 1 callers.
def _market_passes_quality(prob_a, prob_b) -> bool:
    return _binary_market_passes_quality(prob_a, prob_b)


def _extract_two_sided(market: dict) -> tuple[list[str], list[float], list[str]] | None:
    """Pull and validate the parallel outcome/price/token arrays from a
    Polymarket market dict. Returns (labels, prices, tokens) or None on
    any structural failure (mismatched lengths, count != 2, malformed
    prices, etc.).

    Prices are derived from the orderbook tops, NOT from `outcomePrices`
    (which Gamma exposes as the midpoint between bid and ask). A bettor
    buys at the ask, so:
      - outcome[0] (YES side) price = bestAsk
      - outcome[1] (NO side)  price = 1 - bestBid
    Complementary because the NO token's ask = 1 - the YES token's bid
    in an arbitrage-free binary market.
    """
    outcomes = _parse_json_array(market.get("outcomes"))
    tokens   = _parse_json_array(market.get("clobTokenIds"))
    if not outcomes or not tokens:
        return None
    if not (len(outcomes) == len(tokens) == 2):
        return None
    try:
        best_ask = float(market.get("bestAsk"))
        best_bid = float(market.get("bestBid"))
    except (TypeError, ValueError):
        return None
    if not (0 < best_ask < 1) or not (0 < best_bid < 1):
        return None
    if best_ask < best_bid:
        return None
    parsed_prices = [best_ask, 1.0 - best_bid]
    return (
        [str(o) for o in outcomes],
        parsed_prices,
        [str(t) for t in tokens],
    )


def _resolve_event_canon(
    parsed_slug: dict,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> tuple[dict, str, str, datetime] | None:
    """Shared event-resolution helper.

    Returns (matched_event_view, canon_a, canon_b, real_commence_time) or
    None on any failure (unknown team codes, no cache match, live/past).

    `canon_a` / `canon_b` correspond to the slug's team_a_code / team_b_code
    respectively — NOT to the cache's home/away orientation. Callers that
    need home/away should read `matched_event_view['home_team']` /
    `['away_team']` separately.
    """
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    code_a = parsed_slug["team_a_code"]
    code_b = parsed_slug["team_b_code"]
    canon_a = code_map.get(code_a)
    canon_b = code_map.get(code_b)
    if not canon_a or not canon_b:
        return None
    anchor = _noon_et_anchor(parsed_slug["date"])
    if anchor is None:
        return None
    matched = match_event(sport_key, canon_a, canon_b, anchor)
    if matched is None:
        return None
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    real_commence = matched["commence_time"]
    if real_commence <= now:
        return None
    return matched, canon_a, canon_b, real_commence


# ──────────────────────────────────────────────────────────────────────
# h2h (US sports 2-way moneyline)
# ──────────────────────────────────────────────────────────────────────


def normalize_h2h_market(
    market: dict,
    parsed_slug: dict,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Convert one Polymarket h2h market into 2 cache rows."""
    resolved = _resolve_event_canon(parsed_slug, sport_key, fetched_at, match_event)
    if resolved is None:
        return []
    matched, canon_a, canon_b, real_commence = resolved

    extracted = _extract_two_sided(market)
    if extracted is None:
        return []
    _labels, prices, tokens = extracted
    p_a, p_b = prices[0], prices[1]
    if not _binary_market_passes_quality(p_a, p_b):
        return []
    am_a = yes_to_american(p_a)
    am_b = yes_to_american(p_b)
    if am_a is None or am_b is None:
        return []

    base = {
        "event_id":      matched["event_id"],
        "sport_key":     sport_key,
        "home_team":     matched["home_team"],
        "away_team":     matched["away_team"],
        "commence_time": real_commence,
        "bookmaker_key": BOOK_KEY,
        "market_key":    "h2h",
        "outcome_point": None,
        "fetched_at":    fetched_at,
    }
    return [
        {
            **base, "outcome_name": canon_a, "price_american": am_a,
            "_asset_id": tokens[0], "_ws_side": "yes",
        },
        {
            **base, "outcome_name": canon_b, "price_american": am_b,
            "_asset_id": tokens[1], "_ws_side": "yes",
        },
    ]


# ──────────────────────────────────────────────────────────────────────
# Spread (alt-line ladder)
# ──────────────────────────────────────────────────────────────────────


def normalize_spread_market(
    market: dict,
    parsed_slug: dict,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """One Polymarket spread market → 2 cache rows.

    Slug details:
      - `spread-home-Npt5`  → team_b (slug second) is favored, -N.5
      - `spread-away-Npt5`  → team_a (slug first)  is favored, -N.5

    The `outcomes` array lists [favored_team_name, underdog_team_name];
    indices map 1-to-1 with the favored/underdog assignment derived
    from the slug.

    Emit:
      favored_canonical row:   outcome_point = -strike, price from outcomes[0]
      underdog_canonical row:  outcome_point = +strike, price from outcomes[1]
    """
    resolved = _resolve_event_canon(parsed_slug, sport_key, fetched_at, match_event)
    if resolved is None:
        return []
    matched, canon_a, canon_b, real_commence = resolved

    strike = parsed_slug.get("strike")
    if strike is None:
        return []
    side = parsed_slug.get("details") or ""
    # Slug convention:
    #   home → team_b (second in slug) is favored
    #   away → team_a (first in slug)  is favored
    if side == "home":
        favored_canon, underdog_canon = canon_b, canon_a
    elif side == "away":
        favored_canon, underdog_canon = canon_a, canon_b
    else:
        return []

    extracted = _extract_two_sided(market)
    if extracted is None:
        return []
    _labels, prices, tokens = extracted
    p_fav, p_dog = prices[0], prices[1]
    # ALT gate: wider overround tolerance, but still need both sides priced.
    if not _binary_market_passes_quality(p_fav, p_dog, max_overround=MAX_OVERROUND_ALT):
        return []
    am_fav = yes_to_american(p_fav)
    am_dog = yes_to_american(p_dog)
    if am_fav is None or am_dog is None:
        return []

    base = {
        "event_id":      matched["event_id"],
        "sport_key":     sport_key,
        "home_team":     matched["home_team"],
        "away_team":     matched["away_team"],
        "commence_time": real_commence,
        "bookmaker_key": BOOK_KEY,
        "market_key":    "alternate_spreads",
        "fetched_at":    fetched_at,
    }
    return [
        {
            **base, "outcome_name": favored_canon, "outcome_point": -float(strike),
            "price_american": am_fav,
            "_asset_id": tokens[0], "_ws_side": "yes",
        },
        {
            **base, "outcome_name": underdog_canon, "outcome_point": float(strike),
            "price_american": am_dog,
            "_asset_id": tokens[1], "_ws_side": "yes",
        },
    ]


# ──────────────────────────────────────────────────────────────────────
# Total (Over/Under)
# ──────────────────────────────────────────────────────────────────────


def normalize_total_market(
    market: dict,
    parsed_slug: dict,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """One Polymarket total market → 2 cache rows.

    Outcomes array is ["Over", "Under"]; emit:
      - outcome_name="Over",  outcome_point=strike, price from outcomes[0]
      - outcome_name="Under", outcome_point=strike, price from outcomes[1]
    """
    resolved = _resolve_event_canon(parsed_slug, sport_key, fetched_at, match_event)
    if resolved is None:
        return []
    matched, _canon_a, _canon_b, real_commence = resolved

    strike = parsed_slug.get("strike")
    if strike is None:
        return []

    extracted = _extract_two_sided(market)
    if extracted is None:
        return []
    _labels, prices, tokens = extracted
    p_over, p_under = prices[0], prices[1]
    if not _binary_market_passes_quality(p_over, p_under, max_overround=MAX_OVERROUND_ALT):
        return []
    am_over = yes_to_american(p_over)
    am_under = yes_to_american(p_under)
    if am_over is None or am_under is None:
        return []

    base = {
        "event_id":      matched["event_id"],
        "sport_key":     sport_key,
        "home_team":     matched["home_team"],
        "away_team":     matched["away_team"],
        "commence_time": real_commence,
        "bookmaker_key": BOOK_KEY,
        "market_key":    "alternate_totals",
        "fetched_at":    fetched_at,
    }
    return [
        {
            **base, "outcome_name": "Over",  "outcome_point": float(strike),
            "price_american": am_over,
            "_asset_id": tokens[0], "_ws_side": "yes",
        },
        {
            **base, "outcome_name": "Under", "outcome_point": float(strike),
            "price_american": am_under,
            "_asset_id": tokens[1], "_ws_side": "yes",
        },
    ]


# ──────────────────────────────────────────────────────────────────────
# Player prop (NBA points O/U)
# ──────────────────────────────────────────────────────────────────────

# Polymarket strips apostrophes / punctuation from player names in the
# slug ("De'Aaron Fox" → "deaaron-fox", "Victor Wembanyama" →
# "victor-wembanyama"). Reverse via title-case + hyphen→space; the
# resulting canonical loses the apostrophe ("Deaaron Fox") but stays
# consistent with how Polymarket itself emits the name. Downstream
# joins to Coral33 props key on (sport, market_key, strike, player) —
# small case/punct deltas are handled by the prop-matching layer.

_PLAYER_NAME_OVERRIDES: dict[str, str] = {
    # Reactive overrides — extend when joins to Coral33 / Odds API surface
    # player-name drift. Key = slug player segment (lowercase, hyphenated).
    "deaaron-fox":       "De'Aaron Fox",
    "jaren-jackson-jr":  "Jaren Jackson Jr.",
    "shai-gilgeous-alexander": "Shai Gilgeous-Alexander",
    "karl-anthony-towns": "Karl-Anthony Towns",
}


def _decode_player_name(player_slug: str) -> str | None:
    """Convert a hyphenated slug segment to a display name.

    `victor-wembanyama` → "Victor Wembanyama"
    `deaaron-fox`        → "De'Aaron Fox" (via override)

    Returns None on empty input.
    """
    if not player_slug:
        return None
    if player_slug in _PLAYER_NAME_OVERRIDES:
        return _PLAYER_NAME_OVERRIDES[player_slug]
    parts = player_slug.split("-")
    titled = [p.capitalize() for p in parts if p]
    return " ".join(titled) if titled else None


def normalize_player_prop_market(
    market: dict,
    parsed_slug: dict,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """One Polymarket player-points prop → 2 cache rows.

    Outcomes array is ["Yes", "No"]. Yes = Over strike; No = Under.

      - outcome_name="<Player> Over",  outcome_point=strike, price from Yes
      - outcome_name="<Player> Under", outcome_point=strike, price from No

    Matches Coral33 / Odds API player-prop convention (see
    server/odds/books/coral33/normalizer.py for the reference shape).
    """
    resolved = _resolve_event_canon(parsed_slug, sport_key, fetched_at, match_event)
    if resolved is None:
        return []
    matched, _canon_a, _canon_b, real_commence = resolved

    strike = parsed_slug.get("strike")
    player_slug = parsed_slug.get("details") or ""
    if strike is None or not player_slug:
        return []
    player = _decode_player_name(player_slug)
    if not player:
        return []

    extracted = _extract_two_sided(market)
    if extracted is None:
        return []
    _labels, prices, tokens = extracted
    p_yes, p_no = prices[0], prices[1]
    if not _binary_market_passes_quality(p_yes, p_no, max_overround=MAX_OVERROUND_ALT):
        return []
    am_yes = yes_to_american(p_yes)
    am_no = yes_to_american(p_no)
    if am_yes is None or am_no is None:
        return []

    base = {
        "event_id":      matched["event_id"],
        "sport_key":     sport_key,
        "home_team":     matched["home_team"],
        "away_team":     matched["away_team"],
        "commence_time": real_commence,
        "bookmaker_key": BOOK_KEY,
        "market_key":    "player_points",
        "fetched_at":    fetched_at,
    }
    return [
        {
            **base, "outcome_name": f"{player} Over",  "outcome_point": float(strike),
            "price_american": am_yes,
            "_asset_id": tokens[0], "_ws_side": "yes",
        },
        {
            **base, "outcome_name": f"{player} Under", "outcome_point": float(strike),
            "price_american": am_no,
            "_asset_id": tokens[1], "_ws_side": "yes",
        },
    ]


# ──────────────────────────────────────────────────────────────────────
# Soccer 3-way (event-level aggregation)
# ──────────────────────────────────────────────────────────────────────


def _normalize_soccer_3way_event(
    parsed_markets: list[tuple[dict, dict]],
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Aggregate the 3 binary Y/N markets for one soccer event into 3
    cache rows.

    Args:
      parsed_markets: list of (market_dict, parsed_slug) tuples. Each
                      parsed_slug has kind=="soccer_3way" and `details`
                      ∈ {team_a_code, team_b_code, "draw"}.

    Emits one cache row per outcome, all market_key="h2h" matching the
    Coral33 + Odds API convention (3-way soccer h2h is keyed as plain
    `h2h`, not `h2h_3_way`). Each row uses the YES side's price + asset_id.

    Returns [] if:
      - fewer than ALL 3 outcomes are present (incomplete set)
      - event resolution fails (unknown codes / no cache match / past)
      - any market fails quality
    """
    if not parsed_markets:
        return []

    # All parsed_slug objects share team_a/team_b/date — pick the first
    # to derive the event canonicals.
    head_parsed = parsed_markets[0][1]
    resolved = _resolve_event_canon(head_parsed, sport_key, fetched_at, match_event)
    if resolved is None:
        return []
    matched, canon_a, canon_b, real_commence = resolved

    code_a = head_parsed["team_a_code"]
    code_b = head_parsed["team_b_code"]

    # Index markets by their `details` segment.
    by_segment: dict[str, dict] = {}
    for market, parsed in parsed_markets:
        seg = parsed.get("details")
        if seg in (code_a, code_b, "draw") and seg not in by_segment:
            by_segment[seg] = market

    # Require ALL three legs — a partial 3-way set is unusable for
    # cross-book aggregation (we'd be left with a 2-way book on a 3-way
    # market). Defer until next REST cycle when all 3 land.
    if not (code_a in by_segment and code_b in by_segment and "draw" in by_segment):
        return []

    base = {
        "event_id":      matched["event_id"],
        "sport_key":     sport_key,
        "home_team":     matched["home_team"],
        "away_team":     matched["away_team"],
        "commence_time": real_commence,
        "bookmaker_key": BOOK_KEY,
        "market_key":    "h2h",
        "outcome_point": None,
        "fetched_at":    fetched_at,
    }

    rows: list[dict] = []
    segment_to_outcome: list[tuple[str, str]] = [
        (code_a, canon_a),
        (code_b, canon_b),
        ("draw", "Draw"),
    ]
    yes_probs: list[float] = []
    for segment, outcome_name in segment_to_outcome:
        market = by_segment[segment]
        extracted = _extract_two_sided(market)
        if extracted is None:
            return []
        labels, prices, tokens = extracted
        # Each binary market: outcomes = ["Yes", "No"], prices parallel.
        # If labels are reversed (defensive), find the Yes index.
        yes_idx = 0
        if labels[0].strip().lower() != "yes":
            if labels[1].strip().lower() == "yes":
                yes_idx = 1
            else:
                return []
        p_yes = prices[yes_idx]
        token_yes = tokens[yes_idx]
        if p_yes <= 0 or p_yes >= 1:
            return []
        am = yes_to_american(p_yes)
        if am is None:
            return []
        yes_probs.append(p_yes)
        rows.append({
            **base,
            "outcome_name":   outcome_name,
            "price_american": am,
            "_asset_id":      token_yes,
            "_ws_side":       "yes",
        })

    # 3-way overround check: sum of 3 YES probs should be ~1.0 + small vig.
    # Use the same MAX_OVERROUND as binary markets — bookmakers don't
    # widen vig much on 3-way.
    if sum(yes_probs) > MAX_OVERROUND:
        return []

    return rows


# ──────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────


def _matches_any_prefix(slug: str, prefixes: list[str]) -> bool:
    """True if the slug starts with `<prefix>-` for any configured prefix."""
    for p in prefixes:
        if slug.startswith(p + "-"):
            return True
    return False


def normalize_events(
    events: list[dict],
    sport_key: str,
    slug_prefix=None,
    fetched_at: datetime = None,
    match_event: Callable[..., dict | None] = None,
    slug_prefixes: list[str] | None = None,
) -> list[dict]:
    """Top-level entry: walk every Polymarket sports event, parse each
    market's slug, dispatch on `kind`, and emit cache rows.

    Args:
      events: raw Gamma /events response
      sport_key: our internal key ("nba", "mlb", "nhl", "wnba", "soccer")
      slug_prefix: legacy single-prefix arg (Phase 1 callers). When set,
                   used as the only prefix to filter on.
      slug_prefixes: Phase 2 multi-prefix form. For soccer, this is
                   ["epl", "laliga", ...]. Either this OR slug_prefix
                   must be supplied — slug_prefixes wins if both.
      fetched_at: UTC timestamp stamped on each row.
      match_event: callable from PolymarketEventMatcher.match.

    Returns a flat list of cache rows ready for `cache.upsert`.
    """
    from .slug_parser import parse_slug

    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc)
    if slug_prefixes is None:
        slug_prefixes = [slug_prefix] if slug_prefix else [sport_key]

    rows: list[dict] = []
    matched_count = 0
    orphan_count = 0
    parse_skip = 0
    quality_skip = 0
    spread_rows = 0
    total_rows = 0
    pp_rows = 0
    soccer_3way_events = 0

    # Phase 2 grouping for soccer 3-way: collect partials, emit after the
    # per-market walk completes.
    soccer_3way_partial: dict[str, list[tuple[dict, dict]]] = {}

    for ev in events:
        ev_slug = ev.get("slug") or ""
        if not _matches_any_prefix(ev_slug, slug_prefixes):
            continue
        for market in (ev.get("markets") or []):
            m_slug = market.get("slug") or ""
            parsed = parse_slug(m_slug)
            if parsed is None:
                parse_skip += 1
                continue
            if parsed["sport_prefix"] not in slug_prefixes:
                # Defensive: market under a sports-tagged event with a
                # different sport prefix (cross-sport parlay events).
                continue

            kind = parsed["kind"]
            market_rows: list[dict] = []

            if kind == "h2h":
                # Soccer h2h is 3-way; non-soccer is the 2-way path.
                if sport_key == "soccer":
                    # Polymarket doesn't publish a 2-way h2h for soccer
                    # (only the 3 separate Y/N legs which parse as
                    # soccer_3way). If we ever see a bare-h2h soccer
                    # slug it's unsupported — skip.
                    continue
                market_rows = normalize_h2h_market(
                    market, parsed, sport_key, fetched_at, match_event,
                )
            elif kind == "spread":
                market_rows = normalize_spread_market(
                    market, parsed, sport_key, fetched_at, match_event,
                )
                if market_rows:
                    spread_rows += len(market_rows)
            elif kind == "total":
                market_rows = normalize_total_market(
                    market, parsed, sport_key, fetched_at, match_event,
                )
                if market_rows:
                    total_rows += len(market_rows)
            elif kind == "player_prop":
                # Player props only for NBA in Phase 2.
                if sport_key != "nba":
                    continue
                market_rows = normalize_player_prop_market(
                    market, parsed, sport_key, fetched_at, match_event,
                )
                if market_rows:
                    pp_rows += len(market_rows)
            elif kind == "soccer_3way":
                # Defer to event-level aggregation; use the parent event's
                # slug (not the market slug) as the grouping key.
                if sport_key != "soccer":
                    continue
                soccer_3way_partial.setdefault(ev_slug, []).append((market, parsed))
                continue
            else:
                # Unknown kind — defensive.
                continue

            if not market_rows:
                # Distinguish quality-skipped from orphan via outcomes presence.
                if market.get("outcomes") and market.get("clobTokenIds"):
                    orphan_count += 1
                else:
                    quality_skip += 1
                continue
            matched_count += 1
            rows.extend(market_rows)

    # Process soccer 3-way partials.
    for ev_slug, parsed_markets in soccer_3way_partial.items():
        event_rows = _normalize_soccer_3way_event(
            parsed_markets, sport_key, fetched_at, match_event,
        )
        if event_rows:
            soccer_3way_events += 1
            rows.extend(event_rows)
        else:
            # Either incomplete (not all 3 legs), or no matching cache event.
            orphan_count += 1

    if matched_count or orphan_count or parse_skip or quality_skip or soccer_3way_events:
        logger.info(
            "polymarket %s: %d rows (h2h_matches=%d, spread=%d, total=%d, "
            "player_prop=%d, soccer_3way_events=%d; %d orphans, "
            "%d non-parsable skipped, %d quality-skipped)",
            sport_key, len(rows), matched_count, spread_rows, total_rows,
            pp_rows, soccer_3way_events,
            orphan_count, parse_skip, quality_skip,
        )
    return rows
