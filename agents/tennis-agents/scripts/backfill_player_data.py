"""One-time backfill of 2025+ match data into the local Sackmann archive.

Loops date-by-date over the specified range, calls ``sync_matches_day`` for
each tour. Idempotent — existing ``(tourney_id, match_num)`` rows are
skipped. Safe to rerun if interrupted.

Usage:
    python3 scripts/backfill_player_data.py                # 2025-01-01 → yesterday
    python3 scripts/backfill_player_data.py --start 2025-01-01 --end 2025-12-31
    python3 scripts/backfill_player_data.py --tour atp
"""
import argparse
import logging
import sys
import time
from datetime import date, timedelta

# Ensure repo root is on sys.path so ``config``/``scrapers`` import works.
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrapers.sackmann_sync import sync_matches_day, sync_rankings  # noqa: E402

logger = logging.getLogger("mirofish.backfill")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=_parse_date, default=date(2025, 1, 1),
                        help="Start date (YYYY-MM-DD). Default: 2025-01-01")
    parser.add_argument("--end", type=_parse_date,
                        default=date.today() - timedelta(days=1),
                        help="End date (YYYY-MM-DD). Default: yesterday")
    parser.add_argument("--tour", choices=["atp", "wta", "both"], default="both",
                        help="Tour to backfill. Default: both")
    parser.add_argument("--sleep", type=float, default=0.5,
                        help="Seconds to sleep between API calls. Default: 0.5")
    parser.add_argument("--refresh-rankings", action="store_true",
                        help="Also refresh current rankings at the end.")
    args = parser.parse_args()

    if args.start > args.end:
        print(f"ERROR: --start {args.start} is after --end {args.end}", file=sys.stderr)
        sys.exit(1)

    tours = ["atp", "wta"] if args.tour == "both" else [args.tour]
    total_days = (args.end - args.start).days + 1
    total_calls = total_days * len(tours)

    print(f"\n=== Backfill: {args.start} → {args.end}, tours={tours} ===")
    print(f"  Estimated: {total_days} days × {len(tours)} tour(s) = {total_calls} API calls")
    print(f"  Sleep between calls: {args.sleep}s ≈ ETA {int(total_calls * (args.sleep + 0.5) / 60)} min")
    print()

    grand_total = 0
    call_idx = 0
    start_time = time.time()

    for d in _daterange(args.start, args.end):
        for tour in tours:
            call_idx += 1
            date_str = d.isoformat()
            try:
                new_rows = sync_matches_day(date_str, tour)
                grand_total += new_rows
                if new_rows > 0:
                    print(f"  [{call_idx}/{total_calls}] {date_str} {tour.upper()}: +{new_rows} rows")
            except Exception as e:
                logger.error("%s %s failed: %s", date_str, tour, e)
            time.sleep(args.sleep)

    elapsed = time.time() - start_time
    print(f"\n=== Backfill complete: {grand_total} new rows in {int(elapsed)}s ===")

    if args.refresh_rankings:
        print("\nRefreshing rankings...")
        for tour in tours:
            sync_rankings(tour)


if __name__ == "__main__":
    main()
