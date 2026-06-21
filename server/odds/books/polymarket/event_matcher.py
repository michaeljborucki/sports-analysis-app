"""Polymarket → Odds API event matcher.

Polymarket slugs encode the calendar DATE of the game but not the start
TIME. We anchor to noon ET of the slug date and use a 12-hour match
window — wide enough to absorb any North American sports game's actual
start (afternoon games through late-night Pacific Coast) while still
rejecting next-day same-pair rematches.

Mirrors `KalshiEventMatcher` in interface and orientation behavior:
returns the CACHE'S canonical home/away orientation (not caller-positional),
because Polymarket markets don't expose home/away semantics.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

# Reuse coral33's normalization — same accent/punctuation rules apply.
# The team-code → canonical lookup in the normalizer is the primary match
# path; `_normalize_team` is only used here for cache-side equality.
from ..coral33.event_matcher import _normalize_team


logger = logging.getLogger(__name__)


# 12 hours each side of noon-ET = 24h window. A US sports game on date D
# can start anywhere from ~12pm ET (early afternoon getaway games / MLB
# day games) to ~10:30pm ET (West Coast NBA), so a 12h window centered on
# noon ET cleanly catches all of them. The window is wide enough to never
# need shrinking for in-season volatility; same-pair rematches are at
# least 24h+ apart so we never grab the wrong game.
POLYMARKET_MATCH_WINDOW_MIN = 720


class PolymarketEventMatcher:
    """Match a Polymarket (team_a, team_b, date-anchored timestamp) to an
    existing Odds API event_id in our cache. Returns None when no match —
    caller drops the row so we never write orphan events.

    The matcher is sport-orientation-blind: Polymarket's `outcomes` array
    (and the slug team ordering) doesn't carry meaningful home/away
    semantics from our perspective, so we always return the cache's
    canonical orientation. This keeps `distinct_events` aggregation
    consistent across books.
    """

    def __init__(
        self,
        cache_events_for_sport: Callable[[str], list[dict]],
        team_aliases: dict[str, dict[str, str]] | None = None,
        window_minutes: int = POLYMARKET_MATCH_WINDOW_MIN,
    ):
        self._events_for = cache_events_for_sport
        self._aliases = team_aliases or {}
        self._window = timedelta(minutes=window_minutes)

    def match(
        self,
        sport_key: str,
        team_a: str,
        team_b: str,
        commence: datetime,
        window_minutes: int | None = None,
    ) -> dict | None:
        """Return `{event_id, home_team, away_team, commence_time}` with the
        cache's canonical orientation, or None if no game fits within the
        window.

        Args:
          sport_key: our internal key ("nba", "mlb", "nhl")
          team_a, team_b: canonical Odds API team names (caller pre-resolves
                          via TEAM_CODE_TO_CANONICAL). Order is irrelevant —
                          we try both orientations.
          commence: noon-ET anchor of the slug date (UTC-tz datetime)
          window_minutes: optional override. Defaults to the class window.
        """
        aliases = self._aliases.get(sport_key, {})
        ca = _normalize_team(team_a, aliases, sport_key)
        cb = _normalize_team(team_b, aliases, sport_key)
        if not ca or not cb:
            return None
        c_ts = commence if commence.tzinfo else commence.replace(tzinfo=timezone.utc)
        if window_minutes is not None:
            window_s = window_minutes * 60
        else:
            window_s = self._window.total_seconds()

        best: tuple[int, dict] | None = None
        for ev in self._events_for(sport_key):
            eh = _normalize_team(ev.get("home_team", ""), aliases, sport_key)
            ea = _normalize_team(ev.get("away_team", ""), aliases, sport_key)
            # Accept either orientation of (team_a, team_b) vs (home, away).
            if (eh == ca and ea == cb) or (eh == cb and ea == ca):
                pass
            else:
                continue
            ev_ts = ev["commence_time"]
            if isinstance(ev_ts, str):
                ev_ts = datetime.fromisoformat(ev_ts.replace("Z", "+00:00"))
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            diff = abs((ev_ts - c_ts).total_seconds())
            if diff > window_s:
                continue
            if best is None or diff < best[0]:
                best = (int(diff), ev)

        if best is None:
            return None
        ev = best[1]
        # Return cache-canonical orientation. Polymarket markets don't
        # carry home/away — preserve whatever the cache's authoritative
        # Odds API row says.
        canon_home = ev.get("home_team", team_a)
        canon_away = ev.get("away_team", team_b)
        canon_commence = ev["commence_time"]
        if isinstance(canon_commence, str):
            canon_commence = datetime.fromisoformat(
                canon_commence.replace("Z", "+00:00")
            )
        if canon_commence.tzinfo is None:
            canon_commence = canon_commence.replace(tzinfo=timezone.utc)
        return {
            "event_id": ev["event_id"],
            "home_team": canon_home,
            "away_team": canon_away,
            "commence_time": canon_commence,
        }

    def match_multi_anchor(
        self,
        sport_key: str,
        team_a: str, team_b: str,
        candidate_commences: list[datetime],
        tight_window_min: int = 180,
    ) -> dict | None:
        """M3: try each candidate anchor at `tight_window_min`. Return
        the match closest in time to any anchor, or None if no anchor
        hits. Caller falls back to the existing single-anchor wide-
        window `match()` when this returns None.
        """
        best: tuple[float, dict] | None = None
        for anchor in candidate_commences:
            result = self.match(
                sport_key, team_a, team_b, anchor,
                window_minutes=tight_window_min,
            )
            if result is None:
                continue
            ev_ts = result["commence_time"]
            if isinstance(ev_ts, str):
                ev_ts = datetime.fromisoformat(ev_ts.replace("Z", "+00:00"))
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            diff = abs((ev_ts - anchor).total_seconds())
            if best is None or diff < best[0]:
                best = (diff, result)
        return best[1] if best is not None else None
