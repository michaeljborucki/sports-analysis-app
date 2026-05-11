from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Callable


logger = logging.getLogger(__name__)


MATCH_WINDOW_MIN = 15  # ± minutes (default; per-sport overrides below)

# Per-sport match-window overrides. UFC/Boxing stamp every fight on a card
# with the SAME card-start timestamp; Odds API uses each fight's individual
# estimated start time. A heavyweight main event 3+ hours after card-start
# would orphan with a 15-minute window. 6 hours is wide enough to cover any
# realistic card length while still rejecting unrelated days.
SPORT_WINDOW_MINUTES: dict[str, int] = {
    "ufc":    360,
    "boxing": 360,
}

# Abbreviations that mean the same thing in college sports / soccer. Applied
# during prefix matching so coral33's bare "Mississippi St" lines up with
# Odds API's "Mississippi State Bulldogs". Applied per-token, not as
# substring, so "St Louis" (Saint Louis) is unaffected — that token sits
# alone, with no following abbreviation context.
_ABBREV_EXPANSION: dict[str, str] = {
    "st":   "state",
    "intl": "international",
    "natl": "national",
    "univ": "university",
}


def _strip_accents(s: str) -> str:
    """Fold accented Latin characters to ASCII ('á' → 'a', 'ñ' → 'n') so the
    a-z filter below doesn't discard them. Critical for European athletes."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )


def _normalize_team(
    name: str,
    aliases: dict[str, str],
    sport_key: str | None = None,
) -> str:
    """Lowercase, strip accents + punctuation + extra whitespace, apply alias
    map. For tennis, the canonical form is "<first-initial> <surname tokens>"
    because coral33 sends "P Carreno Busta" while the Odds API sends
    "Pablo Carreno Busta" — both reduce to "p carreno busta"."""
    if not name:
        return ""
    n = _strip_accents(name).strip().lower()
    # Drop intra-word punctuation (periods, apostrophes) BEFORE the general
    # punctuation→space pass so "D.C. United" → "dc united" not "d c united".
    # Without this, "DC United" (coral33) and "D.C. United" (Odds API) would
    # normalize differently and never match.
    n = re.sub(r"[.\']", "", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if sport_key == "tennis":
        tokens = n.split(" ")
        if len(tokens) >= 2 and len(tokens[0]) > 1:
            # "pablo carreno busta" → "p carreno busta" so it aligns with
            # coral33's already-abbreviated "p carreno busta".
            tokens[0] = tokens[0][0]
            n = " ".join(tokens)
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
    ) -> dict | None:
        """Return a dict `{event_id, home_team, away_team}` with the canonical
        Odds API team names — AND with `home_team` / `away_team` aligned to
        the SAME positional meaning the caller passed in.

        That alignment is critical: coral33 emits MoneyLine1/Spread for its
        Team1 position regardless of whether Team1 is the canonical home or
        away in Odds API's view. If we returned names in canonical home/away
        order independent of the input, the caller would bind ml1 to the
        wrong team whenever coral's orientation differs from Odds API's.

        So: if the caller passed `home=X, away=Y` and we find an Odds API
        event with canonical_home_norm == normalize(X), we return
        `{home_team: canonical_home, away_team: canonical_away}`. If instead
        canonical_home_norm == normalize(Y) (orientation swapped), we return
        `{home_team: canonical_away, away_team: canonical_home}` — i.e. the
        caller's `home` input still maps to the returned `home_team`.
        """
        aliases = self._aliases.get(sport_key, {})
        ch = _normalize_team(home, aliases, sport_key)
        ca = _normalize_team(away, aliases, sport_key)
        if not ch or not ca:
            return None
        c_ts = commence if commence.tzinfo else commence.replace(tzinfo=timezone.utc)
        # Per-sport time-window override. For UFC/Boxing the default 15-min
        # window is too tight because every fight on a card shares the same
        # card-start timestamp.
        window_s = (
            SPORT_WINDOW_MINUTES.get(sport_key, MATCH_WINDOW_MIN) * 60
        )
        candidates = self._events_for(sport_key)
        best: tuple[int, dict, bool] | None = None
        # ^ (abs_seconds_diff, event, swapped)
        #   swapped=True means canonical_home matches caller's `away`.
        for ev in candidates:
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
        if best is not None:
            ev, swapped = best[1], best[2]
            canon_home = ev.get("home_team", home)
            canon_away = ev.get("away_team", away)
            # Return the pair aligned to the caller's input positions.
            if swapped:
                return {
                    "event_id": ev["event_id"],
                    "home_team": canon_away,  # caller's `home` ≈ canonical away
                    "away_team": canon_home,
                }
            return {
                "event_id": ev["event_id"],
                "home_team": canon_home,
                "away_team": canon_away,
            }

        # Prefix-match fallback for schools that arrive as "{school}" on
        # coral33 but "{school} {mascot…}" on Odds API (all NCAA and any
        # other sport with the same pattern). Safer than maintaining a
        # 300-team alias list: accept only when exactly one candidate
        # prefix-matches in time window — ambiguous matchups (e.g., "Miami"
        # could be Miami FL or Miami OH) stay orphans rather than risking
        # a false positive.
        if sport_key in _PREFIX_MATCH_SPORTS:
            return self._prefix_match(sport_key, ch, ca, c_ts, candidates, aliases)
        return None

    def _prefix_match(
        self,
        sport_key: str,
        ch: str,
        ca: str,
        c_ts: datetime,
        candidates: list[dict],
        aliases: dict[str, str],
    ) -> dict | None:
        # Expand abbreviations on the coral33 side so "Mississippi St" lines
        # up token-by-token with cache "Mississippi State Bulldogs". Apply
        # only here in the prefix-match path, not in equality matching, so
        # we don't accidentally collapse non-NCAA names.
        ch_tokens = [_ABBREV_EXPANSION.get(t, t) for t in ch.split(" ")]
        ca_tokens = [_ABBREV_EXPANSION.get(t, t) for t in ca.split(" ")]
        window_s = SPORT_WINDOW_MINUTES.get(sport_key, MATCH_WINDOW_MIN) * 60
        matches: list[tuple[int, dict, bool]] = []
        for ev in candidates:
            eh = _normalize_team(ev.get("home_team", ""), aliases, sport_key)
            ea = _normalize_team(ev.get("away_team", ""), aliases, sport_key)
            eh_tokens = [_ABBREV_EXPANSION.get(t, t) for t in eh.split(" ")]
            ea_tokens = [_ABBREV_EXPANSION.get(t, t) for t in ea.split(" ")]
            ori_same = _is_token_prefix(ch_tokens, eh_tokens) and _is_token_prefix(ca_tokens, ea_tokens)
            ori_swap = _is_token_prefix(ch_tokens, ea_tokens) and _is_token_prefix(ca_tokens, eh_tokens)
            if ori_same:
                swapped = False
            elif ori_swap:
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
            matches.append((int(diff), ev, swapped))
        if len(matches) != 1:
            return None  # ambiguous or empty → orphan
        ev, swapped = matches[0][1], matches[0][2]
        canon_home = ev.get("home_team", "")
        canon_away = ev.get("away_team", "")
        if swapped:
            return {"event_id": ev["event_id"],
                    "home_team": canon_away, "away_team": canon_home}
        return {"event_id": ev["event_id"],
                "home_team": canon_home, "away_team": canon_away}


# Sports where coral33's bare-school naming convention is the norm and a
# word-prefix fallback is safe. Start conservative — baseball_ncaa only.
_PREFIX_MATCH_SPORTS: frozenset[str] = frozenset({"baseball_ncaa"})


def _is_token_prefix(short_tokens: list[str], long_tokens: list[str]) -> bool:
    """True iff `short_tokens` is a word-level prefix of `long_tokens`.
    "north carolina" is a prefix of "north carolina tar heels"; "north"
    alone is a prefix of "north carolina ..." — so the disambiguation in
    match() (exactly-one-candidate) carries the weight."""
    if not short_tokens or len(short_tokens) > len(long_tokens):
        return False
    return all(short_tokens[i] == long_tokens[i] for i in range(len(short_tokens)))
