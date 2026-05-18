"""Sport-agnostic Closing Line Value (CLV) computation.

Builds the bridge between a placed Coral33 wager and the consensus
closing line we captured for that event. Three responsibilities:

  1. wager_to_market_lookup(wager) → (event_id, market_key,
     outcome_name, outcome_point) — translates a wager's structured
     fields into the cache's outcome encoding.
  2. compute_clv(bet_odds, close_odds) → {clv_cents, clv_pct} —
     ported from baseball-agents/tracker.py:25-45.
  3. lookup_clv(wager) → float | None — orchestrates 1+2 and returns
     the CLV percent (or None when no closing line is available).

The translator is sport-agnostic by leveraging the same dispatch tables
the normalizer used to write the cache rows in the first place
(PERIOD_SUFFIX + the per-sport Coral33Config). No bet-type taxonomy: the
shape of the wager fields (adj_spread, adj_total_points, chosen_team_id
pattern, description) tells us what kind of market it was.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .books.coral33.event_matcher import _normalize_team
from .books.coral33.mapping import (
    Coral33Config,
    PERIOD_SUFFIX,
    PROP_STAT_TO_MARKET_KEY,
    load_coral33_config,
)
from .books.coral33.wager_log import WagerLogEntry
from .cache import OddsCache
from .devig import american_to_decimal


logger = logging.getLogger(__name__)


# Coral33 alt-line / series suffixes that appear on team names — same set
# the normalizer's _clean_team() strips. Duplicated here so we don't
# depend on a private import; both must stay in sync.
_ALT_TEAM_SUFFIXES: tuple[str, ...] = (
    " Alt Line",
    " Alternate Line",
    " Alt RL",
    " Alt Run Line",
    " Series",
    " Games",
)


# Regex catching the "O <num>" / "U <num>" / "Over <num>" / "Under <num>"
# token at the end of a Coral33 description, used to derive the Over/Under
# side and the line for total/team-total/player-prop bets when the
# structured fields don't carry it.
_OU_RE = re.compile(
    r"\b(O|U|Over|Under)\s+(-?\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)

# Regex catching a player-prop description shape — "Player Name O/U Line"
# where the player name is everything before the O/U token. Used as a
# fallback when the structured fields don't tell us whether the bet was
# a player prop.
_PROP_DESCRIPTION_RE = re.compile(
    r"^(?P<player>.+?)\s+(?:O|U|Over|Under)\s+(?P<point>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MarketLookup:
    """Result of translating a wager into the cache's outcome address."""
    event_id: str
    sport_key: str
    market_key: str
    outcome_name: str
    outcome_point: float
    canonical_home: str
    canonical_away: str


@dataclass(frozen=True)
class CLVResult:
    clv_cents: int
    clv_pct: float
    close_odds: int


# ─────────────────────────── CLV math ────────────────────────────────


def compute_clv(bet_odds: int, close_odds: int) -> CLVResult:
    """Compute CLV given the bet's American odds and the closing line's
    American odds.

    Ported verbatim (math-equivalent) from baseball-agents/tracker.py.
    Sport-agnostic — operates on raw American odds, no market context.

      clv_pct  = (bet_decimal / close_decimal) - 1   — primary signal
      clv_cents = sign-aware American-cents diff:
          both favorites (negative):  abs(close) - abs(bet)
          both dogs (positive):       bet - close
          mixed sign (line crossed):  round((bet_dec - close_dec) * 100)
    """
    bet_dec = american_to_decimal(int(bet_odds))
    close_dec = american_to_decimal(int(close_odds))
    if close_dec <= 0:
        return CLVResult(0, 0.0, int(close_odds))
    clv_pct = round((bet_dec / close_dec) - 1.0, 4)
    if bet_odds < 0 and close_odds < 0:
        cents = abs(int(close_odds)) - abs(int(bet_odds))
    elif bet_odds > 0 and close_odds > 0:
        cents = int(bet_odds) - int(close_odds)
    else:
        cents = int(round((bet_dec - close_dec) * 100))
    return CLVResult(int(cents), float(clv_pct), int(close_odds))


# ───────────────────── Sport / market resolution ──────────────────────


