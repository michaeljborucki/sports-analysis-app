"""Compile LoL match data into a structured briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.lol.briefing")


def _format_recent_form(recent_form: list) -> str:
    """Format last N recent results."""
    if not recent_form:
        return "    No recent results available"
    lines = []
    for r in recent_form[:5]:
        result_str = r.get("result", r.get("score", "?"))
        lines.append(
            f"    {r.get('date', '?')} vs {r.get('opponent', '?')}: "
            f"{result_str} ({r.get('tournament', '?')})"
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
    total = h2h.get("total_matches", a_wins + b_wins)
    if a_wins > b_wins:
        leader = "team_a leads"
    elif b_wins > a_wins:
        leader = "team_b leads"
    else:
        leader = "tied"
    return f"Overall: {a_wins}-{b_wins} ({total} games, {leader})"


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


def _format_side_stats(team: dict) -> str:
    """Format blue/red side win rates."""
    blue_wr = team.get("blue_side_wr", 0.0)
    red_wr = team.get("red_side_wr", 0.0)
    blue_str = f"{blue_wr:.0%}" if isinstance(blue_wr, float) else str(blue_wr)
    red_str = f"{red_wr:.0%}" if isinstance(red_wr, float) else str(red_wr)
    return f"Blue Side WR: {blue_str} | Red Side WR: {red_str}"


def _format_lol_stats(team: dict) -> str:
    """Format LoL-specific performance metrics."""
    lines = []

    win_rate = team.get("win_rate", 0.0)
    wr_str = f"{win_rate:.0%}" if isinstance(win_rate, float) else str(win_rate)
    lines.append(f"    Win Rate: {wr_str}")

    avg_duration = team.get("avg_game_duration", 0.0)
    dur_str = f"{avg_duration:.1f} min" if isinstance(avg_duration, float) else str(avg_duration)
    lines.append(f"    Avg Game Duration: {dur_str}")

    gd15 = team.get("gold_diff_15", 0.0)
    gd15_str = f"{gd15:+.0f}" if isinstance(gd15, float) else str(gd15)
    lines.append(f"    Gold Diff @15: {gd15_str}")

    fb_rate = team.get("first_blood_rate", 0.0)
    fb_str = f"{fb_rate:.0%}" if isinstance(fb_rate, float) else str(fb_rate)
    lines.append(f"    First Blood Rate: {fb_str}")

    ft_rate = team.get("first_tower_rate", 0.0)
    ft_str = f"{ft_rate:.0%}" if isinstance(ft_rate, float) else str(ft_rate)
    lines.append(f"    First Tower Rate: {ft_str}")

    fd_rate = team.get("first_dragon_rate", 0.0)
    fd_str = f"{fd_rate:.0%}" if isinstance(fd_rate, float) else str(fd_rate)
    lines.append(f"    First Dragon Rate: {fd_str}")

    return "\n".join(lines)


def build_briefing(match_data: dict) -> str:
    """Build a full LoL match briefing string from compiled match data.

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
    region_a = team_a.get("region", "")
    region_b = team_b.get("region", "")
    region_display_a = f" ({region_a})" if region_a else ""
    region_display_b = f" ({region_b})" if region_b else ""

    ml = odds.get("moneyline", {})
    handicap = odds.get("map_handicap", {})
    total = odds.get("total_maps", {})
    implied = odds.get("implied_probs", {})

    briefing = f"""LEAGUE OF LEGENDS MATCH PREDICTION ANALYSIS
============================================
{match_data.get('tournament', 'N/A')} | {match_data.get('date', 'N/A')} | Tier {match_data.get('tier', 'N/A')}
Format: {match_data.get('format', 'N/A').upper()} | Stage: {ctx.get('stage', 'N/A')} ({ctx.get('stakes', 'N/A')})

{name_a}{region_display_a} vs {name_b}{region_display_b}

== BETTING LINES ==
  Moneyline: {name_a} {ml.get('team_a', 'N/A')} / {name_b} {ml.get('team_b', 'N/A')}
  Game Handicap: {name_a} {handicap.get('team_a_line', 'N/A')} ({handicap.get('team_a_odds', 'N/A')}) / {name_b} {handicap.get('team_b_line', 'N/A')} ({handicap.get('team_b_odds', 'N/A')})
  Total Games: {total.get('line', 'N/A')} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  Implied Win Prob: {name_a} {implied.get('ml_team_a', 0):.1%} / {name_b} {implied.get('ml_team_b', 0):.1%}

== TEAM PROFILES ==

--- {name_a}{region_display_a} ---
  {_format_side_stats(team_a)}
  League Standing: {team_a.get('league_standing', 'N/A')}
  Days Since Roster Change: {team_a.get('days_since_roster_change', 'N/A')}
  Roster:
{_format_roster(team_a.get('roster', []), team_a.get('coach', ''))}
  Performance Metrics:
{_format_lol_stats(team_a)}
  Recent Form:
{_format_recent_form(team_a.get('recent_form', []))}

--- {name_b}{region_display_b} ---
  {_format_side_stats(team_b)}
  League Standing: {team_b.get('league_standing', 'N/A')}
  Days Since Roster Change: {team_b.get('days_since_roster_change', 'N/A')}
  Roster:
{_format_roster(team_b.get('roster', []), team_b.get('coach', ''))}
  Performance Metrics:
{_format_lol_stats(team_b)}
  Recent Form:
{_format_recent_form(team_b.get('recent_form', []))}

== META & PATCH CONTEXT ==
  {_format_patch(patch)}

== MATCH CONTEXT ==
  Head-to-Head: {_format_h2h(h2h)}
  Tournament Stage: {ctx.get('stage', 'N/A')} | Stakes: {ctx.get('stakes', 'N/A')}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions
for ALL of the following:

1. MATCH WINNER: Win probability for each team. Which side has moneyline value?
2. GAME HANDICAP ({handicap.get('team_a_line', 'N/A')} / {handicap.get('team_b_line', 'N/A')}): Probability the favorite wins by 2+ games.
   Is there value on either side?
3. TOTAL GAMES (O/U {total.get('line', 'N/A')}): Projected game count. Do team styles,
   draft tendencies, and format point over or under?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value (edge)
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""

    missing = []
    if not ml:
        missing.append("moneyline_odds")
    if not team_a.get("win_rate"):
        missing.append("team_a_stats")
    if not team_b.get("win_rate"):
        missing.append("team_b_stats")
    if not patch:
        missing.append("patch_data")

    logger.debug(
        "LoL briefing built for %s vs %s: %d chars, missing=%s",
        name_a, name_b, len(briefing), missing or "none",
    )
    return briefing
