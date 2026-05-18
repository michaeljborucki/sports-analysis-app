from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Callable

from .mapping import SERIES_TO_SPORT_MARKET, TEAM_CODE_TO_CANONICAL


logger = logging.getLogger(__name__)


BOOK_KEY = "kalshi"

# Kalshi-side overround filter. h2h ideal would have yes_ask + no_ask ≈ 1.00
# + the cross-market spread; >1.20 indicates a thin book / stale quote we
# shouldn't treat as a real price.
MAX_OVERROUND = 1.20


# Eastern Time zone for Kalshi event-ticker decoding. event_ticker time
# components are emitted in US/Eastern (verified by cross-checking
# rules_primary text — "originally scheduled for May 18, 2026 at 6:40 PM
# EDT" matches event_ticker `26MAY181840`).
try:
    from zoneinfo import ZoneInfo
    _KALSHI_TICKER_TZ = ZoneInfo("America/New_York")
except Exception:
    # Fallback for environments without zoneinfo data — EDT is UTC-4 from
    # March-November; this misses ~5 months of EST coverage but better
    # than crashing.
    from datetime import timedelta as _td
    _KALSHI_TICKER_TZ = timezone(-_td(hours=4))


_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


# event_ticker tail formats (after the series prefix + dash):
#   MLB    : YY + MMM + DD + HHMM + TEAM_PAIR   (time IS encoded)
#   NBA/NHL: YY + MMM + DD + TEAM_PAIR          (NO time)
#   WNBA   : YY + MMM + DD + TEAM_PAIR          (NO time)
#
# Regex extracts the date and optional time; team-pair portion is
# everything after.
_TICKER_TAIL_RX = re.compile(
    r"^(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<hhmm>\d{4})?(?P<teams>[A-Z]+)$"
)


def _parse_event_ticker_commence(
    event_ticker: str, series_ticker: str,
) -> tuple[datetime, bool] | None:
    """Decode an event_ticker into (UTC game-start datetime, has_precise_time).

    Returns:
      - (utc_dt, True)  if the ticker carries HHMM after the date (MLB).
                        `utc_dt` is the encoded local-ET time in UTC.
      - (utc_dt, False) if the ticker is date-only (NBA/NHL/WNBA). `utc_dt`
                        is the *noon ET* of that date — a coarse anchor
                        that, paired with a wider match window in the
                        matcher (12h), correctly identifies same-day
                        team pairs without grabbing the next day's game.
      - None            if the ticker doesn't parse at all.

    Example:
      'KXMLBGAME-26MAY181840BALTB' → (2026-05-18 22:40 UTC, True)
      'KXNBAGAME-26MAY18SASOKC'    → (2026-05-18 16:00 UTC, False)
                                     [noon ET = 16:00 UTC]
    """
    if not event_ticker or not event_ticker.startswith(series_ticker + "-"):
        return None
    tail = event_ticker[len(series_ticker) + 1:]
    m = _TICKER_TAIL_RX.match(tail)
    if m is None:
        return None
    hhmm = m.group("hhmm")
    try:
        yy = 2000 + int(m.group("yy"))
        mon = _MONTH_MAP.get(m.group("mon"))
        dd = int(m.group("dd"))
        if mon is None:
            return None
        if hhmm:
            hh = int(hhmm[:2])
            mm = int(hhmm[2:])
            local = datetime(yy, mon, dd, hh, mm, tzinfo=_KALSHI_TICKER_TZ)
            return (local.astimezone(timezone.utc), True)
        else:
            # Date-only ticker — anchor to noon ET as a coarse reference.
            # The matcher uses a wide window (12h) when has_precise_time
            # is False, so the actual game-start within +/- 12h will still
            # match.
            local = datetime(yy, mon, dd, 12, 0, tzinfo=_KALSHI_TICKER_TZ)
            return (local.astimezone(timezone.utc), False)
    except (TypeError, ValueError):
        return None


# Wide window for date-only tickers (NBA/NHL/WNBA). Allows a noon-ET anchor
# to find a same-day game starting anywhere from noon-midnight ET.
_DATE_ONLY_MATCH_WINDOW_MIN = 12 * 60


def yes_to_american(p: float) -> int | None:
    """Convert a YES decimal price (0..1) to American odds.

    Kalshi quotes its YES side as a dollar amount (cents normalized to 0-1
    when divided by 100). A `0.43` yes_ask means "pay $0.43 to win $1" —
    i.e. 1/0.43 = 2.326 decimal odds. American conversion:
      - underdog (p < 0.5): +odds = round((1-p)/p * 100)
      - favorite (p > 0.5): -odds = -round(p/(1-p) * 100)
      - p == 0.5: pick a sign (return -100 by convention)
    """
    if p <= 0 or p >= 1:
        return None
    if p < 0.5:
        return round((1 - p) / p * 100)
    if p > 0.5:
        return -round(p / (1 - p) * 100)
    return -100


