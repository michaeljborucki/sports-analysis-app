"""CSV → BetRow translator.

Format (header row required):
  date,book,sport,event,market,side,odds,stake,result

  date    YYYY-MM-DD or ISO datetime
  book    free text (preserved in raw_description; source_book is
          always 'imported' for CSV rows)
  sport   our internal sport_key (mlb, nba, ...)
  event   free text matchup, optional
  market  market_key-ish ('h2h', 'spreads -1.5', 'totals 8.5', 'player_points')
  side    team name / Over / Under / player name + O/U
  odds    American odds, e.g. -145 or +155
  stake   dollars
  result  W | L | P | void | pending

Rows whose required fields are missing or unparseable are returned in
the `errors` list. Good rows are still returned.
"""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from typing import TextIO

from .bets import BetRow


REQUIRED_COLUMNS = ("date", "book", "sport", "market", "side", "odds", "stake", "result")

_RESULT_STATUS = {
    "W": "win", "L": "loss", "P": "push",
    "void": "void", "pending": "pending",
    "w": "win", "l": "loss", "p": "push",
}


def _parse_odds(s: str) -> int:
    return int(s.strip().lstrip("+"))


def _parse_date(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _external_id(date_s: str, book: str, sport: str, event: str,
                 side: str, odds: str, stake: str) -> str:
    payload = "|".join((date_s, book, sport, event, side, odds, stake)).encode()
    return hashlib.sha1(payload).hexdigest()[:16]


def parse_csv_to_bet_rows(stream: TextIO) -> tuple[list[BetRow], list[dict]]:
    """Parse a CSV stream. Returns (good_rows, errors). Errors is a
    list of {row: int (1-indexed, header=row 1), reason: str}."""
    reader = csv.DictReader(stream)
    if reader.fieldnames is None or not set(REQUIRED_COLUMNS).issubset({c.strip() for c in reader.fieldnames}):
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        return [], [{"row": 1, "reason": f"missing required columns: {sorted(missing)}"}]

    good: list[BetRow] = []
    errors: list[dict] = []
    now = datetime.now(timezone.utc)

    for i, raw in enumerate(reader, start=2):
        try:
            book = raw["book"].strip()
            sport = raw["sport"].strip()
            event = (raw.get("event") or "").strip()
            market = raw["market"].strip()
            side = raw["side"].strip()
            stake_s = raw["stake"].strip()
            odds_s = raw["odds"].strip()
            result_s = raw["result"].strip()
            date_s = raw["date"].strip()
            stake = float(stake_s)
            odds = _parse_odds(odds_s)
            accepted_at = _parse_date(date_s)
        except (KeyError, ValueError, AttributeError) as e:
            errors.append({"row": i, "reason": f"parse error: {e}"})
            continue

        status = _RESULT_STATUS.get(result_s)
        if status is None:
            errors.append({"row": i, "reason": f"invalid result '{result_s}'"})
            continue

        parts = market.split()
        market_key = parts[0] if parts else market
        outcome_point = 0.0
        if len(parts) > 1:
            try:
                outcome_point = float(parts[1])
            except ValueError:
                outcome_point = 0.0

        good.append(BetRow(
            source_book="imported",
            external_id=_external_id(date_s, book, sport, event, side, odds_s, stake_s),
            customer_id=None,
            accepted_at=accepted_at,
            settled_at=None,
            status=status,
            wager_type="straight",
            total_picks=1,
            sport_key=sport,
            event_id=None,
            home_team=None,
            away_team=None,
            market_key=market_key,
            outcome_name=side,
            outcome_point=outcome_point,
            odds_american=odds,
            stake=stake,
            to_win=None,
            settled_amount=None,
            is_free_play=False,
            raw_description=event or f"{book}: {market} {side}",
            imported_at=now,
        ))
    return good, errors
