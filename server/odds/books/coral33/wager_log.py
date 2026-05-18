"""Historical wager-log scanner for Coral33.

Backs `/api/coral33/accounts/history`'s historical-pending field. Coral33's
daily-figures endpoint only carries the CURRENT pending balance (same value
returned for every week offset), so the only way to reconstruct true EOD
pending for past days is to walk the wager log.

Endpoint: `getWagersByFigureDate` (Report tier). Param trio cracked from the
live JS at `https://coral33.com/app/sports/report/report.js`:

    POST /cloud/api/Report/getWagersByFigureDate
    body: {
        customerID:  <padded>,
        figureDate:  "YYYY-MM-DD",     # specific day within the week
        graded:      "0",              # 0 returns the page's full wager set
        week:        "0..N",           # 0 = current week, 1 = last, ...
        operation:   "getWagersByFigureDate",
    }

Note: empirically `graded=0` returns BOTH open and settled wagers for the
day; `graded=1` returns only the graded subset; `graded=3` (the JS default
for "no specific graded filter") returns nothing on the customer JWT. Use
`0` — it's the most generous and is what the live UI uses.

Algorithm for historical pending on date D:
    1. Pull wagers from every figure date in the window via this endpoint.
    2. Each wager has AcceptedDateTime (placement) + DailyFigureDate
       (settlement day, or "open" if WagerStatus == 'O').
    3. pending(D, customer) = sum(amount_wagered for w in wagers
                                  where w.customer_id == customer
                                    AND w.accepted_at <= D
                                    AND (w.settled_at is None OR w.settled_at > D)
                                    AND not w.is_free_play)
    4. Sum across customers for the "All accounts" total series.

Settled wagers are immutable so the wager log is cache-friendly. Only the
trailing few days need re-fetching to pick up newly-graded wagers.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .accounts import AccountCredential
from .client import Coral33APIError, Coral33AuthError, Coral33Client


logger = logging.getLogger(__name__)


# Per-account wager-log persistence directory. JSON-per-customer so the
# backfill survives backend restarts — without this the 2-week pull would
# repeat on every boot. Files are local-state-only (gitignored).
_WAGER_LOG_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "coral33_wager_log"
)


# Default backfill window. Kept tight (2 weeks) because the one-time
# backfill is the only API hit — chart loads after that read from the
# persisted JSON. 2 weeks is enough to cover the typical lifecycle of a
# pending bet plus a reasonable historical window for the chart.
DEFAULT_BACKFILL_WEEKS = 2


# Schema version for the persisted JSON files. Bump when WagerLogEntry
# fields change so older files trigger an automatic re-backfill (the
# loader returns None on mismatch, which the scraper treats as a cache
# miss). v2 added wager_type / total_picks / per-leg market detail used
# by the /bets endpoint and the bets-history sub-tab.
WAGER_LOG_SCHEMA_VERSION = 2


# Coral33's server timestamps are in America/Denver (MDT/MST). Same fix
# we applied in the line normalizer — reuse here for wager timestamps.
try:
    from zoneinfo import ZoneInfo
    _CORAL_TZ = ZoneInfo("America/Denver")
except Exception:
    _CORAL_TZ = timezone(-timedelta(hours=6))  # MDT fallback


@dataclass(frozen=True)
class WagerLogEntry:
    """One TICKET pulled from getWagersByFigureDate.

    Coral33's response carries one row per LEG, so a 3-leg parlay arrives
    as 3 rows sharing TicketNumber + WagerNumber. We collapse to one
    entry per ticket by keeping only the head leg (lowest PlayNumber) —
    its market detail (team, line, odds) represents the ticket on the
    bet-history view. The ticket-level fields (amount_wagered, to_win,
    status) cover the whole bet regardless of leg count.

    `settled_at` is None when the wager is still open. Money fields are
    in DOLLARS (raw response is cents — converted here so consumers
    don't have to remember).
    """
    # ── Ticket-level identity ──────────────────────────────────────────
    customer_id: str
    ticket_number: int
    accepted_at: datetime
    settled_at: datetime | None
    wager_status: str               # 'O' open | 'W' won | 'L' lost | 'P' push | 'X' (rare; cancelled/void)
    wager_type: str                 # 'S' straight | 'P' parlay | 'T' teaser | 'I' if-bet | 'R' round-robin | 'M' money-line single
    total_picks: int                # 1 for straight, N for parlay/teaser

    # ── Ticket-level money ─────────────────────────────────────────────
    amount_wagered: float           # ticket stake (NOT per-leg share)
    to_win_amount: float            # ticket payout if all legs win
    amount_won: float               # actual realized winnings (0 if open or lost)
    amount_lost: float              # actual realized losses (0 if open or won)
    is_free_play: bool

    # ── Head-leg market detail ─────────────────────────────────────────
    # First-leg only per user request; for parlays the other legs are
    # discarded at parse time. These map directly to Coral33's per-row
    # fields on the head leg.
    sport_type: str | None          # e.g. 'Basketball'
    sport_sub_type: str | None      # e.g. 'NBA'
    period: str | None              # e.g. 'Game', '1st Half'
    team1_id: str | None            # away team (coral convention)
    team2_id: str | None            # home team (coral convention)
    chosen_team_id: str | None      # which side the bettor took
    description: str | None         # raw market description string
    final_money: int | None         # American odds at acceptance
    adj_spread: float | None        # signed spread (for spread bets)
    adj_total_points: float | None  # over/under line (for totals bets)


def _parse_wager_datetime(s: str | None) -> datetime | None:
    """coral33 returns naive timestamps like '2026-05-06 13:26:50.343' in
    America/Denver. Parse, attach the TZ, normalize to UTC. Returns None on
    empty / unparseable input."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # Drop fractional seconds + normalize the separator for fromisoformat.
    if "." in s:
        s = s.split(".")[0]
    s = s.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CORAL_TZ)
    return dt.astimezone(timezone.utc)


