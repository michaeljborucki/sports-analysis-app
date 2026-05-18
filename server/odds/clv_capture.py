"""Closing-line capture for CLV.

The Odds API cache (odds_snapshot) purges rows older than 10 minutes, so
post-game CLV lookups can't read directly from it. We need a frozen
snapshot of "what the sharp market said when the gate closed" for every
event we care about.

Capture window: events whose commence_time falls in [now+5min, now+15min].
For each in-window event, read sharp-book prices for every market the cache
has, devig within each pairing bucket, and persist as one row per
(event, market, outcome, point) into the closing_lines table.

Sport-agnostic by design: the only sport-specific knowledge lives in the
bucketing function (already in ev.py — handles all 11 sports including
3-way soccer, alt lines, team totals, props). Adding a new sport adds rows
to that bucket dispatch; no changes here.

Devig source order, mirroring the EV scanner:
  1. Pinnacle no-vig: if a complete bucket from Pinnacle exists, use it.
  2. Consensus no-vig: take the median devigged probability across all
     sharp books that posted a complete bucket. Falls back to all
     non-coral33 books when no sharp books cover the market (props).

Output is a SET of rows per bucket — every outcome in the bucket gets a
close_prob_devig + close_odds derived from the same devig pass. That way a
CLV lookup for "Home -3.5 vs Away +3.5" picks up the matched pair.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Iterable

from .cache import OddsCache
from .devig import devig_n_way, implied_to_american
from .ev import (
    SHARP_BOOKS,
    _base_market,
    _is_three_way,
    _pair_bucket,
)


logger = logging.getLogger(__name__)


# Coral33 is excluded from consensus devig — it's not a sharp anchor and
# its prices are themselves the offered (vigged) lines we're measuring
# CLV against. Including it would bias the fair line toward coral33's own
# vig.
_EXCLUDE_BOOKS = frozenset({"coral33"})


def _bucket_key(market_key: str, outcome_name: str, outcome_point: float | None) -> object:
    """Stable bucket key (market_family, point_or_player, etc.). Reuses
    the EV scanner's pairing logic so totals/spreads/team-totals/props
    all group identically here."""
    return _pair_bucket(market_key, (outcome_name, outcome_point))


def _outcomes_for_event(
    rows: list[dict],
) -> dict[tuple[str, tuple], list[dict]]:
    """Group rows by (market_key, bucket_key). Each bucket contains
    one or more (outcome_name, outcome_point, price_american, bookmaker_key)
    quotes.

    A "bucket" is a set of outcomes that devig together: e.g. all 3 outcomes
    of a 3-way h2h, or {Over, Under} at a single total point.
    """
    out: dict[tuple[str, tuple], list[dict]] = defaultdict(list)
    for r in rows:
        market_key = r["market_key"]
        outcome_name = r["outcome_name"]
        outcome_point = r.get("outcome_point")
        # The cache stores 0.0 sentinel for h2h; preserve that as 0.0 (the
        # pairing fn ignores point for h2h anyway).
        bucket = _bucket_key(market_key, outcome_name, outcome_point)
        out[(market_key, bucket)].append(r)
    return out


def _book_prices(
    rows: list[dict],
) -> dict[str, dict[tuple[str, float | None], int]]:
    """Per-book table of {(outcome_name, point): price_american}.

    Coral33 is filtered out (not a sharp anchor). All other books are
    kept; the caller decides which subset to devig (Pinnacle / sharp /
    consensus)."""
    out: dict[str, dict[tuple[str, float | None], int]] = defaultdict(dict)
    for r in rows:
        book = r["bookmaker_key"]
        if book in _EXCLUDE_BOOKS:
            continue
        pt = r.get("outcome_point")
        pt_norm = None if pt is None else round(float(pt), 1)
        out[book][(r["outcome_name"], pt_norm)] = int(r["price_american"])
    return out


def _devig_bucket(
    rows: list[dict],
    market_key: str,
) -> dict[tuple[str, float | None], float] | None:
    """Devig one bucket. Returns {(outcome_name, point): fair_prob} where
    fair_prob is the consensus across sharp books (or all non-coral33
    books if no sharp book covered the bucket).

    Returns None if no book offered a complete N-way set.
    """
    n_way = 3 if _is_three_way(market_key) else 2
    by_book = _book_prices(rows)
    if not by_book:
        return None

    # Collect outcome keys present in the bucket (across all books).
    outcomes_seen: list[tuple[str, float | None]] = []
    seen_set: set[tuple[str, float | None]] = set()
    for prices in by_book.values():
        for k in prices.keys():
            if k not in seen_set:
                seen_set.add(k)
                outcomes_seen.append(k)
    # We can only devig if at least N outcomes are present — otherwise the
    # bucket isn't a complete market (e.g. only Over is offered).
    if len(outcomes_seen) < n_way:
        return None

    def _try_devig_with(book_filter: set[str]) -> dict[tuple, float] | None:
        # Per-book devig: each book must have prices for all outcomes_seen.
        per_book: list[dict[tuple, float]] = []
        for book, prices in by_book.items():
            if book not in book_filter:
                continue
            if not all(k in prices for k in outcomes_seen):
                continue
            ordered_prices = [prices[k] for k in outcomes_seen]
            fair = devig_n_way(ordered_prices)
            if not fair:
                continue
            per_book.append({k: p for k, p in zip(outcomes_seen, fair)})
        if not per_book:
            return None
        # Aggregate: median per outcome across books that covered the
        # complete bucket. Median dampens single-book outliers.
        agg: dict[tuple, float] = {}
        for k in outcomes_seen:
            vals = [pb[k] for pb in per_book if k in pb]
            if vals:
                agg[k] = float(median(vals))
        # Re-normalize so probabilities sum to 1.0 (median can drift a
        # few bps from unity).
        s = sum(agg.values())
        if s <= 0:
            return None
        return {k: v / s for k, v in agg.items()}

    # Priority 1: Pinnacle only (canonical price-discovery venue).
    if "pinnacle" in by_book:
        pinnacle_only = _try_devig_with({"pinnacle"})
        if pinnacle_only is not None:
            return pinnacle_only
    # Priority 2: sharp consensus.
    sharp_set = SHARP_BOOKS & set(by_book.keys())
    if sharp_set:
        sharp = _try_devig_with(sharp_set)
        if sharp is not None:
            return sharp
    # Priority 3: all available non-coral33 books (props, obscure markets).
    return _try_devig_with(set(by_book.keys()))


def _source_books_for_bucket(rows: list[dict]) -> str:
    """Comma-separated, deduped list of books that contributed to the
    devig — for debugging / UI transparency."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for r in rows:
        b = r["bookmaker_key"]
        if b in _EXCLUDE_BOOKS or b in seen_set:
            continue
        seen_set.add(b)
        seen.append(b)
    return ",".join(sorted(seen))


