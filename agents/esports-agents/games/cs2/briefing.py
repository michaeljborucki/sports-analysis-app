"""Compile CS2 match data into a structured briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.cs2.briefing")


def _format_map_pool(map_pool: dict) -> str:
    """Format a team's per-map win rate table."""
    if not map_pool:
        return "    No map pool data available"
    lines = []
    for map_name, stats in map_pool.items():
        wr = stats.get("win_rate", "N/A")
        games = stats.get("games", "N/A")
        wr_str = f"{wr:.0%}" if isinstance(wr, float) else str(wr)
        lines.append(f"    {map_name.capitalize()}: {wr_str} WR ({games} games)")
    return "\n".join(lines)


def _format_recent_form(recent_form: list) -> str:
    """Format last N recent results."""
    if not recent_form:
        return "    No recent results available"
    lines = []
    for r in recent_form[:5]:
        lines.append(
            f"    {r.get('date', '?')} vs {r.get('opponent', '?')}: "
            f"{r.get('score', '?')} ({r.get('tournament', '?')})"
        )
    return "\n".join(lines)


def _format_roster(roster: list, coach: str = "") -> str:
    """Format roster list with optional coach."""
    if not roster:
        return "    Roster data unavailable"
    players = ", ".join(roster)
    coach_str = f" | Coach: {coach}" if coach else ""
    return f"    {players}{coach_str}"


def _format_h2h(h2h: dict) -> str:
    """Format head-to-head record."""
    if not h2h:
        return "No H2H data"
    a_wins = h2h.get("team_a_wins", 0)
    b_wins = h2h.get("team_b_wins", 0)
    return f"Overall: {a_wins}-{b_wins} (team_a leads)" if a_wins > b_wins else f"Overall: {a_wins}-{b_wins} (team_b leads)" if b_wins > a_wins else f"Overall: {a_wins}-{b_wins} (tied)"


def _format_patch(patch: dict) -> str:
    """Format patch/meta context."""
    if not patch:
        return "No patch data available"
    version = patch.get("patch_version", "N/A")
    days = patch.get("days_since_patch", "N/A")
    impact = patch.get("impact_rating", "N/A")
    changes = patch.get("key_changes", [])
    changes_str = "; ".join(changes) if changes else "No notable changes"
    return f"Patch {version} ({days} days ago) | Impact: {impact}\n  Key changes: {changes_str}"


def _map_veto_analysis(team_a: dict, team_b: dict, bo_count: int) -> str:
    """Generate a basic map veto analysis from both teams' map pools."""
    pool_a = set(team_a.get("map_pool", {}).keys())
    pool_b = set(team_b.get("map_pool", {}).keys())
    shared = pool_a & pool_b
    a_only = pool_a - pool_b
    b_only = pool_b - pool_a

    name_a = team_a.get("name", "Team A")
    name_b = team_b.get("name", "Team B")

    lines = []
    if a_only:
        lines.append(f"  {name_a} comfort picks (likely to pick): {', '.join(sorted(a_only))}")
    if b_only:
        lines.append(f"  {name_b} comfort picks (likely to pick): {', '.join(sorted(b_only))}")
    if shared:
        lines.append(f"  Contested maps (both teams have data): {', '.join(sorted(shared))}")

    maps_played = min(bo_count, 3)
    lines.append(f"  Expected maps played in bo{bo_count}: up to {maps_played}")

    return "\n".join(lines) if lines else "  Insufficient map pool data for veto analysis"


