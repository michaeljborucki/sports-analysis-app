from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Callable

from .mapping import SERIES_TO_SPORT_MARKET, TEAM_CODE_TO_CANONICAL


# Kalshi's market-order (taker) fee, applied per contract as
# F * price * (1-price). Verified empirically: a 243-contract buy of
# yes_ask=0.57 returned an estimated cost of $142.68 with a $4.17 fee,
# back-solving to F = 4.17 / (243 * 0.57 * 0.43) = 0.0700 exactly.
# Limit orders (makers) pay no fee, but the scanner surfaces actionable
# prices for an instant-fill bettor — taker pricing is the right default.
KALSHI_TAKER_FEE = 0.07


logger = logging.getLogger(__name__)


BOOK_KEY = "kalshi"

# Kalshi-side overround filter for h2h / RFI. yes_ask + no_ask ≈ 1.00
# + book vig; >1.20 indicates a thin book / stale quote we shouldn't
# treat as a real price. ALT markets use a stricter filter (see
# `_alt_market_passes_quality`).
MAX_OVERROUND = 1.20

# Alt-line filters (spreads / totals / team_totals / F5 spread/total). Many
# extreme alts show yes_ask=0.01 / no_ask=1.00 — overround sums to 1.01 and
# would pass the h2h filter, but prices are meaningless. Stricter gate:
ALT_MIN_ASK = 0.02     # drop if either ask is below 2¢ — no real offer
ALT_MIN_SUM = 0.80     # drop if asks sum below 80¢ — bid-ask gap too wide

# F5 3-way: each market is one of 3 mutually exclusive outcomes (Tie / TeamA
# / TeamB). The 3 yes_asks should sum to ~1.0 across the event, but we
# evaluate each market in isolation — only require non-trivial yes_ask.
F5_3WAY_MIN_YES_ASK = 0.01


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


# Market-ticker suffix after the LAST dash. Carries either:
#   - a pure team code:                "KXMLBGAME-..-LAA"        → "LAA"
#   - a team code + strike index:      "KXMLBSPREAD-..-MIL4"     → "MIL"
#   - a pure strike index (totals):    "KXMLBTOTAL-..-14"        → "14"
#   - a literal sentinel:              "KXMLBF5-..-TIE"          → "TIE"
#
# `_strip_strike_index` peels trailing digits to recover the team code (or
# leaves a digits-only / sentinel suffix unchanged).
_TRAILING_DIGITS_RX = re.compile(r"^([A-Z]+)\d+$")


def _strip_strike_index(suffix: str) -> str:
    """Remove a trailing strike-index numeric (if present).

    'MIL8'      → 'MIL'
    'NYK124'    → 'NYK'
    'CONN3'     → 'CONN'
    'TIE'       → 'TIE'    (no change)
    '14'        → '14'     (no change — pure numeric totals suffix)
    ''          → ''
    """
    if not suffix:
        return suffix
    m = _TRAILING_DIGITS_RX.match(suffix)
    if m:
        return m.group(1)
    return suffix


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


def _parse_event_ticker_teams(
    event_ticker: str, series_ticker: str,
) -> str | None:
    """Return the team-pair concatenation tail (e.g. 'MILCHC', 'SDSEA')."""
    if not event_ticker or not event_ticker.startswith(series_ticker + "-"):
        return None
    tail = event_ticker[len(series_ticker) + 1:]
    m = _TICKER_TAIL_RX.match(tail)
    if m is None:
        return None
    return m.group("teams")


def _split_team_pair(
    team_pair: str, code_map: dict[str, str],
) -> tuple[str, str] | None:
    """Find a unique split of `team_pair` into (code_a, code_b) where both
    are keys in `code_map`. Returns None if 0 or >1 valid splits exist.

    Codes are 2-4 chars in our maps; the split range iterates `i ∈ [2, len-2]`
    so each half is at least 2 chars.
    """
    if not team_pair or len(team_pair) < 4:
        return None
    valid: list[tuple[str, str]] = []
    for i in range(2, len(team_pair) - 1):
        a, b = team_pair[:i], team_pair[i:]
        if a in code_map and b in code_map:
            valid.append((a, b))
    if len(valid) != 1:
        return None
    return valid[0]


