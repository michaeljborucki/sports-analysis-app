"""Compile all game data into a seed briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _safe(val, default="N/A"):
    """Return val if truthy (including 0), else default."""
    if val is None or val == "":
        return default
    return val


def _fmt_pct(val, default="N/A"):
    """Format a float as a percentage string."""
    if val is None:
        return default
    try:
        return f"{float(val):.1%}"
    except (TypeError, ValueError):
        return default


def _fmt_player_list(players: list[dict], max_players: int = 5) -> str:
    """Format a list of player dicts into a multi-line summary."""
    if not players:
        return "    No player data available"
    lines = []
    for p in players[:max_players]:
        name = _safe(p.get("name"), "Unknown")
        role = _safe(p.get("role"), "")
        avg = p.get("batting_avg") or p.get("average")
        sr = p.get("strike_rate") or p.get("batting_sr")
        economy = p.get("economy") or p.get("bowling_economy")
        wickets = p.get("wickets")
        form = _safe(p.get("recent_form") or p.get("form"), "")

        parts = [f"    {name}"]
        if role:
            parts.append(f"({role})")
        if avg is not None:
            parts.append(f"Avg:{avg}")
        if sr is not None:
            parts.append(f"SR:{sr}")
        if wickets is not None:
            parts.append(f"Wkts:{wickets}")
        if economy is not None:
            parts.append(f"Eco:{economy}")
        if form:
            parts.append(f"Form:{form}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _fmt_team_profile(profile: dict, team_name: str) -> str:
    """Format a team profile dict into summary lines."""
    if not profile:
        return f"  {team_name}: No profile data"
    lines = []
    batting_avg = _safe(profile.get("batting_avg") or profile.get("team_batting_avg"))
    team_sr = _safe(profile.get("team_strike_rate") or profile.get("batting_sr"))
    powerplay_runs = _safe(profile.get("powerplay_avg") or profile.get("pp_avg"))
    death_runs = _safe(profile.get("death_overs_avg") or profile.get("death_avg"))
    bowling_avg = _safe(profile.get("bowling_avg") or profile.get("team_bowling_avg"))
    economy = _safe(profile.get("economy") or profile.get("team_economy"))
    recent_record = _safe(profile.get("recent_record") or profile.get("last_5"))
    nrr = _safe(profile.get("nrr") or profile.get("net_run_rate"))
    wins = profile.get("wins")
    losses = profile.get("losses")

    if wins is not None and losses is not None:
        lines.append(f"  {team_name}: W{wins}/L{losses} | NRR: {nrr}")
    else:
        lines.append(f"  {team_name}: NRR: {nrr}")
    lines.append(f"    Batting: Avg={batting_avg} | SR={team_sr} | PP={powerplay_runs} | Death={death_runs}")
    lines.append(f"    Bowling: Avg={bowling_avg} | Economy={economy}")
    if recent_record and recent_record != "N/A":
        lines.append(f"    Recent: {recent_record}")
    return "\n".join(lines)


def _fmt_venue_conditions(venue_conditions: dict) -> str:
    """Format venue & conditions section."""
    if not venue_conditions:
        return "  No venue/conditions data available"
    lines = []
    avg_first_innings = _safe(venue_conditions.get("avg_first_innings_score") or
                               venue_conditions.get("avg_score"))
    avg_chase = _safe(venue_conditions.get("avg_second_innings_score") or
                      venue_conditions.get("avg_chase_score"))
    bat_first_wins = _safe(venue_conditions.get("bat_first_win_pct") or
                            venue_conditions.get("bat_first_wins_pct"))
    chase_wins = _safe(venue_conditions.get("chase_win_pct") or
                        venue_conditions.get("chase_wins_pct"))
    pitch_type = _safe(venue_conditions.get("pitch_type") or venue_conditions.get("surface"))
    dew_factor = _safe(venue_conditions.get("dew_factor") or venue_conditions.get("dew"))
    weather = _safe(venue_conditions.get("weather") or venue_conditions.get("conditions"))
    boundary_size = _safe(venue_conditions.get("boundary_size") or venue_conditions.get("boundary"))

    lines.append(f"  Pitch: {pitch_type} | Boundary: {boundary_size}")
    lines.append(f"  Avg 1st Innings: {avg_first_innings} | Avg Chase: {avg_chase}")
    lines.append(f"  Bat First Win%: {bat_first_wins} | Chase Win%: {chase_wins}")
    lines.append(f"  Dew Factor: {dew_factor} | Weather: {weather}")
    return "\n".join(lines)


def _fmt_toss(toss: dict, day_night: str) -> str:
    """Format toss impact section."""
    if not toss:
        return "  No toss data available"
    lines = []
    bat_first_win_pct = _safe(toss.get("bat_first_win_pct") or toss.get("bat_win_pct"))
    chase_win_pct = _safe(toss.get("chase_win_pct") or toss.get("field_win_pct"))
    dew_impact = _safe(toss.get("dew_impact") or toss.get("dew"))
    recent_trend = _safe(toss.get("recent_trend") or toss.get("trend"))
    lines.append(f"  Bat First Win%: {bat_first_win_pct} | Chase Win%: {chase_win_pct}")
    if dew_impact and dew_impact != "N/A":
        lines.append(f"  Dew Impact: {dew_impact}")
    if recent_trend and recent_trend != "N/A":
        lines.append(f"  Recent Trend: {recent_trend}")
    if day_night.lower() == "night":
        lines.append("  Night match — dew likely significant in second innings")
    return "\n".join(lines)


def _fmt_head_to_head(h2h: dict) -> str:
    """Format head-to-head section."""
    if not h2h:
        return "  No head-to-head data available"
    lines = []
    overall = _safe(h2h.get("overall") or h2h.get("overall_record"))
    at_venue = _safe(h2h.get("at_venue") or h2h.get("venue_record"))
    last_3 = h2h.get("last_3") or h2h.get("recent_meetings")
    lines.append(f"  Overall: {overall}")
    lines.append(f"  At Venue: {at_venue}")
    if last_3:
        if isinstance(last_3, list):
            lines.append(f"  Last meetings: {', '.join(str(m) for m in last_3[:3])}")
        else:
            lines.append(f"  Recent: {last_3}")
    return "\n".join(lines)


def _fmt_match_context(context: dict) -> str:
    """Format match context section."""
    if not context:
        return "  No match context available"
    lines = []
    stage = _safe(context.get("stage") or context.get("round"))
    implications = _safe(context.get("playoff_implications") or context.get("implications"))
    pressure = _safe(context.get("pressure") or context.get("must_win"))
    lines.append(f"  Stage: {stage}")
    if implications and implications != "N/A":
        lines.append(f"  Playoff Implications: {implications}")
    if pressure and pressure != "N/A":
        lines.append(f"  Pressure: {pressure}")
    return "\n".join(lines)


def build_briefing(game_data: dict) -> str:
    """Build the full T20 cricket briefing string from compiled game data."""
    league = _safe(game_data.get("league"), "T20")
    match_number = _safe(game_data.get("match_number"), "?")
    date = _safe(game_data.get("date"), "TBD")
    team_a = _safe(game_data.get("team_a"), "Team A")
    team_b = _safe(game_data.get("team_b"), "Team B")
    team_a_full = _safe(game_data.get("team_a_full") or team_a, team_a)
    team_b_full = _safe(game_data.get("team_b_full") or team_b, team_b)
    venue = _safe(game_data.get("venue"), "TBD")
    day_night = _safe(game_data.get("day_night"), "Day/Night")
    toss_result = _safe(game_data.get("toss_result"), "")

    odds = game_data.get("odds") or {}
    ml = odds.get("moneyline") or {}
    total = odds.get("total_runs") or {}
    implied = odds.get("implied_probs") or {}

    team_a_ml = _safe(ml.get("team_a"))
    team_b_ml = _safe(ml.get("team_b"))
    total_line = _safe(total.get("line"))
    over_odds = _safe(total.get("over_odds"), "-110")
    under_odds = _safe(total.get("under_odds"), "-110")
    team_a_prob = _fmt_pct(implied.get("team_a"))
    team_b_prob = _fmt_pct(implied.get("team_b"))

    venue_conditions = game_data.get("venue_conditions") or {}
    toss = game_data.get("toss") or {}
    team_a_profile = game_data.get("team_a_profile") or {}
    team_b_profile = game_data.get("team_b_profile") or {}
    team_a_players = game_data.get("team_a_players") or []
    team_b_players = game_data.get("team_b_players") or []
    head_to_head = game_data.get("head_to_head") or {}
    match_context = game_data.get("match_context") or {}

    briefing = f"""T20 CRICKET MATCH PREDICTION ANALYSIS
