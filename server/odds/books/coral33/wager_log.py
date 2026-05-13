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


# Coral33's server timestamps are in America/Denver (MDT/MST). Same fix
# we applied in the line normalizer — reuse here for wager timestamps.
try:
    from zoneinfo import ZoneInfo
    _CORAL_TZ = ZoneInfo("America/Denver")
except Exception:
    _CORAL_TZ = timezone(-timedelta(hours=6))  # MDT fallback


@dataclass(frozen=True)
class WagerLogEntry:
    """One wager pulled from getWagersByFigureDate.

    `settled_at` is None when the wager is still open (WagerStatus == 'O').
    `amount_wagered` is in DOLLARS (the raw response is in cents — we
    convert here so the historical-pending sum is in dollars consistently
    with HistoryPoint.balance / .pending).
    """
    customer_id: str
    ticket_number: int
    accepted_at: datetime          # placement time, UTC
    settled_at: datetime | None    # None if still open; else figure-date midnight UTC
    amount_wagered: float          # dollars
    wager_status: str              # 'O' open | 'W' won | 'L' lost | 'P' push
    is_free_play: bool


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


def _parse_wager(row: dict, customer_id: str) -> WagerLogEntry | None:
    """Decode one row from the getWagersByFigureDate response."""
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
    is_fp = (row.get("FreePlayFlag") or "").upper() == "Y"
    return WagerLogEntry(
        customer_id=customer_id,
        ticket_number=ticket,
        accepted_at=accepted,
        settled_at=settled,
        amount_wagered=_to_dollars(row.get("AmountWagered")),
        wager_status=status,
        is_free_play=is_fp,
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
    backfill has happened yet (caller should fetch). Returns [] if the
    backfill ran but found no wagers."""
    path = _path_for(customer_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("wager_log: bad cache file %s: %s", path, e)
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
                amount_wagered=float(w["amount_wagered"]),
                wager_status=w.get("wager_status", "O"),
                is_free_play=bool(w.get("is_free_play", False)),
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
    by_ticket: dict[int, WagerLogEntry] = {}

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
                wager = _parse_wager(row, cred.customer_id)
                if wager is None:
                    continue
                # Dedupe by ticket — open wagers come back on every day's
                # call, and the same graded wager can appear on adjacent
                # figure dates depending on coral's grouping.
                by_ticket[wager.ticket_number] = wager

    return list(by_ticket.values())


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