# Wide window for date-only tickers (NBA/NHL/WNBA). Allows a noon-ET anchor
# to find a same-day game starting anywhere from noon-midnight ET.
_DATE_ONLY_MATCH_WINDOW_MIN = 12 * 60


def yes_to_american(p: float) -> int | None:
    """Convert a YES decimal price (0..1) to FEE-ADJUSTED American odds.

    Kalshi quotes its YES side as a dollar amount (0.43 = "pay $0.43 to
    win $1") on the orderbook. A taker also pays a 7% fee on the
    variance term `P * (1-P)`, so the true per-contract cost is
        cost = P + 0.07 * P * (1-P) = P * (1.07 - 0.07 * P)
    and the realized profit on a winning contract is `1 - cost`. This
    function returns the American odds *implied by that effective cost*,
    so EV/arb comparisons against bookmakers (whose vig is already in
    the line) are apples-to-apples. Without the fee adjustment, the
    scanner surfaces phantom Kalshi edges that vanish at fill time.

    Rounding is `math.floor` of the raw American value, which for both
    signs rounds *against the bettor* (favorites become one notch more
    negative, underdogs one notch less positive). Matches the Kalshi
    consumer app's display convention.
    """
    if p <= 0 or p >= 1:
        return None
    cost = p + KALSHI_TAKER_FEE * p * (1 - p)
    profit = 1.0 - cost
    if profit <= 0:
        return None
    if cost > profit:
        return math.floor(-cost / profit * 100)
    return math.floor(profit / cost * 100)


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

    Dispatches on the `market_key` resolved from `SERIES_TO_SPORT_MARKET`:
      - h2h (game winner)              → `_normalize_h2h_markets`
      - h2h_h1 / h2h_h2 / h2h_q1...    → `_normalize_h2h_period_markets`
      - alternate_spreads*             → `_normalize_spread_markets`
      - alternate_totals*              → `_normalize_total_markets`
      - alternate_team_totals*         → `_normalize_team_total_markets`
      - nrfi                           → `_normalize_rfi_markets`
      - h2h_3_way_1st_5_innings        → `_normalize_f5_winner_markets`
    """
    mapping = SERIES_TO_SPORT_MARKET.get(series_ticker)
    if mapping is None:
        logger.warning("kalshi: no sport/market mapping for series %s", series_ticker)
        return []
    sport_key, market_key = mapping

    # --- Dispatch on market_key. Order matters: more specific prefixes
    #     (e.g. h2h_3_way_*) before generic ones (h2h_*).
    if market_key == "h2h":
        return _normalize_h2h_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, fetched_at=fetched_at,
            match_event=match_event,
        )
    if market_key.startswith("h2h_3_way"):
        return _normalize_f5_winner_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, market_key=market_key,
            fetched_at=fetched_at, match_event=match_event,
        )
    if market_key.startswith("h2h_"):
        # Period h2h (h2h_h1 / h2h_h2 / h2h_q1...) — same pattern as the
        # game-h2h but writes to the period-specific market_key.
        return _normalize_h2h_period_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, market_key=market_key,
            fetched_at=fetched_at, match_event=match_event,
        )
    if market_key == "nrfi":
        return _normalize_rfi_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, fetched_at=fetched_at,
            match_event=match_event,
        )
    if market_key.startswith("alternate_team_totals"):
        return _normalize_team_total_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, market_key=market_key,
            fetched_at=fetched_at, match_event=match_event,
        )
    if market_key.startswith("alternate_spreads"):
        return _normalize_spread_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, market_key=market_key,
            fetched_at=fetched_at, match_event=match_event,
        )
    if market_key.startswith("alternate_totals"):
        return _normalize_total_markets(
            markets, series_ticker=series_ticker,
            sport_key=sport_key, market_key=market_key,
            fetched_at=fetched_at, match_event=match_event,
        )

    logger.warning(
        "kalshi: series %s mapped to unsupported market_key %r",
        series_ticker, market_key,
    )
    return []


# ──────────────────────────────────────────────────────────────────────
# Shared event-resolution helper
# ──────────────────────────────────────────────────────────────────────


def _resolve_event(
    event_ticker: str,
    series_ticker: str,
    sport_key: str,
    code_map: dict[str, str],
    match_event: Callable[..., dict | None],
    now: datetime,
    *,
    use_team_pair_decomp: bool,
    seed_codes: tuple[str, str] | None = None,
) -> tuple[dict, datetime, dict[str, str]] | None:
    """Find the canonical Odds-API event for this Kalshi event_ticker.

    Returns (matched, commence_utc, code_to_canon_map) or None.

    `code_to_canon_map`: maps each *Kalshi team code* in the event to the
    matched event's canonical (Odds API) home/away name. Used by per-market
    callers that need to know which canonical name corresponds to the YES
    side (e.g. spreads: the YES team is decoded from the market ticker
    suffix, and the OTHER side is the remaining code).

    Args:
      use_team_pair_decomp: True for spread/total/team_total/etc. where we
        need to recover both team codes from event_ticker's `MILCHC`-style
        tail. False for h2h paths that read codes directly off the per-
        market ticker suffix.
      seed_codes: if caller already knows both Kalshi codes (h2h paths
        pair markets per-event), pass them — skips team-pair decomp.
    """
    # Decode the event_ticker for time + (optionally) team pair.
    ticker_decoded = _parse_event_ticker_commence(event_ticker, series_ticker)
    match_window: int | None = None
    has_precise_time = False
    if ticker_decoded is not None:
        commence, has_precise_time = ticker_decoded
        if not has_precise_time:
            match_window = _DATE_ONLY_MATCH_WINDOW_MIN
    else:
        # No ticker-time fallback for alt markets — every Phase 2 series we
        # support has the same tail format as Phase 1. If we can't decode
        # the ticker, the event is malformed; bail.
        return None

    # Resolve both team codes.
    if seed_codes is not None:
        code_a, code_b = seed_codes
    elif use_team_pair_decomp:
        team_pair = _parse_event_ticker_teams(event_ticker, series_ticker)
        if not team_pair:
            return None
        split = _split_team_pair(team_pair, code_map)
        if split is None:
            logger.debug(
                "kalshi: ambiguous/no team pair split for %s (%s)",
                event_ticker, team_pair,
            )
            return None
        code_a, code_b = split
    else:
        return None

    canon_a = code_map.get(code_a)
    canon_b = code_map.get(code_b)
    if not canon_a or not canon_b:
        return None

    # Live-or-past skip (only when we have precise time).
    if has_precise_time and commence <= now:
        return None

    matched = match_event(sport_key, canon_a, canon_b, commence, match_window)
    if matched is None:
        return None

    canon_home = matched.get("home_team") or canon_a
    canon_away = matched.get("away_team") or canon_b
    commence = matched.get("commence_time") or commence

    # Map each Kalshi code to the matched event's canonical orientation.
    # The matcher returns home/away aligned to ITS canonical (cache) view.
    # `canon_a` matched to either home or away — figure out which by
    # canonical name equality.
    code_to_canon: dict[str, str] = {}
    if canon_a == canon_home or canon_a == canon_away:
        code_to_canon[code_a] = canon_home if canon_a == canon_home else canon_away
        code_to_canon[code_b] = canon_away if canon_a == canon_home else canon_home
    else:
        # Defensive — matcher returned different canonicals than we passed.
        # Fall back to the raw map (should never happen since matcher
        # canonicalizes through cache).
        code_to_canon[code_a] = canon_a
        code_to_canon[code_b] = canon_b

    matched_view = {
        "event_id": matched["event_id"],
        "home_team": canon_home,
        "away_team": canon_away,
    }
    return matched_view, commence, code_to_canon


# ──────────────────────────────────────────────────────────────────────
# h2h (game-winner)
# ──────────────────────────────────────────────────────────────────────


def _normalize_h2h_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Each h2h event on Kalshi spans TWO markets (one per team, suffixed
    `-{team_code}`). Per market we emit ONE cache row: outcome_name = this
    team's canonical Odds API name, price = yes_to_american(yes_ask_dollars).
    """
    return _normalize_h2h_like(
        markets,
        series_ticker=series_ticker,
        sport_key=sport_key,
        market_key="h2h",
        fetched_at=fetched_at,
        match_event=match_event,
    )


