"""Resolve an ev_row_id back into a LegSpec + Kelly% by re-reading the
current /api/ev output. Re-uses the live EV scanner (with TTL cache) so
the sidecar fires against the same snapshot the UI sees.

Returns None if the row is no longer present (line moved off best price,
event went off the board, etc.). The orchestrator surfaces a 404 in that
case.

TODO(D3/D4): This is a best-effort scaffold for Task F0. The final
integration depends on:
  - Task C1 landing `server/sidecar/models.LegSpec` (the dataclass mirroring
    the Coral33 insertWagerParlay per-leg payload).
  - Task D3 (or earlier) adding `OddsCache.get_event_row(event_id,
    market_kind, outcome_name, book)` — or an equivalent helper — that
    returns the raw cache row with Coral33-specific fields (sport_type,
    sport_sub_type, game_num, rot_num, price_numerator/denominator,
    game_datetime, etc.).
  - Task D4 wiring this resolver into POST /api/sidecar/place.

Until those land, this function imports lazily and falls back to a
partial LegSpec or None so the rest of the F0 surface (EVOpportunity
`ev_row_id` field) is unblocked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from server.sidecar.ev_row_id import parse_ev_row_id

if TYPE_CHECKING:
    from server.sidecar.models import LegSpec


def resolve_ev_row_to_leg(ev_row_id: str) -> tuple["LegSpec", float] | None:
    """Resolve a canonical ev_row_id back to (LegSpec, kelly_full_pct).

    Returns None if:
      - the row is no longer present in the current EV scan,
      - the LegSpec model isn't available yet (Task C1 pending), or
      - the cache lookup helper isn't available (Task D3 pending).
    """
    parsed = parse_ev_row_id(ev_row_id)

    # LegSpec is defined in Task C1 (server/sidecar/models.py). Until that
    # lands, we can't build a real LegSpec. Guard the import so this
    # module is still importable for the ev_row_id parse/build surface.
    try:
        from server.sidecar.models import LegSpec  # noqa: F401
    except ImportError:
        # TODO(C1): Once models.py exists, this branch goes away.
        return None

    # Find the matching row by re-running the EV scanner against the
    # current cache snapshot. We use the same code path /api/ev uses;
    # the TTL memo on that endpoint means a sidecar place call inside the
    # 20s window is free.
    match = _find_match(parsed)
    if match is None:
        return None

    # TODO(D3): pull Coral33-specific fields (sport_type, sport_sub_type,
    # game_num, rot_num, price_numerator/denominator, game_datetime,
    # description) from the raw cache row via
    # OddsCache.get_event_row(...) — or refactor to thread the row
    # through scan_all_ev. For now, build a partial LegSpec from what
    # EVOpportunity carries directly so the resolver shape is stable.
    leg = _build_partial_leg_spec(LegSpec, parsed, match)
    return leg, float(match.get("kelly_full_pct", 0.0))


def _find_match(parsed: dict) -> dict | None:
    """Scan the current cache for the row matching `parsed`.

    Reuses /api/ev's public scanner path so we hit the same snapshot the
    UI sees. Returns the raw opportunity dict (as produced by
    scan_all_ev) or None.
    """
    try:
        from server.odds.cache import OddsCache
        from server.odds.ev import scan_all_ev
        from server.odds.normalize import rows_to_games
    except ImportError:
        return None

    # TODO(D3): inject the shared OddsCache instance via dependency rather
    # than opening a fresh one here. For F0 scaffolding we open the
    # default-located cache; the orchestrator will replace this with a
    # passed-in handle.
    from pathlib import Path
    cache_path = Path("server/cache.db")
    if not cache_path.exists():
        return None

    cache = OddsCache(cache_path)
    now = datetime.now(timezone.utc)
    rows = cache.all_current()
    games = rows_to_games(rows, now=now)
    opps = scan_all_ev(
        games,
        now=now,
        # Permissive defaults — we just need to FIND a specific row,
        # not filter the universe.
        min_ev_pct=-100.0,
        stale_seconds=300.0,
        max_results=10000,
    )

    target_point = parsed["point"]
    for o in opps:
        op_point = o.get("point")
        # `point` comes through as float|None from scan_all_ev; compare
        # tolerantly since the row_id round-trip serializes via %g.
        point_match = (
            (op_point is None and target_point is None)
            or (
                op_point is not None
                and target_point is not None
                and abs(float(op_point) - float(target_point)) < 1e-6
            )
        )
        if (
            o.get("event_id") == parsed["event_id"]
            and o.get("market_kind") == parsed["market_kind"]
            and point_match
            and o.get("outcome_name") == parsed["outcome_name"]
            and o.get("book") == parsed["book"]
        ):
            return o
    return None


def _build_partial_leg_spec(LegSpec, parsed: dict, match: dict):
    """Build the best LegSpec we can from /api/ev's output alone.

    Coral33-specific fields default to placeholders until D3 wires in
    OddsCache.get_event_row(). Callers in test/dry-run mode will see
    sensible defaults; live mode (D4) will overwrite these from the raw
    cache row.
    """
    # TODO(D3): replace placeholder defaults with cache-row lookups.
    return LegSpec(
        sport_type="",
        sport_sub_type="",
        period="Game",
        line_type=_market_to_line_type(parsed["market_kind"]),
        game_num=0,
        chosen_team_id="",
        rot_num=0,
        price_american=int(match.get("offered_price_american", 0)),
        price_decimal=_american_to_decimal(
            int(match.get("offered_price_american", 0))
        ),
        price_numerator=0,
        price_denominator=0,
        spread=float(parsed["point"]) if parsed["point"] is not None else 0.0,
        total_points=(
            float(parsed["point"])
            if parsed["point"] is not None
            and parsed["market_kind"] in ("totals", "alternate_totals")
            else 0.0
        ),
        game_datetime="",
        description="",
    )


def _market_to_line_type(market_kind: str) -> str:
    """Map our market_kind taxonomy to Coral33's line_type tag.

    TODO(D3): align with the canonical mapping in the Coral33 normalizer.
    """
    if market_kind in ("h2h",):
        return "M"
    if market_kind in ("spreads", "alternate_spreads"):
        return "S"
    if market_kind in ("totals", "alternate_totals"):
        return "T"
    return "M"


def _american_to_decimal(american: int) -> float:
    """Standard American-to-decimal conversion (matches odds/devig.py)."""
    if american == 0:
        return 1.0
    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)
