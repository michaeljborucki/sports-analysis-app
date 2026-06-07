"""Compile all game data into a seed briefing document for LLM simulation."""
import logging
from collections import defaultdict

logger = logging.getLogger("mirofish.briefing")


class SafeDict(defaultdict):
    """A dict that returns 'N/A' for any missing key, safe for format_map()."""

    def __missing__(self, key):
        return "N/A"


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _format_injuries(injuries: list[dict]) -> str:
    """Format a list of injury dicts into a readable string."""
    if not injuries:
        return "No reported injuries"
    return ", ".join(
        f"{i.get('player', 'Unknown')} ({i.get('status', 'unknown')})"
        for i in injuries
    )


def _format_four_factors(stats: dict, side: str) -> str:
    """Format offensive or defensive four factors for a team.

    Args:
        stats: Team stats dict.
        side: 'off' or 'def'.
    """
    prefix = f"four_factors_{side}"
    ff = stats.get(prefix, stats)
    return (
        f"eFG% {_safe_get(ff, f'efg_{side}', default=_safe_get(stats, f'efg_{side}'))} | "
        f"TOV% {_safe_get(ff, f'tov_{side}', default=_safe_get(stats, f'tov_{side}'))} | "
        f"OREB% {_safe_get(ff, f'oreb_{side}', default=_safe_get(stats, f'oreb_{side}'))} | "
        f"FT Rate {_safe_get(ff, f'ftr_{side}', default=_safe_get(stats, f'ftr_{side}'))}"
    )


def _format_efficiency_profile(team: str, stats: dict, label: str) -> str:
    """Format a full efficiency profile block for one team.

    Args:
        team: Display name of the team.
        stats: TeamStats dict for this team.
        label: 'away' or 'home' — used to pull record sub-keys.
    """
    record = stats.get("record", _safe_get(stats, "record"))
    conf_record = stats.get("conf_record", _safe_get(stats, "conf_record"))
    away_record = stats.get("away_record", _safe_get(stats, "away_record"))
    home_record = stats.get("home_record", _safe_get(stats, "home_record"))
    location_record = away_record if label == "away" else home_record

    lines = [
        f"{team} — T-Rank: #{_safe_get(stats, 'trank')} | AdjEM: {_safe_get(stats, 'adjem')}",
        f"  AdjOE: {_safe_get(stats, 'adjoe')} (#{_safe_get(stats, 'adjoe_rank')}) | "
        f"AdjDE: {_safe_get(stats, 'adjde')} (#{_safe_get(stats, 'adjde_rank')})",
        f"  Tempo: {_safe_get(stats, 'tempo')} poss/40min",
        f"  Record: {record} | Conf: {conf_record} | "
        f"{'Away' if label == 'away' else 'Home'}: {location_record}",
        f"  Last 10: {_safe_get(stats, 'last_10')} | Trend: {_safe_get(stats, 'trend')}",
        f"  Four Factors (Off): {_format_four_factors(stats, 'off')}",
        f"  Four Factors (Def): {_format_four_factors(stats, 'def')}",
        f"  3PT: {_safe_get(stats, 'three_rate')} attempt rate, {_safe_get(stats, 'three_pct')}%",
        f"  SOS: {_safe_get(stats, 'sos')} | Luck: {_safe_get(stats, 'luck')}",
    ]
    return "\n".join(lines)


def _format_roster_context(team: str, roster: dict) -> str:
    """Format roster / coaching context for one team."""
    new_coach = " ** NEW COACH **" if roster.get("new_coach") else ""
    lines = [
        f"{team}:",
        f"  Returning Minutes: {_safe_get(roster, 'returning_minutes')}%",
        f"  Key Players: {_safe_get(roster, 'key_players')}",
        f"  Notable Transfers In: {_safe_get(roster, 'transfers_in')}",
        f"  Coach: {_safe_get(roster, 'coach')} "
        f"({_safe_get(roster, 'coach_tenure')} years){new_coach}",
    ]
    return "\n".join(lines)


