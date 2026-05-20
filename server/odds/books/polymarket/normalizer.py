"""Polymarket market → cache row normalizer.

Phase 1: h2h moneyline only. One Polymarket market → 2 cache rows, one
per team outcome.

The interesting per-market fields (parsed in `normalize_h2h_market`):
  - `outcomes`         : JSON string list of 2 outcome labels (team names)
                         e.g. '["Spurs", "Thunder"]'
  - `outcomePrices`    : JSON string list of 2 implied probabilities,
                         parallel to outcomes. e.g. '["0.315", "0.685"]'
  - `clobTokenIds`     : JSON string list of 2 CLOB asset_ids, parallel
                         to outcomes. Each asset_id = one tradeable side.
                         These are the IDs we subscribe to over WS.

Phase 2 will add: spreads, totals, team_totals, 3-way soccer h2h, player
props. The slug-parser already rejects all those upstream, so this file
only ever sees clean h2h markets.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from .mapping import TEAM_CODE_TO_CANONICAL


logger = logging.getLogger(__name__)


BOOK_KEY = "polymarket"

# Polymarket h2h overround filter. Each side's outcomePrice is the implied
# probability for THAT outcome; the two sides should sum to ≈ 1.00 with a
# tiny vig (Polymarket's spread is 1-2c). >1.10 indicates a stale orderbook
# or a market that's resolved-but-still-listed — drop.
MAX_OVERROUND = 1.10

# Min per-outcome probability. Anything below 1c on a moneyline implies
# the orderbook is one-sided (no real opposing offer). Reject — matches
# Kalshi's ALT_MIN_ASK gate.
MIN_OUTCOME_PROB = 0.01


def yes_to_american(p: float) -> int | None:
    """Convert a YES decimal price (0..1) to American odds.

    Polymarket quotes implied probability per outcome (e.g. 0.315 = "Spurs
    win") directly. This is identical to Kalshi's yes_ask_dollars semantics:
      - underdog (p < 0.5): +odds = round((1-p)/p * 100)
      - favorite (p > 0.5): -odds = -round(p/(1-p) * 100)

    Verified: Spurs at 0.315 → +218, Thunder at 0.685 → -217.
    """
    if p <= 0 or p >= 1:
        return None
    if p < 0.5:
        return round((1 - p) / p * 100)
    if p > 0.5:
        return -round(p / (1 - p) * 100)
    return -100


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
        # Eastern Time (use system zoneinfo if available; otherwise approximate
        # via UTC-4 — EDT is correct April-November which is most of the
        # in-season window for the Phase 1 sports).
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


def _market_passes_quality(
    prob_a: float | None,
    prob_b: float | None,
) -> bool:
    """Reject markets with non-finite quotes, single-sided books, or
    extreme overround. Same intent as Kalshi's `_market_passes_quality`.
    """
    if prob_a is None or prob_b is None:
        return False
    if prob_a < MIN_OUTCOME_PROB or prob_b < MIN_OUTCOME_PROB:
        return False
    if prob_a >= 1.0 or prob_b >= 1.0:
        return False
    if (prob_a + prob_b) > MAX_OVERROUND:
        return False
    return True


def normalize_h2h_market(
    market: dict,
    parsed_slug: dict,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Convert one Polymarket h2h market into 2 cache rows.

    Returns [] on any of:
      - missing/malformed outcomes / outcomePrices / clobTokenIds
      - outcomes count != 2
      - team codes not in TEAM_CODE_TO_CANONICAL
      - market doesn't match any Odds API event in our cache
      - quality filter fails (extreme overround, dead book, etc.)
      - game has already started (commence_time <= now)

    Row shape per `cache.upsert` schema, with two WS bookkeeping extras
    (`_asset_id`, `_ws_side`) that pass through harmlessly. The asset_id
    is the index the ingestor uses to route incoming WS messages.
    """
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    code_a = parsed_slug["team_a_code"]
    code_b = parsed_slug["team_b_code"]
    canon_a = code_map.get(code_a)
    canon_b = code_map.get(code_b)
    if not canon_a or not canon_b:
        logger.debug(
            "polymarket: unknown team code(s) %s/%s for sport %s in slug %s",
            code_a, code_b, sport_key, market.get("slug"),
        )
        return []

    # Anchor to noon ET of the slug date; matcher uses a 12h window so
    # actual game-start time is captured. We override commence_time on
    # the row from the MATCHED Odds API event so `purge_live_rows_for_book`
    # decides live vs future on real game-start (not the noon anchor).
    anchor = _noon_et_anchor(parsed_slug["date"])
    if anchor is None:
        return []

    matched = match_event(sport_key, canon_a, canon_b, anchor)
    if matched is None:
        return []

    # Live-or-past skip — we have the real game-start from the matched event.
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    real_commence = matched["commence_time"]
    if real_commence <= now:
        return []

    outcomes = _parse_json_array(market.get("outcomes"))
    prices   = _parse_json_array(market.get("outcomePrices"))
    tokens   = _parse_json_array(market.get("clobTokenIds"))
    if not outcomes or not prices or not tokens:
        return []
    if not (len(outcomes) == len(prices) == len(tokens) == 2):
        # Phase 1 h2h is strictly 2-way. 3-way soccer is Phase 2.
        return []

    # Each outcome label is a short team name (e.g. "Spurs", "Thunder",
    # "Tampa Bay Rays"). We DON'T map labels back to codes — the codes
    # come from the slug, which is canonical. The label-to-canonical
    # association is by INDEX: outcomes[0] corresponds to team_a_code
    # (first in slug), outcomes[1] to team_b_code (second in slug).
    #
    # This invariant is what Polymarket's slug convention promises (and
    # what we verified on probed data: slug `nba-sas-okc-...` → outcomes
    # `["Spurs", "Thunder"]` in the same order).
    parallel_pairs: list[tuple[str, float | None, str]] = []
    for label, price_str, token in zip(outcomes, prices, tokens):
        try:
            p = float(price_str)
        except (TypeError, ValueError):
            p = None
        # Drop the label — we use canonicals from the slug/code map.
        parallel_pairs.append((str(label), p, str(token)))

    p_a = parallel_pairs[0][1]
    p_b = parallel_pairs[1][1]
    if not _market_passes_quality(p_a, p_b):
        return []

    am_a = yes_to_american(p_a) if p_a is not None else None
    am_b = yes_to_american(p_b) if p_b is not None else None
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

    rows = [
        {
            **base,
            "outcome_name":   canon_a,
            "price_american": am_a,
            "_asset_id":      parallel_pairs[0][2],
            "_ws_side":       "yes",
        },
        {
            **base,
            "outcome_name":   canon_b,
            "price_american": am_b,
            "_asset_id":      parallel_pairs[1][2],
            "_ws_side":       "yes",
        },
    ]
    return rows


def normalize_events(
    events: list[dict],
    sport_key: str,
    slug_prefix: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Top-level entry: walk every Polymarket sports event, find each
    event's h2h moneyline market (the one whose slug equals the event
    slug — no suffix), filter to those matching this sport's prefix, and
    normalize each into 2 cache rows.

    Skips events without an h2h market (Phase 2 alt-only events) and any
    market that fails parse / quality / matcher.

    Logging is per-sport counted so cycle health is observable.
    """
    from .slug_parser import parse_slug

    rows: list[dict] = []
    matched_count = 0
    orphan_count = 0
    parse_skip = 0
    quality_skip = 0

    for ev in events:
        ev_slug = ev.get("slug") or ""
        # Quick prefix filter — skip everything not in our sport before
        # doing per-market work.
        if not ev_slug.startswith(slug_prefix + "-"):
            continue
        for market in (ev.get("markets") or []):
            m_slug = market.get("slug") or ""
            parsed = parse_slug(m_slug)
            if parsed is None:
                # Not an h2h-shaped slug (alt market, prop, etc.) — Phase 2
                parse_skip += 1
                continue
            if parsed["sport_prefix"] != slug_prefix:
                # Defensive: market under a sports-tagged event with a
                # different sport prefix (cross-sport parlay events).
                continue
            if parsed["kind"] != "h2h":
                continue

            market_rows = normalize_h2h_market(
                market, parsed, sport_key, fetched_at, match_event,
            )
            if not market_rows:
                # Distinguish quality-rejected from orphan via outcomes
                # presence — coarse but informative for logs.
                if market.get("outcomes") and market.get("outcomePrices"):
                    if market.get("clobTokenIds"):
                        # Most likely matcher returned None (orphan).
                        orphan_count += 1
                    else:
                        quality_skip += 1
                else:
                    quality_skip += 1
                continue
            matched_count += 1
            rows.extend(market_rows)

    if matched_count or orphan_count or parse_skip or quality_skip:
        logger.info(
            "polymarket %s: %d rows from %d matched markets "
            "(%d orphans, %d non-h2h skipped, %d quality-skipped)",
            sport_key, len(rows), matched_count,
            orphan_count, parse_skip, quality_skip,
        )
    return rows
