from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable


logger = logging.getLogger(__name__)


MATCH_WINDOW_MIN = 10  # ± minutes


def _normalize_team(name: str, aliases: dict[str, str]) -> str:
    """Lowercase, strip punctuation and extra whitespace, apply alias map.
    Alias keys are the normalized form (post lowercase/strip)."""
    if not name:
        return ""
    n = name.strip().lower()
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return aliases.get(n, n)


class Coral33EventMatcher:
    """Match a coral33 (home, away, commence_time) triple to an existing
    Odds-API event_id in our cache. Returns None when no match — caller drops
    the row so we never write orphan events.

    Usage:
        m = Coral33EventMatcher(cache, aliases_by_sport)
        event_id = m.match("nba", "Portland Trail Blazers", "San Antonio Spurs",
                           datetime(2026, 4, 19, 19, tzinfo=timezone.utc))
    """

    def __init__(
        self,
        cache_events_for_sport: Callable[[str], list[dict]],
        team_aliases: dict[str, dict[str, str]] | None = None,
        window_minutes: int = MATCH_WINDOW_MIN,
    ):
        """
        cache_events_for_sport: callable(sport_key) -> list of
            {"event_id", "home_team", "away_team", "commence_time"}.
        team_aliases: {sport_key: {normalized_name: canonical_normalized_name}}.
        """
        self._events_for = cache_events_for_sport
        self._aliases = team_aliases or {}
        self._window = timedelta(minutes=window_minutes)

    def match(
        self,
        sport_key: str,
        home: str,
        away: str,
        commence: datetime,
    ) -> str | None:
        aliases = self._aliases.get(sport_key, {})
        ch = _normalize_team(home, aliases)
        ca = _normalize_team(away, aliases)
        if not ch or not ca:
            return None
        c_ts = commence if commence.tzinfo else commence.replace(tzinfo=timezone.utc)
        candidates = self._events_for(sport_key)
        best: tuple[int, str] | None = None  # (abs_seconds_diff, event_id)
        for ev in candidates:
            eh = _normalize_team(ev.get("home_team", ""), aliases)
            ea = _normalize_team(ev.get("away_team", ""), aliases)
            # Teams match in either orientation — the two providers can disagree
            # about which team is "home". If they disagree, the event is still
            # the same event. Accepting both directions trades a negligible
            # false-match risk for a big recall boost.
            if not ((eh == ch and ea == ca) or (eh == ca and ea == ch)):
                continue
            ev_ts = ev["commence_time"]
            if isinstance(ev_ts, str):
                ev_ts = datetime.fromisoformat(ev_ts.replace("Z", "+00:00"))
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            diff = abs((ev_ts - c_ts).total_seconds())
            if diff > self._window.total_seconds():
                continue
            if best is None or diff < best[0]:
                best = (int(diff), ev["event_id"])
        return best[1] if best else None
