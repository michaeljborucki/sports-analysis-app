"""Unified bet ledger — DB layer.

One table, one row per (source_book, external_id). All four sync
paths (coral33 mirror, kalshi sync, polymarket sync, CSV import)
write rows in the same shape. CLV is NEVER stored here — it's
computed at query time by `lookup_clv_for_bet` against the existing
`closing_lines` table.
"""
from __future__ import annotations

from dataclasses import dataclass, replace as _replace
from datetime import datetime
from typing import Iterable

from .cache import OddsCache


@dataclass(frozen=True)
class BetRow:
    source_book: str
    external_id: str
    customer_id: str | None
    accepted_at: datetime
    settled_at: datetime | None
    status: str
    wager_type: str
    total_picks: int
    sport_key: str | None
    event_id: str | None
    home_team: str | None
    away_team: str | None
    market_key: str | None
    outcome_name: str | None
    outcome_point: float
    odds_american: int | None
    stake: float
    to_win: float | None
    settled_amount: float | None
    is_free_play: bool
    raw_description: str | None
    imported_at: datetime | None

    def replace(self, **kwargs) -> "BetRow":
        return _replace(self, **kwargs)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if isinstance(dt, datetime) else str(dt)


def upsert_bets(cache: OddsCache, rows: Iterable[BetRow]) -> int:
    """Idempotent upsert on (source_book, external_id).

    On conflict, status / settled_at / settled_amount / odds_american /
    stake / to_win / total_picks update. accepted_at stays put.
    """
    rows = list(rows)
    if not rows:
        return 0
    prepared = [{
        "source_book": r.source_book,
        "external_id": r.external_id,
        "customer_id": r.customer_id,
        "accepted_at": _iso(r.accepted_at),
        "settled_at": _iso(r.settled_at),
        "status": r.status,
        "wager_type": r.wager_type,
        "total_picks": r.total_picks,
        "sport_key": r.sport_key,
        "event_id": r.event_id,
        "home_team": r.home_team,
        "away_team": r.away_team,
        "market_key": r.market_key,
        "outcome_name": r.outcome_name,
        "outcome_point": float(r.outcome_point),
        "odds_american": r.odds_american,
        "stake": float(r.stake),
        "to_win": r.to_win,
        "settled_amount": r.settled_amount,
        "is_free_play": 1 if r.is_free_play else 0,
        "raw_description": r.raw_description,
        "imported_at": _iso(r.imported_at),
    } for r in rows]
    with cache._conn() as c:
        c.executemany(
            """
            INSERT INTO bets (
              source_book, external_id, customer_id, accepted_at, settled_at, status,
              wager_type, total_picks, sport_key, event_id,
              home_team, away_team, market_key, outcome_name,
              outcome_point, odds_american, stake, to_win,
              settled_amount, is_free_play, raw_description, imported_at
            ) VALUES (
              :source_book, :external_id, :customer_id, :accepted_at, :settled_at, :status,
              :wager_type, :total_picks, :sport_key, :event_id,
              :home_team, :away_team, :market_key, :outcome_name,
              :outcome_point, :odds_american, :stake, :to_win,
              :settled_amount, :is_free_play, :raw_description, :imported_at
            )
            ON CONFLICT(source_book, external_id) DO UPDATE SET
              settled_at      = excluded.settled_at,
              status          = excluded.status,
              total_picks     = excluded.total_picks,
              odds_american   = excluded.odds_american,
              stake           = excluded.stake,
              to_win          = excluded.to_win,
              settled_amount  = excluded.settled_amount,
              market_key      = excluded.market_key,
              outcome_name    = excluded.outcome_name,
              outcome_point   = excluded.outcome_point,
              event_id        = excluded.event_id,
              sport_key       = excluded.sport_key,
              home_team       = excluded.home_team,
              away_team       = excluded.away_team
            """,
            prepared,
        )
    return len(prepared)


def query_bets(
    cache: OddsCache,
    *,
    book: str | None = None,
    sport: str | None = None,
    status: str | None = None,
    market_key: str | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Filtered bet list. All filters AND together. Sorted by
    accepted_at DESC."""
    q = "SELECT * FROM bets WHERE 1=1"
    args: list = []
    if book is not None:
        q += " AND source_book = ?"; args.append(book)
    if sport is not None:
        q += " AND sport_key = ?"; args.append(sport)
    if status is not None:
        q += " AND status = ?"; args.append(status)
    if market_key is not None:
        q += " AND market_key = ?"; args.append(market_key)
    if from_iso is not None:
        q += " AND accepted_at >= ?"; args.append(from_iso)
    if to_iso is not None:
        q += " AND accepted_at < ?"; args.append(to_iso)
    q += " ORDER BY accepted_at DESC"
    if limit is not None:
        q += " LIMIT ?"; args.append(int(limit))
    with cache._conn() as c:
        return [dict(r) for r in c.execute(q, args)]