def _normalize_h2h_period_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """NBA / WNBA 1H, 2H, 1Q etc. winner markets. Identical structure to
    game h2h: 2 markets per event, suffix = team code. The series also
    emits a 3rd TIE market for NBA 1H/2H winner — that's a 3-way variant
    we don't currently store separately. Skip TIE markets so the per-event
    pair count drops back to 2.
    """
    # Filter out the literal `-TIE` markets up front. These are the 3-way
    # tie outcome — for now we only consume the 2-way YES/NO pair from
    # the team-suffixed markets.
    filtered = [
        m for m in markets
        if (_team_code_from_ticker(m.get("ticker") or "") or "").upper() != "TIE"
    ]
    return _normalize_h2h_like(
        filtered,
        series_ticker=series_ticker,
        sport_key=sport_key,
        market_key=market_key,
        fetched_at=fetched_at,
        match_event=match_event,
    )


def _normalize_h2h_like(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Internal: shared 2-markets-per-event h2h flow used by both the
    game-winner and period-winner paths. The only difference is the
    `market_key` written to each cache row."""
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)

    by_event: dict[str, list[dict]] = {}
    for m in markets:
        et = m.get("event_ticker")
        if not et:
            continue
        by_event.setdefault(et, []).append(m)

    # Re-derive series_ticker from event_ticker if not provided.
    if series_ticker is None:
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
            skipped_pair += 1
            continue

        coded: list[tuple[dict, str, str]] = []  # (market, code, canonical)
        for m in mkts:
            code = _team_code_from_ticker(m.get("ticker") or "")
            canon = code_map.get(code or "")
            if not code or not canon:
                skipped_unknown_team += 1
                coded = []
                break
            coded.append((m, code, canon))
        if len(coded) != 2:
            continue
        (m_a, code_a, _canon_a), (m_b, code_b, _canon_b) = coded

        resolved = _resolve_event(
            event_ticker,
            series_ticker or "",
            sport_key,
            code_map,
            match_event,
            now,
            use_team_pair_decomp=False,
            seed_codes=(code_a, code_b),
        )
        # Fallback for h2h: try occurrence_datetime when ticker parses but
        # is date-only and matcher returns no match — preserve Phase 1
        # behavior. The new helper returns None for "no match" without
        # distinguishing cause, which is fine for h2h's accounting.
        if resolved is None:
            # Distinguish "live/past" from "orphan": peek the ticker.
            tdec = _parse_event_ticker_commence(event_ticker, series_ticker or "")
            if tdec is not None and tdec[1] and tdec[0] <= now:
                live += 1
            else:
                orphans += 1
            continue
        matched, commence, code_to_canon = resolved

        base = {
            "event_id": matched["event_id"],
            "sport_key": sport_key,
            "home_team": matched["home_team"],
            "away_team": matched["away_team"],
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }

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
            outcome_canon = code_to_canon.get(code)
            if not outcome_canon:
                skipped_unknown_team += 1
                continue
            rows.append({
                **base,
                "market_key": market_key,
                "outcome_name": outcome_canon,
                "outcome_point": None,
                "price_american": american,
                # WS bookkeeping — ingestor uses _market_ticker to map
                # ticker updates → cache rows; _ws_side tells it which
                # side (yes_ask vs no_ask) to read from each ticker msg.
                # The fields pass through cache.upsert harmlessly.
                "_market_ticker": market.get("ticker"),
                "_ws_side": "yes",
            })

    if skipped_pair or skipped_quality or skipped_unknown_team or orphans or live:
        logger.info(
            "kalshi %s %s: %d rows, %d events, %d orphans, %d live, "
            "%d quality-skipped, %d unknown-team, %d pair-mismatch",
            sport_key, market_key, len(rows), len(by_event), orphans, live,
            skipped_quality, skipped_unknown_team, skipped_pair,
        )
    return rows


# ──────────────────────────────────────────────────────────────────────
# Spread markets (alternate_spreads / alternate_spreads_h1 / ... / 1st_5_innings)
# ──────────────────────────────────────────────────────────────────────


def _normalize_spread_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Each Kalshi spread market is one-sided: YES = the team named in the
    title wins by ≥ floor_strike. Emit TWO cache rows per Kalshi market:

      1. outcome_name = YES_team_canonical,  point = -floor_strike,
         price = american(yes_ask)
      2. outcome_name = OTHER_team_canonical, point = +floor_strike,
         price = american(no_ask)

    Convention: positive `outcome_point` is the underdog side (+pts), so
    the OTHER side (who concedes the spread) gets +floor_strike. The YES
    team wins by MORE than floor, so they're laying floor → negative point.
    """
    return _normalize_two_sided_market(
        markets,
        series_ticker=series_ticker,
        sport_key=sport_key,
        market_key=market_key,
        fetched_at=fetched_at,
        match_event=match_event,
        kind="spread",
    )


# ──────────────────────────────────────────────────────────────────────
# Total markets (alternate_totals / *_h1 / *_h2 / *_1st_5_innings)
# ──────────────────────────────────────────────────────────────────────


def _normalize_total_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Kalshi total markets are pure Over/Under: YES = Over floor_strike,
    NO = Under floor_strike. Emit:

      1. outcome_name = "Over",  point = floor_strike, price = american(yes_ask)
      2. outcome_name = "Under", point = floor_strike, price = american(no_ask)

    No team-side encoding — but we still need both team canonicals via
    event_ticker decomposition to populate home_team/away_team.
    """
    return _normalize_two_sided_market(
        markets,
        series_ticker=series_ticker,
        sport_key=sport_key,
        market_key=market_key,
        fetched_at=fetched_at,
        match_event=match_event,
        kind="total",
    )


# ──────────────────────────────────────────────────────────────────────
# Team total markets (alternate_team_totals)
# ──────────────────────────────────────────────────────────────────────


def _normalize_team_total_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """Each Kalshi team-total market is one-sided: YES = the named team
    scores over floor_strike. Emit two rows:

      1. outcome_name = "{team_canonical} Over",  point = floor_strike,
         price = american(yes_ask)
      2. outcome_name = "{team_canonical} Under", point = floor_strike,
         price = american(no_ask)

    Suffix carries the team code (e.g. `-MIL8` → MIL). Both teams' codes
    needed via event_ticker decomp to populate home/away.
    """
    return _normalize_two_sided_market(
        markets,
        series_ticker=series_ticker,
        sport_key=sport_key,
        market_key=market_key,
        fetched_at=fetched_at,
        match_event=match_event,
        kind="team_total",
    )


# ──────────────────────────────────────────────────────────────────────
# Shared two-sided-market emitter (spread / total / team_total)
# ──────────────────────────────────────────────────────────────────────


def _normalize_two_sided_market(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
    kind: str,           # "spread" | "total" | "team_total"
) -> list[dict]:
    """Shared flow: per Kalshi market emit two cache rows (YES side, NO side)
    after passing the alt-market quality filter. Event resolution uses
    team-pair decomposition (event_ticker tail carries both codes).
    """
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)

    # Re-derive series_ticker if not passed in.
    if series_ticker is None:
        for m in markets:
            et = m.get("event_ticker") or ""
            if "-" in et:
                series_ticker = et.split("-", 1)[0]
                break

    # Cache per-event resolution so we don't re-decompose for every market.
    event_cache: dict[str, tuple[dict, datetime, dict[str, str]] | None] = {}

    rows: list[dict] = []
    skipped_quality = 0
    skipped_decomp = 0
    skipped_unknown_team = 0
    orphans = 0
    live = 0

    for m in markets:
        event_ticker = m.get("event_ticker") or ""
        if not event_ticker:
            continue

        # Resolve once per event.
        if event_ticker not in event_cache:
            event_cache[event_ticker] = _resolve_event(
                event_ticker,
                series_ticker or "",
                sport_key,
                code_map,
                match_event,
                now,
                use_team_pair_decomp=True,
            )
        resolved = event_cache[event_ticker]
        if resolved is None:
            # Distinguish live/past from orphan via ticker peek.
            tdec = _parse_event_ticker_commence(event_ticker, series_ticker or "")
            if tdec is not None and tdec[1] and tdec[0] <= now:
                live += 1
            elif tdec is None:
                skipped_decomp += 1
            else:
                # Could be orphan (no Odds API event) or team-pair decomp
                # failure. We don't distinguish; both bucket as orphans.
                orphans += 1
            continue
        matched, commence, code_to_canon = resolved

        if not _alt_market_passes_quality(m):
            skipped_quality += 1
            continue

        yes_ask = _parse_decimal(m.get("yes_ask_dollars"))
        no_ask = _parse_decimal(m.get("no_ask_dollars"))
        if yes_ask is None or no_ask is None:
            skipped_quality += 1
            continue
        american_yes = yes_to_american(yes_ask)
        american_no = yes_to_american(no_ask)
        if american_yes is None or american_no is None:
            skipped_quality += 1
            continue

        floor = m.get("floor_strike")
        try:
            floor_f = float(floor) if floor is not None else None
        except (TypeError, ValueError):
            floor_f = None
        if floor_f is None:
            skipped_quality += 1
            continue

        base = {
            "event_id": matched["event_id"],
            "sport_key": sport_key,
            "home_team": matched["home_team"],
            "away_team": matched["away_team"],
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }

        # WS bookkeeping — same market_ticker for both sides; ws_side
        # distinguishes which ask we pull from incoming ticker messages.
        mt = m.get("ticker")

        if kind == "total":
            # Pure Over/Under — no team-side encoding.
            rows.append({
                **base, "market_key": market_key,
                "outcome_name": "Over",  "outcome_point": floor_f,
                "price_american": american_yes,
                "_market_ticker": mt, "_ws_side": "yes",
            })
            rows.append({
                **base, "market_key": market_key,
                "outcome_name": "Under", "outcome_point": floor_f,
                "price_american": american_no,
                "_market_ticker": mt, "_ws_side": "no",
            })
            continue

        # spread + team_total need the YES team's code from the suffix.
        raw_suffix = _team_code_from_ticker(m.get("ticker") or "") or ""
        yes_code = _strip_strike_index(raw_suffix)
        yes_canon = code_to_canon.get(yes_code)
        if not yes_canon:
            skipped_unknown_team += 1
            continue
        # The OTHER team's canonical: whichever code in code_to_canon isn't
        # `yes_code`.
        other_canon = None
        for code, canon in code_to_canon.items():
            if code != yes_code:
                other_canon = canon
                break
        if other_canon is None:
            skipped_unknown_team += 1
            continue

        if kind == "spread":
            # YES = "this team wins by > floor_strike runs/points". They're
            # laying floor_strike → outcome_point = -floor. The OTHER team
            # is the underdog spread → outcome_point = +floor.
            rows.append({
                **base, "market_key": market_key,
                "outcome_name": yes_canon,   "outcome_point": -floor_f,
                "price_american": american_yes,
                "_market_ticker": mt, "_ws_side": "yes",
            })
            rows.append({
                **base, "market_key": market_key,
                "outcome_name": other_canon, "outcome_point": floor_f,
                "price_american": american_no,
                "_market_ticker": mt, "_ws_side": "no",
            })
        elif kind == "team_total":
            rows.append({
                **base, "market_key": market_key,
                "outcome_name": f"{yes_canon} Over",
                "outcome_point": floor_f,
                "price_american": american_yes,
                "_market_ticker": mt, "_ws_side": "yes",
            })
            rows.append({
                **base, "market_key": market_key,
                "outcome_name": f"{yes_canon} Under",
                "outcome_point": floor_f,
                "price_american": american_no,
                "_market_ticker": mt, "_ws_side": "no",
            })
        else:
            # Unknown kind — defensive.
            continue

    if skipped_quality or skipped_decomp or skipped_unknown_team or orphans or live:
        logger.info(
            "kalshi %s %s: %d rows, %d events, %d orphans, %d live, "
            "%d quality-skipped, %d unknown-team, %d decomp-fail",
            sport_key, market_key, len(rows), len(event_cache), orphans, live,
            skipped_quality, skipped_unknown_team, skipped_decomp,
        )
    return rows


# ──────────────────────────────────────────────────────────────────────
# RFI (no-run-first-inning, MLB only)
# ──────────────────────────────────────────────────────────────────────


def _normalize_rfi_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """KXMLBRFI: one binary market per event. YES = 1st-inning run scored
    (YRFI), NO = no 1st-inning run (NRFI). Cache market_key = 'nrfi' with
    outcome_name "Yes"/"No" — matches what Odds API populates for the
    nrfi market.
    """
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)

    if series_ticker is None:
        for m in markets:
            et = m.get("event_ticker") or ""
            if "-" in et:
                series_ticker = et.split("-", 1)[0]
                break

    rows: list[dict] = []
    skipped_quality = 0
    orphans = 0
    live = 0

    for m in markets:
        event_ticker = m.get("event_ticker") or ""
        if not event_ticker:
            continue

        resolved = _resolve_event(
            event_ticker, series_ticker or "", sport_key, code_map,
            match_event, now, use_team_pair_decomp=True,
        )
        if resolved is None:
            tdec = _parse_event_ticker_commence(event_ticker, series_ticker or "")
            if tdec is not None and tdec[1] and tdec[0] <= now:
                live += 1
            else:
                orphans += 1
            continue
        matched, commence, _code_to_canon = resolved

        # RFI uses the h2h quality filter (binary market — overround logic
        # is the right gate).
        if not _market_passes_quality(m):
            skipped_quality += 1
            continue
        yes_ask = _parse_decimal(m.get("yes_ask_dollars"))
        no_ask = _parse_decimal(m.get("no_ask_dollars"))
        if yes_ask is None or no_ask is None:
            skipped_quality += 1
            continue
        american_yes = yes_to_american(yes_ask)
        american_no = yes_to_american(no_ask)
        if american_yes is None or american_no is None:
            skipped_quality += 1
            continue

        base = {
            "event_id": matched["event_id"],
            "sport_key": sport_key,
            "home_team": matched["home_team"],
            "away_team": matched["away_team"],
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }
        mt = m.get("ticker")
        rows.append({
            **base, "market_key": "nrfi",
            "outcome_name": "Yes", "outcome_point": None,
            "price_american": american_yes,
            "_market_ticker": mt, "_ws_side": "yes",
        })
        rows.append({
            **base, "market_key": "nrfi",
            "outcome_name": "No",  "outcome_point": None,
            "price_american": american_no,
            "_market_ticker": mt, "_ws_side": "no",
        })

    if skipped_quality or orphans or live:
        logger.info(
            "kalshi %s nrfi: %d rows, %d markets, %d orphans, %d live, "
            "%d quality-skipped",
            sport_key, len(rows), len(markets), orphans, live, skipped_quality,
        )
    return rows


# ──────────────────────────────────────────────────────────────────────
# F5 3-way winner (MLB only)
# ──────────────────────────────────────────────────────────────────────


def _normalize_f5_winner_markets(
    markets: list[dict],
    series_ticker: str | None,
    sport_key: str,
    market_key: str,
    fetched_at: datetime,
    match_event: Callable[..., dict | None],
) -> list[dict]:
    """KXMLBF5: 3-way per event (Tie / TeamA / TeamB) — 3 markets per event.
    Each is one binary YES/NO on a single outcome.

    Emit ONE row per market on the YES side only (the NO side prices the
    "anything else happens" outcome, which isn't a meaningful 3-way line).

    Outcome canonicalization:
      - The "Tie" market's YES outcome → literal string `"Draw"` (matches
        Odds API 3-way convention).
      - Each team-suffixed market's YES outcome → that team's canonical
        Odds API name.
    """
    code_map = TEAM_CODE_TO_CANONICAL.get(sport_key, {})
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)

    if series_ticker is None:
        for m in markets:
            et = m.get("event_ticker") or ""
            if "-" in et:
                series_ticker = et.split("-", 1)[0]
                break

    # Resolve each event once (use team-pair decomp from event_ticker).
    event_cache: dict[str, tuple[dict, datetime, dict[str, str]] | None] = {}

    rows: list[dict] = []
    skipped_quality = 0
    orphans = 0
    live = 0
    skipped_unknown = 0

    for m in markets:
        event_ticker = m.get("event_ticker") or ""
        if not event_ticker:
            continue

        if event_ticker not in event_cache:
            event_cache[event_ticker] = _resolve_event(
                event_ticker, series_ticker or "", sport_key, code_map,
                match_event, now, use_team_pair_decomp=True,
            )
        resolved = event_cache[event_ticker]
        if resolved is None:
            tdec = _parse_event_ticker_commence(event_ticker, series_ticker or "")
            if tdec is not None and tdec[1] and tdec[0] <= now:
                live += 1
            else:
                orphans += 1
            continue
        matched, commence, code_to_canon = resolved

        # F5 3-way quality: only require non-trivial yes_ask. No overround
        # check (3 markets sum to ~1.0 across the event, not per-market).
        if (m.get("status") or "").lower() != "active":
            skipped_quality += 1
            continue
        yes_ask = _parse_decimal(m.get("yes_ask_dollars"))
        if yes_ask is None or yes_ask <= F5_3WAY_MIN_YES_ASK:
            skipped_quality += 1
            continue
        american = yes_to_american(yes_ask)
        if american is None:
            skipped_quality += 1
            continue

        raw_suffix = _team_code_from_ticker(m.get("ticker") or "") or ""
        if raw_suffix.upper() == "TIE":
            outcome_name = "Draw"
        else:
            # Suffix is a team code (no strike index on winner markets).
            outcome_name = code_to_canon.get(raw_suffix)
            if not outcome_name:
                skipped_unknown += 1
                continue

        rows.append({
            "event_id": matched["event_id"],
            "sport_key": sport_key,
            "home_team": matched["home_team"],
            "away_team": matched["away_team"],
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "market_key": market_key,
            "outcome_name": outcome_name,
            "outcome_point": None,
            "price_american": american,
            "fetched_at": fetched_at,
            "_market_ticker": m.get("ticker"),
            "_ws_side": "yes",
        })

    if skipped_quality or orphans or live or skipped_unknown:
        logger.info(
            "kalshi %s %s: %d rows, %d events, %d orphans, %d live, "
            "%d quality-skipped, %d unknown",
            sport_key, market_key, len(rows), len(event_cache), orphans, live,
            skipped_quality, skipped_unknown,
        )
    return rows


# ──────────────────────────────────────────────────────────────────────
# Quality gates
# ──────────────────────────────────────────────────────────────────────


def _market_passes_quality(m: dict) -> bool:
    """Per-market gate for h2h / RFI (binary markets where overround is
    meaningful). Returns False if the market should be discarded."""
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


def _alt_market_passes_quality(m: dict) -> bool:
    """Stricter gate for alt-line markets (spreads / totals / team_totals
    / F5 spread / F5 total).

    Many extreme Kalshi alts show yes_ask=0.01 / no_ask=1.00 — overround
    sums to 1.01 and passes `_market_passes_quality`, but the prices are
    not real two-sided quotes. Drop those.
    """
    if (m.get("status") or "").lower() != "active":
        return False
    yes_ask = _parse_decimal(m.get("yes_ask_dollars"))
    no_ask = _parse_decimal(m.get("no_ask_dollars"))
    if yes_ask is None or no_ask is None:
        return False
    if yes_ask < ALT_MIN_ASK or no_ask < ALT_MIN_ASK:
        return False
    if (yes_ask + no_ask) < ALT_MIN_SUM:
        return False
    # We don't bound an UPPER overround for alts because many legit alts
    # near the median price as ~0.5/0.5 — overround ~1.0 — and extreme
    # alts have wider but still actionable spreads.
    return True
