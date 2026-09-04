"""Resolve odds-feed team names onto provider (ESPN) team records.

The odds feed and ESPN rarely spell a team the same way. The feed says
``Albany``; ESPN says ``UAlbany Great Danes``. Exact normalized-string
equality — what this module replaces — silently produced no match, and a
game that fails to match loses *every* context field, which used to blank
six systems at once (see ``evaluator.evaluate_systems``).

Matching is deliberately deterministic and conservative. Three ordered
passes, each of which must land on exactly ONE provider team:

  A. exact match on any registered alias
  B. an alias *starts with* the queried name  ("Albany" -> "albanygreatdanes")
  C. the queried name starts with an alias AND the leftover ends in that
     team's mascot ("Nicholls State Colonels" -> "Nicholls" + "Colonels").
     The mascot is what stops "Houston Baptist Huskies" collapsing onto
     "Houston" (Cougars) — extending an alias is the dangerous direction,
     because a longer name is usually a DIFFERENT school, not the same one.

Each pass also tries a ``U``-prefix variant, which is how the feed and ESPN
disagree about UAlbany / UMass / UConn / UCF.

An ambiguous name resolves to ``None`` rather than to a guess: a wrong
match feeds the wrong stadium's weather and the wrong conference into live
wager rules, which is strictly worse than a visible gap.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable


# Feed spellings that share no prefix with the provider's, so no structural
# rule can bridge them. Keep this list short — it is the escape hatch, not
# the mechanism.
_ALIASES = {
    "thecitadelbulldogs": "citadelbulldogs",
    "mcneesestatecowboys": "mcneesecowboys",
    # ESPN abbreviates where the feed spells out.
    "appalachianstate": "appstate",
    "appalachianstatemountaineers": "appstatemountaineers",
    "liu": "longisland",
    "liusharks": "longislandsharks",
    # Renamed school the odds feed still carries under its old name; without
    # this the resolver correctly refuses it (Houston is a different team).
    "houstonbaptist": "houstonchristian",
    "houstonbaptisthuskies": "houstonchristianhuskies",
}

# Tokens that carry no identity and only break prefix comparisons.
_NOISE = re.compile(r"\b(university|univ|of|the|and)\b")


def normalize(name: str) -> str:
    """ASCII-fold to bare lowercase alphanumerics."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stripped = _NOISE.sub(" ", ascii_name.lower())
    normalized = re.sub(r"[^a-z0-9]", "", stripped)
    return _ALIASES.get(normalized, normalized)


def _variants(key: str) -> list[str]:
    """`key` plus the U-prefix spelling it may disagree with."""
    if not key:
        return []
    if key.startswith("u") and len(key) > 3:
        return [key, key[1:]]
    return [key, f"u{key}"]


class TeamIndex:
    """Provider teams keyed by every alias they are known to answer to."""

    def __init__(self) -> None:
        self._ids_by_alias: dict[str, set[str]] = defaultdict(set)
        self._values: dict[str, Any] = {}
        self._mascots: dict[str, str] = {}

    def add(
        self, team_id: str, value: Any, *names: str | None, mascot: str | None = None
    ) -> None:
        self._values[team_id] = value
        if mascot:
            self._mascots[team_id] = normalize(mascot)
        for name in names:
            key = normalize(name) if name else ""
            if key:
                self._ids_by_alias[key].add(team_id)

    def __len__(self) -> int:
        return len(self._values)

    def _one(self, ids: Iterable[str]) -> Any | None:
        distinct = set(ids)
        if len(distinct) != 1:
            return None
        return self._values[distinct.pop()]

    def resolve(self, name: str) -> Any | None:
        """The single provider team `name` denotes, or None if unsure."""
        key = normalize(name)
        if not key:
            return None
        candidates = _variants(key)

        for candidate in candidates:                      # pass A — exact
            hit = self._one(self._ids_by_alias.get(candidate, ()))
            if hit is not None:
                return hit

        for candidate in candidates:                      # pass B — alias extends name
            hit = self._one(
                team_id
                for alias, ids in self._ids_by_alias.items()
                if alias.startswith(candidate)
                for team_id in ids
            )
            if hit is not None:
                return hit

        # pass C — name extends alias, longest alias first ("Ohio State
        # Buckeyes" must reach `ohiostate`, never `ohio`). The leftover has
        # to end in the team's own mascot, or the match is refused: without
        # that check "Houston Baptist Huskies" matched Houston, and
        # "Southeastern Louisiana Lions" matched Southeastern.
        prefixes = sorted(
            (alias for alias in self._ids_by_alias if len(alias) >= 4 and key.startswith(alias)),
            key=len,
            reverse=True,
        )
        for alias in prefixes:
            corroborated = {
                team_id
                for team_id in self._ids_by_alias[alias]
                if self._mascot_agrees(team_id, key[len(alias):])
            }
            hit = self._one(corroborated)
            if hit is not None:
                return hit
        return None

    def _mascot_agrees(self, team_id: str, leftover: str) -> bool:
        """Does what is left after the alias end in this team's mascot?

        A team we hold no mascot for cannot corroborate or refute, so it is
        allowed through — some ESPN payloads omit `name`.
        """
        mascot = self._mascots.get(team_id)
        if not mascot:
            return True
        return leftover.endswith(mascot)


def competitor_id(team: dict) -> str | None:
    """Stable id for an ESPN team, falling back to its normalized name.

    Live scoreboards always carry `team.id`; some historical and partial
    payloads do not, and a name-derived id keeps those usable instead of
    dropping the team out of the index entirely.
    """
    team_id = team.get("id")
    if team_id is not None:
        return str(team_id)
    fallback = normalize(team.get("displayName") or team.get("location") or "")
    return f"name:{fallback}" if fallback else None


def index_from_competitors(sides: Iterable[dict], index: TeamIndex) -> None:
    """Register both competitors of one ESPN competition into `index`."""
    for competitor in sides:
        team = competitor.get("team") or {}
        team_id = competitor_id(team)
        if team_id is None:
            continue
        index.add(
            team_id,
            str(team_id),
            team.get("displayName"),
            team.get("location"),
            team.get("shortDisplayName"),
            team.get("nickname"),
            f"{team.get('location') or ''} {team.get('name') or ''}",
            mascot=team.get("name"),
        )