def build_subtype_to_sport_key(config: Coral33Config) -> dict[str, str]:
    """Inverse of coral33.toml's [sports.<key>] blocks.

    Maps every coral33 sportSubType the config knows about to our internal
    sport_key. Keyed by UPPERCASE subtype string so the wager log's
    case-variant subtypes (e.g. "MLB Alt Line", "NBAPlayerPro", "Score
    in 1st") still resolve against the config's canonical-case entries.
    Used to translate wager_log entries' sport_sub_type field back to
    our key (e.g. "wnba", "mlb", "tennis"). Walks main + alt + prop +
    extras subtypes so wagers placed on any tier resolve.
    """
    out: dict[str, str] = {}
    for key, cfg in config.sports.items():
        for sub in (
            *cfg.subtypes_main,
            *cfg.subtypes_alt,
            *cfg.subtypes_prop,
        ):
            out[sub.upper()] = key
        for ex in cfg.extras:
            out[ex.subtype.upper()] = key
    return out


def _period_suffix_for(period: str | None) -> str:
    """Map a wager's period string to our market-key suffix. Defaults to
    the empty string (game-level) when unknown, since most wager records
    omit the period field entirely on game-level bets."""
    if not period:
        return ""
    return PERIOD_SUFFIX.get(period, "")


def _strip_alt_suffixes(name: str) -> str:
    """Strip Coral33's alt/series suffixes from a team-name field. Mirrors
    normalizer._clean_team so the resulting name matches what the
    matcher / aliases were built against."""
    n = (name or "").strip()
    for suf in _ALT_TEAM_SUFFIXES:
        if n.endswith(suf):
            return n[: -len(suf)]
    return n


def _normalize_with_aliases(
    name: str | None,
    sport_key: str,
    config: Coral33Config,
) -> str:
    """Normalize a Coral33 team name through the same pipeline the matcher
    uses, then apply the per-sport alias table. Returns the lowercase
    normalized canonical name (e.g. "phoenix suns"), suitable for
    comparison against another normalized name."""
    if not name:
        return ""
    cleaned = _strip_alt_suffixes(name)
    aliases = config.team_aliases.get(sport_key, {})
    return _normalize_team(cleaned, aliases, sport_key)


def _parse_over_under(description: str | None) -> tuple[str, float] | None:
    """Pull the 'Over X' / 'Under X' token from a description string.
    Returns (side, point) where side is "Over" or "Under", or None when
    the description doesn't carry one."""
    if not description:
        return None
    m = _OU_RE.search(description)
    if not m:
        return None
    side_raw = m.group(1).lower()
    point = float(m.group(2))
    if side_raw in ("o", "over"):
        return ("Over", point)
    return ("Under", point)


def _parse_prop_player(description: str | None) -> tuple[str, float] | None:
    """Pull a player name + line from a player-prop-shaped description.
    Returns (player_name, point) or None. Used as a fallback to detect
    that a wager is a player prop when the structured fields don't make
    it obvious."""
    if not description:
        return None
    m = _PROP_DESCRIPTION_RE.match(description.strip())
    if not m:
        return None
    player = m.group("player").strip()
    point = float(m.group("point"))
    return (player, point)


def _is_prop_subtype(sport_sub_type: str | None, sport_key: str) -> bool:
    """Coral33's prop subtypes don't share a single naming convention
    across sports — NBAPLAYERPRO, BasePlaProp, NHL GAME PRO etc. Cheapest
    discriminator: any subtype string that contains 'PRO' (case-insensitive)
    AND is referenced as a prop subtype in PROP_STAT_TO_MARKET_KEY's
    keyed sports. We additionally consult the per-sport prop stat table —
    a wager whose `team2_id` matches a known stat name is unambiguously a
    prop regardless of subtype."""
    if not sport_sub_type:
        return False
    s = sport_sub_type.upper()
    return "PRO" in s or "PROP" in s


def _is_nrfi_subtype(sport_sub_type: str | None, chosen: str | None) -> bool:
    """Coral33 surfaces NRFI under the 'SCORE IN 1ST' extras subtype with
    chosen_team_id encoded as 'Yes/No ... score 1st Inn'. Detect by
    looking for the literal phrase in either field."""
    s = (sport_sub_type or "").upper()
    if "SCORE IN 1ST" in s or "SCORE 1ST" in s:
        return True
    c = (chosen or "").lower()
    return "score 1st inn" in c or "score in 1st" in c