def _parse_figure_date(s: str | None) -> datetime | None:
    """DailyFigureDate ships as e.g. '2026-05-08 00:00:00.000'. We treat
    the figure date as 23:59:59 of that day in coral33's timezone — the
    end-of-day cutoff for "was this wager settled by EOD?"
    """
    if not s:
        return None
    base = s.strip().split(" ")[0]
    try:
        d = date.fromisoformat(base)
    except ValueError:
        return None
    # End of figure date in coral's local timezone.
    dt = datetime.combine(d, datetime.max.time().replace(microsecond=0))
    return dt.replace(tzinfo=_CORAL_TZ).astimezone(timezone.utc)


def _to_dollars(cents) -> float:
    """coral33 stores money fields as cents (int). Return float dollars."""
    try:
        return float(cents) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _str_or_none(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _float_or_none(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int_or_none(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_wager(row: dict, customer_id: str) -> WagerLogEntry | None:
    """Decode one row from the getWagersByFigureDate response into a
    ticket-level WagerLogEntry. Returns None when the row can't be
    identified as a wager. For parlays this is one row per LEG; the
    caller deduplicates by ticket_number and keeps the head leg only."""
    try:
        ticket = int(row.get("TicketNumber") or 0)
    except (TypeError, ValueError):
        return None
    if ticket <= 0:
        return None
    accepted = _parse_wager_datetime(row.get("AcceptedDateTime"))
    if accepted is None:
        return None
    status = (row.get("WagerStatus") or "").strip().upper()
    if status == "O":
        settled: datetime | None = None
    else:
        # Graded — figure date is the settlement day.
        settled = _parse_figure_date(row.get("DailyFigureDate"))
        # Defensive: if we can't parse the settle date but we know it's
        # graded, treat it as settled "now" so it doesn't linger as open
        # in past-day pending sums.
        if settled is None:
            settled = accepted
    wager_type = (row.get("WagerType") or "").strip().upper() or "S"
    try:
        total_picks = int(row.get("TotalPicks") or 1)
    except (TypeError, ValueError):
        total_picks = 1
    is_fp = (row.get("FreePlayFlag") or "").upper() == "Y"
    return WagerLogEntry(
        customer_id=customer_id,
        ticket_number=ticket,
        accepted_at=accepted,
        settled_at=settled,
        wager_status=status,
        wager_type=wager_type,
        total_picks=total_picks,
        amount_wagered=_to_dollars(row.get("AmountWagered")),
        to_win_amount=_to_dollars(row.get("ToWinAmount")),
        amount_won=_to_dollars(row.get("AmountWon")),
        amount_lost=_to_dollars(row.get("AmountLost")),
        is_free_play=is_fp,
        sport_type=_str_or_none(row.get("SportType")),
        sport_sub_type=_str_or_none(row.get("SportSubType")),
        period=_str_or_none(row.get("PeriodDescription")),
        team1_id=_str_or_none(row.get("Team1ID")),
        team2_id=_str_or_none(row.get("Team2ID")),
        chosen_team_id=_str_or_none(row.get("ChosenTeamID")),
        description=_str_or_none(row.get("Description")),
        final_money=_int_or_none(row.get("FinalMoney")),
        adj_spread=_float_or_none(row.get("AdjSpread")),
        adj_total_points=_float_or_none(row.get("AdjTotalPoints")),
    )


# ─────────────────────── JSON persistence ────────────────────────


def _path_for(customer_id: str) -> Path:
    """JSON file location for one customer's wager log."""
    safe = "".join(c if c.isalnum() else "_" for c in customer_id.strip())
    return _WAGER_LOG_DIR / f"{safe}.json"


def save_wager_log(
    customer_id: str, wagers: list[WagerLogEntry], weeks_back: int,
) -> None:
    """Persist a customer's wager log to JSON. Overwrites any prior file."""
    _WAGER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(customer_id)
    payload = {
        "schema_version": WAGER_LOG_SCHEMA_VERSION,
        "customer_id": customer_id,
        "weeks_back": weeks_back,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "wagers": [
            {
                **asdict(w),
                "accepted_at": w.accepted_at.isoformat(),
                "settled_at": w.settled_at.isoformat() if w.settled_at else None,
            }
            for w in wagers
        ],
    }
    # Atomic write — rename after write so a crash doesn't leave a half-
    # written file that fails to load on next boot.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def load_wager_log(customer_id: str) -> list[WagerLogEntry] | None:
    """Read the persisted wager log for a customer. Returns None if no
    backfill has happened yet OR if the file is from an older schema
    version (the scraper treats both as a cache miss and re-fetches).
    Returns [] if the backfill ran but found no wagers."""
    path = _path_for(customer_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("wager_log: bad cache file %s: %s", path, e)
        return None
    # Schema-version gate — older v1 files are missing wager_type /
    # total_picks / market-detail fields, so we trigger a re-backfill
    # instead of trying to read them with .get(... default).
    if payload.get("schema_version") != WAGER_LOG_SCHEMA_VERSION:
        logger.info(
            "wager_log: schema mismatch for %s (have v%s, need v%s) — "
            "will re-backfill",
            customer_id, payload.get("schema_version"), WAGER_LOG_SCHEMA_VERSION,
        )
        return None
    out: list[WagerLogEntry] = []
    for w in payload.get("wagers") or []:
        try:
            accepted = datetime.fromisoformat(w["accepted_at"])
            settled = (
                datetime.fromisoformat(w["settled_at"])
                if w.get("settled_at") else None
            )
            out.append(WagerLogEntry(
                customer_id=w["customer_id"],
                ticket_number=int(w["ticket_number"]),
                accepted_at=accepted,
                settled_at=settled,
                wager_status=w.get("wager_status", "O"),
                wager_type=w.get("wager_type", "S"),
                total_picks=int(w.get("total_picks", 1)),
                amount_wagered=float(w["amount_wagered"]),
                to_win_amount=float(w.get("to_win_amount", 0.0)),
                amount_won=float(w.get("amount_won", 0.0)),
                amount_lost=float(w.get("amount_lost", 0.0)),
                is_free_play=bool(w.get("is_free_play", False)),
                sport_type=w.get("sport_type"),
                sport_sub_type=w.get("sport_sub_type"),
                period=w.get("period"),
                team1_id=w.get("team1_id"),
                team2_id=w.get("team2_id"),
                chosen_team_id=w.get("chosen_team_id"),
                description=w.get("description"),
                final_money=w.get("final_money"),
                adj_spread=w.get("adj_spread"),
                adj_total_points=w.get("adj_total_points"),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning("wager_log: skipping malformed entry: %s", e)
            continue
    return out


# ─────────────────────── Fetcher ─────────────────────────────────


async def fetch_account_wager_log(
    cred: AccountCredential,
    weeks_back: int = DEFAULT_BACKFILL_WEEKS,
) -> list[WagerLogEntry]:
    """Pull every wager for one account across the last `weeks_back` weeks.

    Strategy: iterate week × day, calling getWagersByFigureDate per day.
    Each call returns the day's settled wagers PLUS the customer's
    currently-open wagers (which appear with WagerStatus='O' regardless of
    figureDate — empirically the endpoint always includes them on every
    day's response). We dedupe by TicketNumber to avoid double-counting.

    Cost: weeks_back × 7 calls per account (~84 for 12 weeks). At 200ms/
    call that's ~17s per account, run-once-then-cache.
    """
    client = Coral33Client(cred.customer_id, cred.password)
    try:
        await client.authenticate()
    except (Coral33AuthError, Coral33APIError) as e:
        logger.warning("wager_log auth failed for %s: %s", cred.customer_id, e)
        return []

    today = datetime.now(timezone.utc).date()

    # Coral33's response carries one row per LEG. For parlays/teasers a
    # single ticket arrives as N rows sharing TicketNumber. We collapse
    # to one WagerLogEntry per ticket by picking the LOWEST PlayNumber's
    # row as the "head leg" — its market detail (team, line, odds)
    # represents the ticket on the bet-history view, per the product
    # requirement that parlays only show their first leg.
    # `head_row` maps ticket → (lowest_play_number_seen, raw_row).
    head_row: dict[int, tuple[int, dict]] = {}

    def _consider(row: dict) -> None:
        try:
            ticket = int(row.get("TicketNumber") or 0)
        except (TypeError, ValueError):
            return
        if ticket <= 0:
            return
        try:
            play = int(row.get("PlayNumber") or 1)
        except (TypeError, ValueError):
            play = 1
        existing = head_row.get(ticket)
        if existing is None or play < existing[0]:
            head_row[ticket] = (play, row)

    # Iterate per-week (0 = current, 1 = last, ...). Within each week try
    # 7 figure dates spanning that week's date range. coral33 ignores
    # mismatched figureDate / week combos gracefully (returns an empty
    # INFO list), so a slightly over-broad sweep is fine.
    for week_offset in range(weeks_back):
        week_end = today - timedelta(days=week_offset * 7)
        week_start = week_end - timedelta(days=6)
        for day_offset in range(7):
            fd = week_start + timedelta(days=day_offset)
            if fd > today:
                continue
            try:
                resp = await client.post_form("getWagersByFigureDate", {
                    "figureDate": fd.strftime("%Y-%m-%d"),
                    "graded": "0",
                    "week": str(week_offset),
                    "RRO": "0",
                })
            except Coral33APIError as e:
                logger.warning(
                    "wager_log fetch failed for %s @ %s w=%d: %s",
                    cred.customer_id, fd, week_offset, e,
                )
                continue
            lst = resp.get("LIST") or {}
            infos = lst.get("INFO") if isinstance(lst, dict) else None
            if not isinstance(infos, list):
                continue
            for row in infos:
                _consider(row)

    # Build entries from the head-leg-per-ticket map.
    out: list[WagerLogEntry] = []
    for _ticket, (_play, row) in head_row.items():
        wager = _parse_wager(row, cred.customer_id)
        if wager is not None:
            out.append(wager)
    return out


def compute_pending_by_date(
    wager_log: Iterable[WagerLogEntry],
    dates: Iterable[date],
) -> dict[str, float]:
    """For each date D, sum dollars-at-risk on open wagers as of EOD D.

    A wager contributes to pending(D) iff:
      - It was placed on or before D (accepted_at <= EOD D, coral TZ), AND
      - It hadn't settled by D (settled_at > EOD D OR settled_at is None), AND
      - It's not a free play (free plays don't lock cash).

    Returns a dict keyed by `YYYY-MM-DD` (date.isoformat()) so the API
    layer can join directly against HistoryPoint.date.
    """
    log = [w for w in wager_log if not w.is_free_play and w.amount_wagered > 0]
    out: dict[str, float] = {}
    for d in dates:
        # End-of-day cutoff in coral33's timezone, normalized to UTC for
        # comparison with the parsed wager timestamps.
        cutoff = datetime.combine(
            d, datetime.max.time().replace(microsecond=0)
        ).replace(tzinfo=_CORAL_TZ).astimezone(timezone.utc)
        total = 0.0
        for w in log:
            if w.accepted_at > cutoff:
                continue
            if w.settled_at is not None and w.settled_at <= cutoff:
                continue
            total += w.amount_wagered
        out[d.isoformat()] = total
    return out
