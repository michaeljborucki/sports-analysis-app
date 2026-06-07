"""Odds time-series read API.

Exposes the append-on-change `odds_history` table (see cache.py) for
charting and book-behaviour analysis. The raw table is a flat stream of
price-change points; this layer groups it into per-outcome, per-book
trajectories and overlays the captured closing line as the "right answer"
reference, so a consumer can see how early each book reached the number the
market eventually settled on.

Two endpoints:
  GET /api/timeseries/events            — events that have history (picker)
  GET /api/timeseries/event/{event_id}  — grouped trajectories for one event
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..odds.cache import OddsCache


def _point_key(p) -> float:
    """Round an outcome_point for stable dict keying / close-line matching.
    Mirrors the 0.0 sentinel the cache uses for point-less (h2h) markets."""
    return round(float(p or 0.0), 4)


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/timeseries/events")
    async def list_events(sport: str | None = None, limit: int = 200) -> dict:
        return {
            "events": cache.events_with_history(sport_key=sport, limit=limit),
        }

    @router.get("/api/timeseries/event/{event_id}")
    async def event_history(event_id: str, market_key: str | None = None) -> dict:
        rows = cache.history_for_event(event_id, market_key=market_key)
        if not rows:
            raise HTTPException(404, f"no time-series for event '{event_id}'")

        # Closing-line overlay keyed by (market, outcome, point) — the devigged
        # consensus we froze at kickoff. Lets the chart mark where the market
        # actually settled so per-book lead/lag is readable at a glance.
        closes: dict[tuple, dict] = {}
        for cl in cache.closing_lines_for_event(event_id):
            closes[(cl["market_key"], cl["outcome_name"], _point_key(cl["outcome_point"]))] = {
                "close_odds": cl["close_odds"],
                "close_prob_devig": cl["close_prob_devig"],
                "captured_at": cl["captured_at"],
            }

        # Group: (market, outcome, point) → book → ordered points. rows already
        # arrive ordered by (market, outcome, point, book, observed_at), so the
        # point lists come out time-sorted without re-sorting here.
        grouped: dict[tuple, dict[str, list[dict]]] = {}
        for r in rows:
            key = (r["market_key"], r["outcome_name"], _point_key(r["outcome_point"]))
            grouped.setdefault(key, {}).setdefault(r["bookmaker_key"], []).append(
                {"observed_at": r["observed_at"], "price_american": r["price_american"]}
            )

        markets = []
        for (mk, outcome, point), by_book in grouped.items():
            markets.append({
                "market_key": mk,
                "outcome_name": outcome,
                "outcome_point": point,
                "close": closes.get((mk, outcome, point)),
                "series": [
                    {"bookmaker_key": book, "points": pts}
                    for book, pts in sorted(by_book.items())
                ],
            })

        # history_for_event returns only price columns, so pull event meta
        # (teams, commence) from the grouped-events summary.
        meta = next(
            (e for e in cache.events_with_history() if e["event_id"] == event_id),
            None,
        ) or {}
        return {
            "event_id": event_id,
            "sport_key": meta.get("sport_key"),
            "home_team": meta.get("home_team"),
            "away_team": meta.get("away_team"),
            "commence_time": meta.get("commence_time"),
            "markets": markets,
        }

    return router