def _parse_decimal(s) -> float | None:
    """Kalshi serializes dollar prices as JSON strings ('0.4800'). Coerce
    safely — empty / missing / invalid → None."""
    if s is None:
        return None
    try:
        if isinstance(s, str) and not s.strip():
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Kalshi uses 'Z' or '+00:00' suffix. fromisoformat in 3.11 handles
        # +00:00 directly; Z needs a swap.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _team_code_from_ticker(ticker: str) -> str | None:
    """The market ticker's last dash-separated chunk is the YES team's
    code, e.g. 'KXMLBGAME-26MAY202138ATHLAA-LAA' → 'LAA'.
    """
    if not ticker or "-" not in ticker:
        return None
    return ticker.rsplit("-", 1)[-1].strip() or None


def normalize_markets(
    markets: list[dict],
    series_ticker: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Convert one paginated /markets response (already concatenated to a
    flat list) for a single series into cache rows.

    Phase 1: h2h only. Dispatch by series-ticker prefix would normally
    pick the right normalizer; for now `SERIES_TO_SPORT_MARKET` resolves
    every supported series to ("<sport>", "h2h") and we call
    `_normalize_h2h_markets` unconditionally. Phase 2 adds the dispatch
    by extending SERIES_TO_SPORT_MARKET with non-h2h market keys (spreads,
    totals, etc.) and adding a switch here.
    """
    mapping = SERIES_TO_SPORT_MARKET.get(series_ticker)
    if mapping is None:
        logger.warning("kalshi: no sport/market mapping for series %s", series_ticker)
        return []
    sport_key, market_key = mapping

    # TODO Phase 2: dispatch on `market_key`. For now h2h is the only
    # supported value — if/when KXMLBSPREAD etc. land in
    # SERIES_TO_SPORT_MARKET, route here.
    if market_key == "h2h":
        return _normalize_h2h_markets(
            markets,
            sport_key=sport_key,
            fetched_at=fetched_at,
            match_event=match_event,
        )
    logger.warning(
        "kalshi: series %s mapped to unsupported market_key %r (Phase 2?)",
        series_ticker, market_key,
    )
    return []


def _normalize_h2h_markets(
    markets: list[dict],
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Each h2h event on Kalshi spans TWO markets (one per team, suffixed
    `-{team_code}`). Per market we emit ONE cache row: outcome_name = this
    team's canonical Odds API name, price = yes_to_american(yes_ask_dollars).

    Pairing strategy:
      1. Group raw markets by `event_ticker`.
      2. For each pair (skip groups that aren't exactly size 2), resolve
         both team codes via TEAM_CODE_TO_CANONICAL[sport_key]. That
         gives us BOTH (home/away) candidate teams to feed the matcher
         — orientation is canonicalized by the matcher's return value.
      3. Apply per-market quality filter (status, overround, expired
         occurrence, missing prices).
      4. Emit one row per surviving market.
    """
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)

    by_event: dict[str, list[dict]] = {}
    for m in markets:
        et = m.get("event_ticker")
        if not et:
            continue
        by_event.setdefault(et, []).append(m)

    # We need the series_ticker prefix to decode event_ticker time
    # components. Since `normalize_markets` only calls us with a single
    # series at a time, we can re-derive it from the first market's
    # event_ticker (`KXMLBGAME-...` → `KXMLBGAME`). This keeps the
    # function signature stable while making time-decoding work without
    # threading a new arg through.
    series_ticker: str | None = None
    for m in markets:
        et = m.get("event_ticker") or ""
        if "-" in et:
            series_ticker = et.split("-", 1)[0]
            break

    rows: list[dict] = []
    skipped_pair = 0
    skipped_quality = 0
    skipped_unknown_team = 0
    orphans = 0
    live = 0

    for event_ticker, mkts in by_event.items():
        if len(mkts) != 2:
            # h2h has exactly 2 markets per event. If we see anything else
            # it's a 3-way (extra-innings tie?), a derivative we don't
            # understand yet, or pagination ate a market — skip to avoid
            # half-emitting.
            skipped_pair += 1
            continue

        # Resolve both team codes up-front; we need both to call the matcher.
        coded: list[tuple[dict, str, str]] = []  # (market, code, canonical)
        for m in mkts:
            code = _team_code_from_ticker(m.get("ticker") or "")
            canon = code_map.get(code or "")
            if not code or not canon:
                # Either ticker malformed or team code missing from our
                # static map. Skip the entire event — a one-sided emission
                # would create an orphan outcome.
                skipped_unknown_team += 1
                coded = []
                break
            coded.append((m, code, canon))
        if len(coded) != 2:
            continue
        (m_a, code_a, canon_a), (m_b, code_b, canon_b) = coded

        # Game-start time resolution:
        #   MLB tickers carry HHMM → precise time, default match window.
        #   NBA/NHL/WNBA tickers are date-only → coarse noon-ET anchor +
        #     12h match window (catches the actual same-day game start).
        # Fall back to occurrence_datetime if ticker doesn't parse (which
        # shouldn't happen for the 4 series we support, but defensive).
        ticker_decoded = (
            _parse_event_ticker_commence(event_ticker, series_ticker or "")
            if series_ticker
            else None
        )
        match_window = None  # use matcher's default (60min)
        if ticker_decoded is not None:
            commence, has_precise_time = ticker_decoded
            if not has_precise_time:
                match_window = _DATE_ONLY_MATCH_WINDOW_MIN
        else:
            commence = _parse_iso_utc(
                m_a.get("occurrence_datetime") or m_b.get("occurrence_datetime")
            )
        if commence is None:
            skipped_quality += 1
            continue
        # "Live or past" skip uses the precise commence when we have it.
        # For date-only tickers the noon-ET anchor isn't a real start time,
        # so apply the live filter only when we have a precise time.
        if ticker_decoded and ticker_decoded[1] and commence <= now:
            live += 1
            continue

        # Resolve the canonical event_id by handing both candidate teams
        # to the matcher. Kalshi gives no home/away orientation, but the
        # matcher checks both orderings and returns the canonical pair.
        matched = match_event(
            sport_key, canon_a, canon_b, commence, match_window,
        )
        if matched is None:
            orphans += 1
            continue
        canon_home = matched.get("home_team") or canon_a
        canon_away = matched.get("away_team") or canon_b
        # Prefer the matched event's canonical commence_time over the
        # Kalshi-derived one — the cache row needs to store the REAL
        # game start (which is what purge_live_rows_for_book + the
        # frontend / matrix layer expect). The Kalshi-derived `commence`
        # is approximate (date-only anchor for NBA/NHL/WNBA, or pseudo-
        # EDT-decoded for MLB).
        commence = matched.get("commence_time") or commence
        # matched's home/away is aligned to (canon_a, canon_b) positions:
        # if matcher swapped, matched["home_team"] is what we passed as
        # `away` (canon_b). Build a per-code → canonical map post-match
        # so each market's outcome_name uses the matched canonical (which
        # may differ from code_map's canonical only by orientation, but
        # both should produce identical strings since matcher returned
        # canonicals derived from the cache's own rows).
        canon_by_code = {code_a: canon_home, code_b: canon_away}

        event_id = matched["event_id"]
        base = {
            "event_id": event_id,
            "sport_key": sport_key,
            "home_team": canon_home,
            "away_team": canon_away,
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }

        # Per-market quality + emission.
        for market, code, _canon in coded:
            if not _market_passes_quality(market):
                skipped_quality += 1
                continue
            yes_ask = _parse_decimal(market.get("yes_ask_dollars"))
            if yes_ask is None:
                skipped_quality += 1
                continue
            american = yes_to_american(yes_ask)
            if american is None:
                skipped_quality += 1
                continue
            outcome_canon = canon_by_code.get(code)
            if not outcome_canon:
                skipped_unknown_team += 1
                continue
            rows.append({
                **base,
                "market_key": "h2h",
                "outcome_name": outcome_canon,
                "outcome_point": None,
                "price_american": american,
            })

    if skipped_pair or skipped_quality or skipped_unknown_team or orphans or live:
        logger.info(
            "kalshi %s h2h: %d rows, %d events, %d orphans, %d live, "
            "%d quality-skipped, %d unknown-team, %d pair-mismatch",
            sport_key, len(rows), len(by_event), orphans, live,
            skipped_quality, skipped_unknown_team, skipped_pair,
        )
    return rows


def _market_passes_quality(m: dict) -> bool:
    """Apply the per-market quality gate. Returns False if the market
    should be discarded."""
    if (m.get("status") or "").lower() != "active":
        return False
    yes_ask = _parse_decimal(m.get("yes_ask_dollars"))
    if yes_ask is None or yes_ask <= 0:
        return False
    no_ask = _parse_decimal(m.get("no_ask_dollars"))
    # If no_ask is missing we can't compute overround — be conservative
    # and drop, since markets without a NO quote are typically thin.
    if no_ask is None:
        return False
    if (yes_ask + no_ask) > MAX_OVERROUND:
        return False
    return True