def _classify_bet(wager: WagerLogEntry) -> str:
    """Determine market family from the structured wager fields.

    Returns one of: 'spread', 'total', 'team_total', 'player_prop',
    'nrfi', 'moneyline', 'unknown'.

    Heuristic order matters — props and NRFI are detected first since
    they have stronger structural signatures than h2h/spread/total.
    """
    spread = wager.adj_spread or 0.0
    total = wager.adj_total_points or 0.0
    chosen = (wager.chosen_team_id or "").strip()
    desc = (wager.description or "")
    team1 = (wager.team1_id or "").strip()
    team2 = (wager.team2_id or "").strip()

    # NRFI / 1st-inning yes-no markets — detected via subtype tag or
    # the 'score 1st Inn' phrase that Coral33 embeds in chosen_team_id.
    if _is_nrfi_subtype(wager.sport_sub_type, chosen):
        return "nrfi"

    # Player prop — Coral33 puts the stat name in team2_id and the player
    # in team1_id. Strongest signal: team2_id matches a known stat for
    # this sport. Fallback: subtype contains 'PROP'/'PRO'.
    sub = wager.sport_sub_type
    # We need the sport_key to look up the prop stat table. We don't have
    # the config here, so a simpler check: team2_id is a known stat
    # across ANY sport's table.
    all_stat_names: set[str] = set()
    for stat_map in PROP_STAT_TO_MARKET_KEY.values():
        all_stat_names.update(s.lower() for s in stat_map.keys())
    if team2 and team2.lower() in all_stat_names:
        return "player_prop"
    if _is_prop_subtype(sub, sport_key=""):
        return "player_prop"

    if spread != 0.0:
        return "spread"

    if total != 0.0:
        # Slash in chosen_team_id (or both-teams pattern like "Lynx/Mercury")
        # → game total. Otherwise a single team named → team total.
        if "/" in chosen:
            return "total"
        # If chosen_team_id is empty or matches one of the teams, decide
        # by parsing the description for "Over"/"Under" on a single side.
        if not chosen:
            if _parse_over_under(desc):
                return "total"
            return "unknown"
        return "team_total"

    if chosen:
        return "moneyline"
    return "unknown"


def _resolve_prop_market_key(
    sport_key: str,
    description: str | None,
) -> str | None:
    """Map a prop description's stat phrase to a cache market_key.

    Coral33 wager descriptions don't always carry the canonical stat name
    Coral33 uses on its prop endpoint (those are surfaced as Team2ID at
    fetch time). We do a best-effort substring scan over the
    PROP_STAT_TO_MARKET_KEY[sport_key] entries.
    """
    if not description:
        return None
    table = PROP_STAT_TO_MARKET_KEY.get(sport_key)
    if not table:
        return None
    desc_l = description.lower()
    # Longer keys first so "Pts+Rebs+Asts" wins over "Points" when both
    # could substring-match.
    for stat in sorted(table.keys(), key=len, reverse=True):
        if stat.lower() in desc_l:
            return table[stat]
    return None


# ───────────────────── Wager → market lookup ──────────────────────────