def devig_rows_to_closing_lines(
    event_meta: dict,
    rows: list[dict],
    captured_at: datetime,
) -> list[dict]:
    """Devig a flat list of odds_snapshot-shaped rows into
    closing_lines-shaped rows for one event.

    Pure function — no cache reads or writes. Used by both the live
    capture (reads rows from odds_snapshot) and the historical backfill
    (reads rows from a normalized Odds API response). The event_meta
    carries the canonical home/away/commence/sport_key the closing_lines
    row needs.
    """
    out_rows: list[dict] = []
    if not rows:
        return out_rows
    eid = event_meta["event_id"]
    sport_key = event_meta.get("sport_key") or rows[0].get("sport_key") or ""
    home_team = event_meta.get("home_team") or rows[0].get("home_team") or ""
    away_team = event_meta.get("away_team") or rows[0].get("away_team") or ""
    commence = event_meta["commence_time"]

    buckets = _outcomes_for_event(rows)
    for (market_key, _bucket_id), bucket_rows in buckets.items():
        fair = _devig_bucket(bucket_rows, market_key)
        if fair is None:
            continue
        source_books = _source_books_for_bucket(bucket_rows)
        for (outcome_name, outcome_point), prob in fair.items():
            # Guard: drop degenerate probabilities (0 or 1) — they
            # produce infinite American odds and would propagate NaN
            # through the CLV math.
            if prob <= 0.0 or prob >= 1.0:
                continue
            close_odds = implied_to_american(prob)
            if close_odds == 0:
                continue
            out_rows.append({
                "event_id": eid,
                "sport_key": sport_key,
                "home_team": home_team,
                "away_team": away_team,
                "market_key": market_key,
                "outcome_name": outcome_name,
                "outcome_point": (
                    0.0 if outcome_point is None else float(outcome_point)
                ),
                "close_odds": int(close_odds),
                "close_prob_devig": round(float(prob), 6),
                "commence_time": commence,
                "captured_at": captured_at,
                "source_books": source_books,
            })
    return out_rows