========================================
{league} — Match {match_number} | {date}
{team_a_full} vs {team_b_full}
{venue} | {day_night}

BETTING LINES:
  Match Winner: {team_a} {team_a_ml} / {team_b} {team_b_ml}
  Total Runs: {total_line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {team_a} {team_a_prob} / {team_b} {team_b_prob}

== VENUE & CONDITIONS ==
{_fmt_venue_conditions(venue_conditions)}

== TOSS IMPACT ==
{_fmt_toss(toss, day_night)}
{f"  Toss Result: {toss_result}" if toss_result else "  Toss Result: Pending"}

== TEAM PROFILES ==
{_fmt_team_profile(team_a_profile, team_a_full)}
  Key Players:
{_fmt_player_list(team_a_players)}

{_fmt_team_profile(team_b_profile, team_b_full)}
  Key Players:
{_fmt_player_list(team_b_players)}

== HEAD-TO-HEAD ==
{_fmt_head_to_head(head_to_head)}

== MATCH CONTEXT ==
{_fmt_match_context(match_context)}

== PREDICTION TASK ==
Analyze this T20 matchup from multiple expert perspectives and provide PROJECTED
VALUES (not just probabilities) for ALL of the following:

GAME-LEVEL:
1. MATCH WINNER: Win probability for {team_a} vs {team_b}
2. TOTAL RUNS: Project the combined total runs for both innings
3. TEAM TOTAL RUNS: Project each team's innings score
4. SPREAD: Project the victory margin in runs

PLAYER PROPS (top 3-4 key players per side):
5. PLAYER RUNS: Project runs scored per innings for each key batsman
6. PLAYER WICKETS: Project wickets taken per match for each key bowler
7. PLAYER BOUNDARIES: Project total boundaries (4s+6s) per key batsman
8. PLAYER SIXES: Project sixes hit per key batsman

PHASE PREDICTIONS:
9. POWERPLAY RUNS: Project runs scored in first 6 overs (first innings)
10. MATCH TOTAL SIXES: Project total sixes in the entire match
11. MATCH TOTAL FOURS: Project total fours in the entire match
12. FIRST OVER RUNS: Project runs scored in the very first over
13. FALL OF FIRST WICKET: Project runs scored before the first wicket falls

BOWLING PROPS (top 2-3 bowlers):
14. RUNS CONCEDED: Project runs conceded per 4-over spell for key bowlers
15. DOT BALLS: Project dot balls per 4-over spell for key bowlers

For each prediction, provide your PROJECTED NUMBER and confidence level.
Focus on what you think WILL ACTUALLY HAPPEN, not what the market says.
"""

    missing = []
    if not odds:
        missing.append("odds")
    if not venue_conditions:
        missing.append("venue_conditions")
    if not team_a_players:
        missing.append("team_a_players")
    if not team_b_players:
        missing.append("team_b_players")
    if not head_to_head:
        missing.append("head_to_head")

    logger.debug("Briefing built for %s vs %s: %d chars, missing=%s",
                 team_a, team_b, len(briefing), missing or "none")
    return briefing