def _find_event_for_wager(
    cache: OddsCache,
    sport_key: str,
    team1_norm: str,
    team2_norm: str,
    accepted_at: datetime,
    config: Coral33Config,
) -> dict | None:
    """Find the closing_lines event whose home/away teams match this
    wager's pair, picking the closest commence_time AFTER accepted_at.

    Returns {event_id, home_team, away_team, commence_time} or None.
    """
    if not team1_norm or not team2_norm:
        return None

    def _norm(name: str) -> str:
        return _normalize_with_aliases(name, sport_key, config)

    candidates = cache.find_closed_events_for_teams(
        sport_key=sport_key,
        normalized_team_a=team1_norm,
        normalized_team_b=team2_norm,
        normalize_fn=_norm,
        accepted_at=accepted_at,
    )
    if not candidates:
        return None
    # Pick the closest commence_time that postdates the bet's accepted_at
    # (game must start after bet placement for CLV to be meaningful).
    best: dict | None = None
    best_diff: float | None = None
    accepted_iso = accepted_at.isoformat() if accepted_at.tzinfo else accepted_at.replace(tzinfo=timezone.utc).isoformat()
    for c in candidates:
        ct_raw = c["commence_time"]
        try:
            ct = datetime.fromisoformat(str(ct_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        accepted_utc = (
            accepted_at if accepted_at.tzinfo
            else accepted_at.replace(tzinfo=timezone.utc)
        )
        if ct < accepted_utc:
            continue
        diff = (ct - accepted_utc).total_seconds()
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = {**c, "commence_time": ct}
    return best


def wager_to_market_lookup(
    wager: WagerLogEntry,
    cache: OddsCache,
    config: Coral33Config,
    subtype_to_sport_key: dict[str, str] | None = None,
) -> MarketLookup | None:
    """Translate a wager into (event_id, market_key, outcome_name,
    outcome_point) — the address of the closing line we'd want to query.

    Returns None when the wager can't be resolved (unknown sport,
    parlay/teaser, event not in closing_lines, ambiguous market shape).
    Callers should treat None as "CLV not yet available" and surface as
    null in the API.
    """
    # Teasers move the line as part of the wager itself (e.g., a 6-point
    # NFL teaser shifts every spread by +6 in the bettor's favor), so
    # comparing teaser-adjusted odds to the un-teased close would be
    # meaningless. Skip them.
    #
    # Parlays / round-robins / if-bets are FINE here because Coral33
    # stores the head leg's American odds in `final_money` (not the
    # combined parlay payout). CLV on the head leg measures whether the
    # bettor timed THAT leg's line well, which is the most useful signal
    # for parlay decision-making.
    if (wager.wager_type or "").upper() == "T":
        return None

    sub = wager.sport_sub_type
    if not sub:
        return None
    mapping = subtype_to_sport_key or build_subtype_to_sport_key(config)
    sport_key = mapping.get(sub.upper())
    if sport_key is None:
        return None

    # Event match against closing_lines table.
    team1_norm = _normalize_with_aliases(wager.team1_id, sport_key, config)
    team2_norm = _normalize_with_aliases(wager.team2_id, sport_key, config)
    if not team1_norm or not team2_norm:
        return None
    event = _find_event_for_wager(
        cache, sport_key, team1_norm, team2_norm, wager.accepted_at, config,
    )
    if event is None:
        return None
    event_id = event["event_id"]
    canon_home = event["home_team"]
    canon_away = event["away_team"]

    suffix = _period_suffix_for(wager.period)
    bet_class = _classify_bet(wager)

    # Build outcome encoding per bet class.
    if bet_class == "moneyline":
        market_key = f"h2h{suffix}"
        outcome_name = _resolve_canonical_chosen(
            wager.chosen_team_id, canon_home, canon_away, sport_key, config,
        )
        if outcome_name is None:
            return None
        return MarketLookup(
            event_id=event_id, sport_key=sport_key,
            market_key=market_key,
            outcome_name=outcome_name, outcome_point=0.0,
            canonical_home=canon_home, canonical_away=canon_away,
        )

    if bet_class == "spread":
        market_key = f"spreads{suffix}"
        outcome_name = _resolve_canonical_chosen(
            wager.chosen_team_id, canon_home, canon_away, sport_key, config,
        )
        if outcome_name is None:
            return None
        return MarketLookup(
            event_id=event_id, sport_key=sport_key,
            market_key=market_key,
            outcome_name=outcome_name,
            outcome_point=float(wager.adj_spread or 0.0),
            canonical_home=canon_home, canonical_away=canon_away,
        )

    if bet_class == "total":
        ou = _parse_over_under(wager.description)
        if ou is None:
            return None
        side, _line_from_desc = ou
        market_key = f"totals{suffix}"
        return MarketLookup(
            event_id=event_id, sport_key=sport_key,
            market_key=market_key,
            outcome_name=side,
            outcome_point=float(wager.adj_total_points or 0.0),
            canonical_home=canon_home, canonical_away=canon_away,
        )

    if bet_class == "team_total":
        ou = _parse_over_under(wager.description)
        if ou is None:
            return None
        side, _ = ou
        market_key = f"team_totals{suffix}"
        team_canon = _resolve_canonical_chosen(
            wager.chosen_team_id, canon_home, canon_away, sport_key, config,
        )
        if team_canon is None:
            return None
        return MarketLookup(
            event_id=event_id, sport_key=sport_key,
            market_key=market_key,
            outcome_name=f"{team_canon} {side}",
            outcome_point=float(wager.adj_total_points or 0.0),
            canonical_home=canon_home, canonical_away=canon_away,
        )

    if bet_class == "player_prop":
        # Coral33 stores player in team1_id, stat in team2_id. Map team2
        # → market_key via the sport-keyed prop table. Fall back to
        # scanning the description for the stat phrase when team2 isn't
        # a known stat (e.g. on alt-line prop subtypes).
        stat_table = PROP_STAT_TO_MARKET_KEY.get(sport_key) or {}
        market_key = stat_table.get(wager.team2_id or "")
        if market_key is None:
            market_key = _resolve_prop_market_key(sport_key, wager.description)
        if market_key is None:
            return None
        market_key = f"{market_key}{suffix}"
        ou = _parse_over_under(wager.description)
        if ou is None:
            return None
        side, _ = ou
        player_name = (wager.team1_id or "").strip()
        if not player_name:
            return None
        return MarketLookup(
            event_id=event_id, sport_key=sport_key,
            market_key=market_key,
            outcome_name=f"{player_name} {side}",
            outcome_point=float(wager.adj_total_points or 0.0),
            canonical_home=canon_home, canonical_away=canon_away,
        )

    if bet_class == "nrfi":
        # Coral33's NRFI chosen_team_id is like 'Yes Reds/Cubs score 1st
        # Inn' or 'No Reds/Cubs score 1st Inn'. Cache stores nrfi with
        # outcome_name 'Yes' / 'No' (per normalizer.py NRFI bridge).
        c = (wager.chosen_team_id or "").lower().strip()
        if c.startswith("yes"):
            side = "Yes"
        elif c.startswith("no"):
            side = "No"
        else:
            return None
        return MarketLookup(
            event_id=event_id, sport_key=sport_key,
            market_key="nrfi",
            outcome_name=side, outcome_point=0.0,
            canonical_home=canon_home, canonical_away=canon_away,
        )

    return None


def _resolve_canonical_chosen(
    chosen_team_id: str | None,
    canon_home: str,
    canon_away: str,
    sport_key: str,
    config: Coral33Config,
) -> str | None:
    """Map a wager's chosen_team_id to the canonical Odds-API team name
    used on the cache row. Compares normalized forms so alt-line short
    names (e.g. 'Suns Alt Line') still resolve."""
    if not chosen_team_id:
        return None
    chosen_n = _normalize_with_aliases(chosen_team_id, sport_key, config)
    home_n = _normalize_with_aliases(canon_home, sport_key, config)
    away_n = _normalize_with_aliases(canon_away, sport_key, config)
    if chosen_n == home_n:
        return canon_home
    if chosen_n == away_n:
        return canon_away
    return None


# ─────────────────────── Top-level orchestration ──────────────────────


def lookup_clv(
    wager: WagerLogEntry,
    cache: OddsCache,
    config: Coral33Config,
    subtype_to_sport_key: dict[str, str] | None = None,
) -> CLVResult | None:
    """End-to-end: translate wager → lookup closing line → compute CLV.

    Returns None on any miss (no event match, no closing line captured
    for that outcome, unsupported bet class, etc.).
    """
    if wager.final_money is None:
        return None
    lookup = wager_to_market_lookup(
        wager, cache, config, subtype_to_sport_key,
    )
    if lookup is None:
        return None
    close_row = cache.find_closing_line(
        event_id=lookup.event_id,
        market_key=lookup.market_key,
        outcome_name=lookup.outcome_name,
        outcome_point=lookup.outcome_point,
    )
    if close_row is None:
        return None
    try:
        close_odds = int(close_row["close_odds"])
    except (KeyError, ValueError, TypeError):
        return None
    return compute_clv(int(wager.final_money), close_odds)


# Convenience for callers: cache the Coral33Config + reverse map.
_CORAL_CONFIG_CACHE: tuple[Coral33Config, dict[str, str]] | None = None


def get_coral33_config(
    config_path: Path | None = None,
) -> tuple[Coral33Config, dict[str, str]]:
    """Lazy-loaded Coral33Config + subtype-to-sport-key map.

    The config is small and immutable at runtime — load once per process.
    """
    global _CORAL_CONFIG_CACHE
    if _CORAL_CONFIG_CACHE is not None:
        return _CORAL_CONFIG_CACHE
    if config_path is None:
        config_path = (
            Path(__file__).resolve().parent.parent
            / "config" / "coral33.toml"
        )
    config = load_coral33_config(config_path)
    reverse = build_subtype_to_sport_key(config)
    _CORAL_CONFIG_CACHE = (config, reverse)
    return _CORAL_CONFIG_CACHE
