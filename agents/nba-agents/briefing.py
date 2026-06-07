"""Compile all game data into a seed briefing document for LLM simulation."""


def _format_injuries(injuries: list[dict]) -> str:
    if not injuries:
        return "No notable injuries"
    return ", ".join(f"{i['player']} ({i.get('status', 'unknown')})" for i in injuries)


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _format_pct(value, default="N/A") -> str:
    """Format a decimal as a percentage string (e.g. 0.530 -> 53.0%)."""
    if value is None or value == "N/A":
        return default
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return default


def _rest_advantage(away_rest: dict, home_rest: dict, away: str, home: str) -> str:
    """Describe the rest advantage between two teams."""
    a_days = away_rest.get("days_rest", 1)
    h_days = home_rest.get("days_rest", 1)
    a_b2b = away_rest.get("is_b2b", False)
    h_b2b = home_rest.get("is_b2b", False)

    if a_b2b and not h_b2b:
        return f"{away} on back-to-back; {home} rested"
    if h_b2b and not a_b2b:
        return f"{home} on back-to-back; {away} rested"
    if a_days == h_days:
        return "Even rest"
    if h_days > a_days:
        return f"{home} +{h_days - a_days} day(s) rest advantage"
    return f"{away} +{a_days - h_days} day(s) rest advantage"