def capture_closing_lines_for_events(
    cache: OddsCache,
    events: Iterable[dict],
    now: datetime | None = None,
) -> int:
    """Capture closing lines for a specific list of events.

    For each event, reads every odds_snapshot row, groups by market +
    pairing bucket, devigs, and writes one closing_lines row per outcome.
    Idempotent on the (event, market, outcome, point) PK — re-capture
    overwrites with the latest fair line.

    Events whose `commence_time <= now` are skipped — books post very
    different prices during a live game (often heavy implied prob on
    whoever's currently winning), and capturing those as "closing" would
    poison the CLV math. The live scheduler's T-15..T-5 window
    naturally enforces this, but the bound is restated here so callers
    invoking capture_closing_lines_for_events with a hand-picked event
    set can't accidentally grab in-progress prices.

    Returns total rows upserted.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    events = list(events)
    if not events:
        return 0

    def _commence_dt(ev: dict) -> datetime | None:
        c = ev.get("commence_time")
        if c is None:
            return None
        if isinstance(c, datetime):
            return c if c.tzinfo else c.replace(tzinfo=timezone.utc)
        try:
            dt = datetime.fromisoformat(str(c).replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    events = [e for e in events if (lambda c: c is not None and c > now)(_commence_dt(e))]
    if not events:
        return 0

    # Pull every cache row for these events in one shot. The cache doesn't
    # expose a "rows-for-event-ids" query, so we read per-sport and filter
    # in-process. Acceptable because the in-window event set is small
    # (typically <20 events) and sport_key narrows the universe before the
    # filter pass.
    event_ids: set[str] = {e["event_id"] for e in events}
    sport_keys: set[str] = {e["sport_key"] for e in events if e.get("sport_key")}
    if not sport_keys:
        sport_keys = {None}

    all_rows: list[dict] = []
    for sk in sport_keys:
        rows = cache.all_current(sport_key=sk) if sk else cache.all_current()
        all_rows.extend(r for r in rows if r["event_id"] in event_ids)

    if not all_rows:
        return 0

    # Group rows by event for per-event devig passes.
    by_event: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        by_event[r["event_id"]].append(r)

    out_rows: list[dict] = []
    for event in events:
        eid = event["event_id"]
        ev_rows = by_event.get(eid) or []
        if not ev_rows:
            continue
        out_rows.extend(devig_rows_to_closing_lines(event, ev_rows, now))

    if not out_rows:
        return 0
    return cache.upsert_closing_lines(out_rows)


def capture_closing_lines(
    cache: OddsCache,
    now: datetime | None = None,
    lead_minutes: int = 15,
    trail_minutes: int = 5,
) -> int:
    """Capture closing lines for every event in the T-{lead}..T-{trail}
    window. Default window matches baseball-agents.

    Returns total rows upserted. Safe to call on a fixed interval — the
    upsert is idempotent on the PK and re-captures within the same window
    overwrite with the latest sharp-consensus price.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    events = cache.events_in_close_window(
        now, lead_minutes=lead_minutes, trail_minutes=trail_minutes,
    )
    if not events:
        return 0
    count = capture_closing_lines_for_events(cache, events, now=now)
    if count > 0:
        logger.info(
            "closing-line capture: %d outcomes across %d events",
            count, len(events),
        )
    return count