def _format_game_context(matchup: dict) -> str:
    """Format the game-context block from a MatchupContext dict."""
    tourney = _safe_get(matchup, "tourney_context")
    lines = [
        f"  Conference: {_safe_get(matchup, 'conference_context')}",
        f"  Rivalry: {_safe_get(matchup, 'rivalry_flag')}",
        f"  Quad: {_safe_get(matchup, 'quad_classification')}",
        f"  Tournament Implications: {tourney}",
        f"  Travel: {_safe_get(matchup, 'travel_context')}",
    ]
    if tourney == "Tournament game":
        lines.append(
            "  NOTE: NCAA tournament game. Consider single-elimination dynamics, "
            "neutral court, and travel factors. Historical tournament over rate "
            "is approximately 48% — do not assume higher scoring."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main template
# ---------------------------------------------------------------------------

BRIEFING_TEMPLATE = """\
NCAAB GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}, #{away_trank}) at {home} ({home_record}, #{home_trank})
{venue} | {conference_context} | {game_time}

== EFFICIENCY PROFILES ==

{away_efficiency_profile}

{home_efficiency_profile}

== TEMPO MATCHUP ==
  {away} Tempo: {away_tempo} poss/40min | {home} Tempo: {home_tempo} poss/40min
  Projected Pace: {projected_tempo} poss/40min
  Tempo Mismatch: {mismatch_desc}

BETTING LINES:
  Spread: {home} {spread_home} ({spread_home_odds}) / {away} {spread_away} ({spread_away_odds})
  Moneyline: {home} {ml_home} / {away} {ml_away}
  Total: {total_line} (Over {over_odds} / Under {under_odds})
  1H Spread: {home} {h1_spread_home} ({h1_spread_home_odds})
  1H Total: {h1_total_line} (Over {h1_over_odds} / Under {h1_under_odds})

== ROSTER CONTEXT ==
{away_roster_context}

{home_roster_context}

== INJURIES ==
{away}: {away_injuries_text}
{home}: {home_injuries_text}
(NOTE: NCAA has no mandatory injury reporting — information may be incomplete)

== GAME CONTEXT ==
{game_context_block}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. SPREAD ({home} {spread_home}): Will the favorite cover? Factor in efficiency gap, tempo matchup, home court, and roster quality.
3. TOTAL (O/U {total_line}): Projected total points. Does the tempo matchup, efficiency ratings, and pace projection point over or under?
4. FIRST HALF: Who leads at halftime? What's the projected 1H total? Will the 1H spread favorite cover? Consider early-game pace and team tendencies.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""


def build_briefing(game_data: dict) -> str:
    """Build the full briefing string from compiled game data."""
    away = game_data.get("away_team", "AWAY")
    home = game_data.get("home_team", "HOME")

    a_stats = game_data.get("away_stats", {})
    h_stats = game_data.get("home_stats", {})
    a_roster = game_data.get("away_roster", {})
    h_roster = game_data.get("home_roster", {})
    matchup = game_data.get("matchup", {})
    odds = game_data.get("odds", {})

    # Odds sub-dicts
    spread = odds.get("spread", {})
    ml = odds.get("moneyline", {})
    total = odds.get("total", {})
    h1_spread = odds.get("h1_spread", {})
    h1_total = odds.get("h1_total", {})

    # Build the composite blocks using helpers
    away_efficiency = _format_efficiency_profile(away, a_stats, "away")
    home_efficiency = _format_efficiency_profile(home, h_stats, "home")
    away_roster_ctx = _format_roster_context(away, a_roster)
    home_roster_ctx = _format_roster_context(home, h_roster)
    game_ctx = _format_game_context(matchup)

    # Assemble all values into a SafeDict for resilient formatting
    vals = SafeDict()
    vals.update({
        # Teams
        "away": away,
        "home": home,
        "away_record": _safe_get(a_stats, "record"),
        "home_record": _safe_get(h_stats, "record"),
        "away_trank": _safe_get(a_stats, "trank"),
        "home_trank": _safe_get(h_stats, "trank"),
        "venue": game_data.get("venue", "N/A"),
        "conference_context": _safe_get(matchup, "conference_context"),
        "game_time": game_data.get("game_time", "N/A"),

        # Spread
        "spread_home": spread.get("home", "N/A"),
        "spread_home_odds": spread.get("home_odds", "N/A"),
        "spread_away": spread.get("away", "N/A"),
        "spread_away_odds": spread.get("away_odds", "N/A"),

        # Moneyline
        "ml_home": ml.get("home", "N/A"),
        "ml_away": ml.get("away", "N/A"),

        # Total
        "total_line": total.get("line", "N/A"),
        "over_odds": total.get("over_odds", "N/A"),
        "under_odds": total.get("under_odds", "N/A"),

        # 1H lines
        "h1_spread_home": h1_spread.get("home", "N/A"),
        "h1_spread_home_odds": h1_spread.get("home_odds", "N/A"),
        "h1_total_line": h1_total.get("line", "N/A"),
        "h1_over_odds": h1_total.get("over_odds", "N/A"),
        "h1_under_odds": h1_total.get("under_odds", "N/A"),

        # Efficiency profile blocks
        "away_efficiency_profile": away_efficiency,
        "home_efficiency_profile": home_efficiency,

        # Tempo matchup
        "away_tempo": _safe_get(a_stats, "adj_tempo", default=_safe_get(a_stats, "tempo")),
        "home_tempo": _safe_get(h_stats, "adj_tempo", default=_safe_get(h_stats, "tempo")),
        "projected_tempo": _safe_get(matchup, "projected_tempo"),
        "mismatch_desc": _safe_get(matchup, "mismatch_desc"),

        # Roster context blocks
        "away_roster_context": away_roster_ctx,
        "home_roster_context": home_roster_ctx,

        # Injuries
        "away_injuries_text": _format_injuries(game_data.get("away_injuries", [])),
        "home_injuries_text": _format_injuries(game_data.get("home_injuries", [])),

        # Game context block
        "game_context_block": game_ctx,
    })

    briefing = BRIEFING_TEMPLATE.format_map(vals)

    # -----------------------------------------------------------------------
    # Log briefing completeness
    # -----------------------------------------------------------------------
    missing = []
    if not a_stats:
        missing.append("away_stats")
    if not h_stats:
        missing.append("home_stats")
    if not odds:
        missing.append("odds")
    if not a_roster:
        missing.append("away_roster")
    if not h_roster:
        missing.append("home_roster")
    if not matchup:
        missing.append("matchup")
    if not game_data.get("away_injuries") and not game_data.get("home_injuries"):
        missing.append("injuries")

    logger.debug(
        "Briefing built for %s @ %s: %d chars, missing=%s",
        away, home, len(briefing), missing or "none",
    )
    return briefing