def build_briefing(game_data: dict) -> str:
    """Build the full briefing string from compiled game data."""
    away = game_data["away_team"]
    home = game_data["home_team"]
    away_record = game_data.get("away_record", "")
    home_record = game_data.get("home_record", "")
    arena = game_data.get("arena", "")
    game_time = game_data.get("game_time", "")

    a_stats = game_data.get("away_stats", {})
    h_stats = game_data.get("home_stats", {})
    a_rest = game_data.get("away_rest", {})
    h_rest = game_data.get("home_rest", {})
    matchup = game_data.get("matchup", {})
    pace_matchup = matchup.get("pace_matchup", {})
    odds = game_data.get("odds", {})

    ml = odds.get("moneyline", {})
    spread = odds.get("spread", {})
    total = odds.get("total", {})
    h1_spread = odds.get("h1_spread", {})
    h1_total = odds.get("h1_total", {})
    implied = odds.get("implied_probs", {})
    total_line = total.get("line", "N/A")

    briefing = f"""NBA GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}) at {home} ({home_record})
{arena} | {game_time}

BETTING LINES:
  Moneyline: {home} {ml.get('home', 'N/A')} / {away} {ml.get('away', 'N/A')}
  Spread: {home} {spread.get('home', 'N/A')} ({spread.get('home_odds', 'N/A')}) / {away} {spread.get('away', 'N/A')} ({spread.get('away_odds', 'N/A')})
  Total: {total_line} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  1H Spread: {home} {h1_spread.get('home', 'N/A')} ({h1_spread.get('home_odds', 'N/A')})
  1H Total: {h1_total.get('line', 'N/A')} (Over {h1_total.get('over_odds', 'N/A')} / Under {h1_total.get('under_odds', 'N/A')})
  Implied Win Prob: {home} {implied.get('ml_home', 0):.1%} / {away} {implied.get('ml_away', 0):.1%}

== TEAM PROFILES ==

{away} — {away_record} ({a_stats.get('away_record', 'N/A')} away)
  Off Rtg: {a_stats.get('ortg', 'N/A')} | Def Rtg: {a_stats.get('drtg', 'N/A')} | Net: {a_stats.get('net_rtg', 'N/A')}
  Pace: {a_stats.get('pace', 'N/A')} | eFG%: {_format_pct(a_stats.get('efg_pct'))} | TOV%: {_format_pct(a_stats.get('tov_pct'))}
  3PT Rate: {_format_pct(a_stats.get('three_rate'))} | 3PT%: {_format_pct(a_stats.get('three_pct'))}
  Last 10: {a_stats.get('last_10', 'N/A')} | Trend: {a_stats.get('trend', 'N/A')}
  Rest: {a_rest.get('days_rest', 'N/A')} days | B2B: {'Yes' if a_rest.get('is_b2b') else 'No'}
  Travel: {a_rest.get('travel_miles', 'N/A')} miles from last game

{home} — {home_record} ({h_stats.get('home_record', 'N/A')} home)
  Off Rtg: {h_stats.get('ortg', 'N/A')} | Def Rtg: {h_stats.get('drtg', 'N/A')} | Net: {h_stats.get('net_rtg', 'N/A')}
  Pace: {h_stats.get('pace', 'N/A')} | eFG%: {_format_pct(h_stats.get('efg_pct'))} | TOV%: {_format_pct(h_stats.get('tov_pct'))}
  3PT Rate: {_format_pct(h_stats.get('three_rate'))} | 3PT%: {_format_pct(h_stats.get('three_pct'))}
  Last 10: {h_stats.get('last_10', 'N/A')} | Trend: {h_stats.get('trend', 'N/A')}
  Rest: {h_rest.get('days_rest', 'N/A')} days | B2B: {'Yes' if h_rest.get('is_b2b') else 'No'}

== PACE MATCHUP ==
  Projected Pace: {pace_matchup.get('projected_pace', 'N/A')}
  Projected Possessions: {pace_matchup.get('projected_possessions', 'N/A')}
  Pace Mismatch: {pace_matchup.get('mismatch', 'N/A')}
"""

    # Team totals
    team_totals = odds.get("team_totals", {})
    if team_totals:
        ht = team_totals.get("home", {})
        at = team_totals.get("away", {})
        briefing += f"""
== TEAM TOTALS ==
  {home} O/U: {ht.get('line', 'N/A')} (Over {ht.get('over_odds', 'N/A')} / Under {ht.get('under_odds', 'N/A')})
  {away} O/U: {at.get('line', 'N/A')} (Over {at.get('over_odds', 'N/A')} / Under {at.get('under_odds', 'N/A')})
"""

    # Q1 lines
    q1_ml = odds.get("q1_moneyline", {})
    q1_spread = odds.get("q1_spread", {})
    q1_total = odds.get("q1_total", {})
    if q1_ml or q1_total:
        briefing += f"""
== QUARTER 1 LINES ==
  Q1 ML: {home} {q1_ml.get('home', 'N/A')} / {away} {q1_ml.get('away', 'N/A')}
  Q1 Spread: {home} {q1_spread.get('home', 'N/A')} ({q1_spread.get('home_odds', 'N/A')})
  Q1 Total: {q1_total.get('line', 'N/A')} (Over {q1_total.get('over_odds', 'N/A')} / Under {q1_total.get('under_odds', 'N/A')})
"""

    briefing += f"""
== INJURIES ==
{away}: {_format_injuries(game_data.get('away_injuries', []))}
{home}: {_format_injuries(game_data.get('home_injuries', []))}

== REST & SCHEDULE CONTEXT ==
  Rest Advantage: {_rest_advantage(a_rest, h_rest, away, home)}
  {away} schedule: {a_rest.get('games_last_7', 'N/A')} games in last 7 days
  {home} schedule: {h_rest.get('games_last_7', 'N/A')} games in last 7 days

== HEAD-TO-HEAD ==
  Season Series: {matchup.get('h2h_record', 'N/A')}
  Last Meeting: {matchup.get('last_meeting', 'N/A')}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. SPREAD ({home} {spread.get('home', 'N/A')}): Will the favorite cover? Factor in rest, pace matchup, and injury impact.
3. TOTAL (O/U {total_line}): Projected total points. Does the pace matchup, defensive ratings, and rest situation point over or under?
4. FIRST HALF: Based on starting lineups and early-game tendencies, who leads at halftime? What's the projected 1H total?
5. QUARTER 1: Project the Q1 winner, total, and whether the Q1 spread/total offers value.
6. TEAM TOTALS: Project each team's individual point total and whether each team's O/U line offers value.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""
    return briefing
