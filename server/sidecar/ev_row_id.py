"""Canonical row identifier for /api/ev opportunities.

Format: f"{event_id}|{market_kind}|{point or ''}|{outcome_name}|{book}"

Strict: no field may contain a literal '|'. event_id and outcome_name in
Odds-API data don't contain pipes today, but we validate to avoid silent
ambiguity if that ever changes."""
from __future__ import annotations


SEP = "|"


def build_ev_row_id(
    *,
    event_id: str,
    market_kind: str,
    point: float | None,
    outcome_name: str,
    book: str,
) -> str:
    for name, val in [
        ("event_id", event_id), ("market_kind", market_kind),
        ("outcome_name", outcome_name), ("book", book),
    ]:
        if SEP in val:
            raise ValueError(f"{name} contains '{SEP}': {val!r}")
    point_str = "" if point is None else f"{point:g}"
    return SEP.join([event_id, market_kind, point_str, outcome_name, book])


def parse_ev_row_id(rid: str) -> dict:
    parts = rid.split(SEP)
    if len(parts) != 5:
        raise ValueError(f"malformed ev_row_id (expected 5 parts): {rid!r}")
    event_id, market_kind, point_str, outcome_name, book = parts
    return {
        "event_id": event_id,
        "market_kind": market_kind,
        "point": float(point_str) if point_str else None,
        "outcome_name": outcome_name,
        "book": book,
    }
