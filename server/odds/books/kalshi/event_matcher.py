from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

# Reuse coral33's normalization function — same string-cleaning rules apply
# (Kalshi's yes_sub_title is even cleaner than coral33's Team1ID; the alias
# layer plus the team-code fallback path means we rarely need fuzzy matching).
from ..coral33.event_matcher import _normalize_team


logger = logging.getLogger(__name__)


# Kalshi's occurrence_datetime is a real ISO timestamp (not coral33's local-
# tz string), but games still get rescheduled, doubleheader times jiggle,
# rain-delayed restarts shift by hours, etc. 60min is the conservative safe
# window — wide enough to absorb rescheduling, tight enough to never grab
# the wrong same-pair game (back-to-back NBA finals games are ~24h apart;
# same MLB pair plays at the earliest 12h later).
KALSHI_MATCH_WINDOW_MIN = 60


class KalshiEventMatcher:
    """Match a Kalshi (home, away, commence_time) triple to an existing
    Odds-API event_id in our cache. Returns None when no match — caller drops
    the row so we never write orphan events.

    Uses the same canonicalization rules as coral33 (`_normalize_team` from
    coral33.event_matcher) so a sport's alias table can be shared cleanly.
    Kalshi's `yes_sub_title` is usually a short form ("Los Angeles A",
    "Chicago C") so the TEAM_CODE_TO_CANONICAL lookup in the normalizer is
    the primary match path — the team_aliases hook is for the rare case
    where Kalshi's English short-form drifts from coral33-style aliases.
    """

    def __init__(
        self,
        cache_events_for_sport: Callable[[str], list[dict]],
        team_aliases: dict[str, dict[str, str]] | None = None,
        window_minutes: int = KALSHI_MATCH_WINDOW_MIN,
    ):
        self._events_for = cache_events_for_sport
        self._aliases = team_aliases or {}
        self._window = timedelta(minutes=window_minutes)

    def match(
        self,
        sport_key: str,
        home: str,
        away: str,
        commence: datetime,
        window_minutes: int | None = None,
    ) -> dict | None:
        """Return `{event_id, home_team, away_team}` with the canonical
        Odds API team names, aligned to the caller's home/away positions.

        Kalshi doesn't expose home/away on the market — we pass the two
        teams in arbitrary order and rely on the cache's existing
        canonical event to disambiguate. Mirrors Coral33EventMatcher's
        orientation-aware return.

        `window_minutes` (optional) overrides the default match window —
        used by the normalizer's date-only event_ticker path where we
        only know the game's calendar date (not its start time), and
        need a wider window to find the same-day game.
        """
        aliases = self._aliases.get(sport_key, {})
        ch = _normalize_team(home, aliases, sport_key)
        ca = _normalize_team(away, aliases, sport_key)
        if not ch or not ca:
            return None
        c_ts = commence if commence.tzinfo else commence.replace(tzinfo=timezone.utc)
        if window_minutes is not None:
            window_s = window_minutes * 60
        else:
            window_s = self._window.total_seconds()
        best: tuple[int, dict, bool] | None = None
        for ev in self._events_for(sport_key):
            eh = _normalize_team(ev.get("home_team", ""), aliases, sport_key)
            ea = _normalize_team(ev.get("away_team", ""), aliases, sport_key)
            if eh == ch and ea == ca:
                swapped = False
            elif eh == ca and ea == ch:
                swapped = True
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
                best = (int(diff), ev, swapped)
        if best is None:
            return None
        ev = best[1]
        # Return the cache's CANONICAL home/away orientation (NOT
        # caller-aligned, which is what Coral33EventMatcher does). Kalshi
        # markets don't carry a meaningful home/away — the (canon_a,
        # canon_b) the normalizer hands us is arbitrary (driven by
        # `by_event[event_ticker]` iteration order). For coral33 the
        # alignment matters because spread sign / favored-team is keyed
        # on Team1/Team2 positions; for Kalshi h2h there's no such
        # asymmetric data, and aligning to the cache's canonical avoids
        # writing rows that disagree with every other book's home/away
        # convention (which would break `distinct_events`'s MAX()
        # aggregation and corrupt downstream displays).
        canon_home = ev.get("home_team", home)
        canon_away = ev.get("away_team", away)
        # Pass through the canonical event's commence_time so the caller
        # can store the REAL game-start (not the date-only noon anchor we
        # used for matching). Critical for purge_live_rows_for_book — it
        # decides live-vs-future based on stored commence_time, and the
        # noon anchor would falsely flag rows as live mid-afternoon.
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