def build_briefing(match_data: dict) -> str:
    """Build a full CS2 match briefing string from compiled match data.

    Args:
        match_data: Dict with keys: tournament, date, format, bo_count, tier,
                    team_a, team_b, odds, head_to_head, patch, context.

    Returns:
        Formatted briefing string suitable for LLM input.
    """
    team_a = match_data.get("team_a", {})
    team_b = match_data.get("team_b", {})
    odds = match_data.get("odds", {})
    h2h = match_data.get("head_to_head", {})
    patch = match_data.get("patch", {})
    ctx = match_data.get("context", {})
    bo_count = match_data.get("bo_count", 3)

    name_a = team_a.get("name", "Team A")
    name_b = team_b.get("name", "Team B")

    ml = odds.get("moneyline", {})
    handicap = odds.get("map_handicap", {})
    total = odds.get("total_maps", {})
    implied = odds.get("implied_probs", {})

    briefing = f"""CS2 MATCH PREDICTION ANALYSIS
==============================
{match_data.get('tournament', 'N/A')} | {match_data.get('date', 'N/A')} | Tier {match_data.get('tier', 'N/A')}
Format: {match_data.get('format', 'N/A').upper()} | Stage: {ctx.get('stage', 'N/A')} ({ctx.get('stakes', 'N/A')})
Setting: {ctx.get('online_lan', 'N/A').upper()}

{name_a} vs {name_b}

== BETTING LINES ==
  Moneyline: {name_a} {ml.get('team_a', 'N/A')} / {name_b} {ml.get('team_b', 'N/A')}
  Map Handicap: {name_a} {handicap.get('team_a_line', 'N/A')} ({handicap.get('team_a_odds', 'N/A')}) / {name_b} {handicap.get('team_b_line', 'N/A')} ({handicap.get('team_b_odds', 'N/A')})
  Total Maps: {total.get('line', 'N/A')} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  Implied Win Prob: {name_a} {implied.get('ml_team_a', 0):.1%} / {name_b} {implied.get('ml_team_b', 0):.1%}

== TEAM PROFILES ==

--- {name_a} ---
  HLTV Rank: #{team_a.get('hltv_ranking', 'N/A')}
  Win Rate (3m / 6m): {team_a.get('win_rate_3m', 0):.0%} / {team_a.get('win_rate_6m', 0):.0%}
  LAN Record: {team_a.get('lan_record', 'N/A')} | Online Record: {team_a.get('online_record', 'N/A')}
  Days Since Roster Change: {team_a.get('days_since_roster_change', 'N/A')}
  Roster:
{_format_roster(team_a.get('roster', []), team_a.get('coach', ''))}
  Map Pool:
{_format_map_pool(team_a.get('map_pool', {}))}
  Recent Form:
{_format_recent_form(team_a.get('recent_form', []))}

--- {name_b} ---
  HLTV Rank: #{team_b.get('hltv_ranking', 'N/A')}
  Win Rate (3m / 6m): {team_b.get('win_rate_3m', 0):.0%} / {team_b.get('win_rate_6m', 0):.0%}
  LAN Record: {team_b.get('lan_record', 'N/A')} | Online Record: {team_b.get('online_record', 'N/A')}
  Days Since Roster Change: {team_b.get('days_since_roster_change', 'N/A')}
  Roster:
{_format_roster(team_b.get('roster', []), team_b.get('coach', ''))}
  Map Pool:
{_format_map_pool(team_b.get('map_pool', {}))}
  Recent Form:
{_format_recent_form(team_b.get('recent_form', []))}

== MAP VETO ANALYSIS ==
{_map_veto_analysis(team_a, team_b, bo_count)}

== META & PATCH CONTEXT ==
  {_format_patch(patch)}

== MATCH CONTEXT ==
  Head-to-Head: {_format_h2h(h2h)}
  Online/LAN: {ctx.get('online_lan', 'N/A').upper()}
  Tournament Stage: {ctx.get('stage', 'N/A')} | Stakes: {ctx.get('stakes', 'N/A')}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions
for ALL of the following:

1. MATCH WINNER: Win probability for each team. Which side has moneyline value?
2. MAP HANDICAP ({handicap.get('team_a_line', 'N/A')} / {handicap.get('team_b_line', 'N/A')}): Probability the favorite wins by 2+ maps.
   Is there value on either side?
3. TOTAL MAPS (O/U {total.get('line', 'N/A')}): Projected map count. Does the map pool matchup,
   team styles, and format point over or under?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value (edge)
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""

    missing = []
    if not ml:
        missing.append("moneyline_odds")
    if not team_a.get("map_pool"):
        missing.append("team_a_map_pool")
    if not team_b.get("map_pool"):
        missing.append("team_b_map_pool")
    if not patch:
        missing.append("patch_data")

    logger.debug(
        "CS2 briefing built for %s vs %s: %d chars, missing=%s",
        name_a, name_b, len(briefing), missing or "none",
    )
    return briefing
