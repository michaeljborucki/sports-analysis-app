"""Compile soccer match data into a briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _format_injuries(injuries: list[dict]) -> str:
    if not injuries:
        return "No notable injuries"
    return ", ".join(f"{i['player']} ({i.get('status', 'unknown')} - {i.get('injury', '')})" for i in injuries)


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def build_briefing(match_data: dict) -> str:
    """Build the full briefing string from compiled match data."""
    home = match_data["home_team"]
    away = match_data["away_team"]
    league = match_data.get("league", "")
    odds = match_data.get("odds", {})
    ah = odds.get("asian_handicap", {})
    total = odds.get("total", {})
    btts = odds.get("btts", {})
    ml = odds.get("moneyline_1x2", {})
    implied = odds.get("implied_probs", {})

    h_stats = match_data.get("home_stats", {})
    a_stats = match_data.get("away_stats", {})
    h_xg = match_data.get("home_xg", {})
    a_xg = match_data.get("away_xg", {})
    h_form = match_data.get("home_form", {})
    a_form = match_data.get("away_form", {})
    ctx = match_data.get("context", {})
    elo = match_data.get("elo", {}) or {}

    total_line = total.get("line", 2.5)

    elo_block = ""
    if elo.get("home_elo") and elo.get("away_elo"):
        elo_block = f"""
== POWER RATINGS (Club Elo) ==
  {home}: {elo['home_elo']} | {away}: {elo['away_elo']} | Diff (+HFA): {elo['elo_diff_plus_hfa']:+.0f}
  Elo-implied 1X2: {home} {elo['elo_home_win_prob']:.1%} / Draw {elo['elo_draw_prob']:.1%} / {away} {elo['elo_away_win_prob']:.1%}
"""

    briefing = f"""SOCCER MATCH PREDICTION ANALYSIS
==============================
{league} — Matchday {match_data.get('matchday', '')} | {match_data.get('kickoff_time', '')}
{home} vs {away}
{match_data.get('venue', '')}

BETTING LINES:
  Asian Handicap: {home} {ah.get('home', 'N/A')} ({ah.get('home_odds', 'N/A')}) / {away} {ah.get('away', 'N/A')} ({ah.get('away_odds', 'N/A')})
  Total: O/U {total_line} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  BTTS: Yes {btts.get('yes_odds', 'N/A')} / No {btts.get('no_odds', 'N/A')}
  1X2: {home} {ml.get('home', 'N/A')} / Draw {ml.get('draw', 'N/A')} / {away} {ml.get('away', 'N/A')}
  Implied AH Prob: {home} {implied.get('ah_home', 0):.1%} / {away} {implied.get('ah_away', 0):.1%}

== TEAM PROFILES ==

{home} — {h_stats.get('standing', '')} | {h_stats.get('record', '')} | {h_stats.get('points', 0)} pts
  Goals: {h_stats.get('goals_for', 0)} scored / {h_stats.get('goals_against', 0)} conceded (GD: {h_stats.get('goal_diff', 0)})
  xG: {h_xg.get('xg_per_match', 'N/A')} / xGA: {h_xg.get('xga_per_match', 'N/A')}
  xG Overperformance: {h_xg.get('xg_overperformance', 'N/A')} (positive = regression risk)
  Clean Sheets: {h_xg.get('clean_sheet_pct', 'N/A')}
  Form (last 5): {h_form.get('form', 'N/A')} | PPG: {h_form.get('last_5_ppg', 'N/A')}
  Home: {h_form.get('home_record', 'N/A')} (GF:{h_form.get('home_gf', 0)} GA:{h_form.get('home_ga', 0)})
  Away: {h_form.get('away_record', 'N/A')} (GF:{h_form.get('away_gf', 0)} GA:{h_form.get('away_ga', 0)})

{away} — {a_stats.get('standing', '')} | {a_stats.get('record', '')} | {a_stats.get('points', 0)} pts
  Goals: {a_stats.get('goals_for', 0)} scored / {a_stats.get('goals_against', 0)} conceded (GD: {a_stats.get('goal_diff', 0)})
  xG: {a_xg.get('xg_per_match', 'N/A')} / xGA: {a_xg.get('xga_per_match', 'N/A')}
  xG Overperformance: {a_xg.get('xg_overperformance', 'N/A')} (positive = regression risk)
  Clean Sheets: {a_xg.get('clean_sheet_pct', 'N/A')}
  Form (last 5): {a_form.get('form', 'N/A')} | PPG: {a_form.get('last_5_ppg', 'N/A')}
  Home: {a_form.get('home_record', 'N/A')} (GF:{a_form.get('home_gf', 0)} GA:{a_form.get('home_ga', 0)})
  Away: {a_form.get('away_record', 'N/A')} (GF:{a_form.get('away_gf', 0)} GA:{a_form.get('away_ga', 0)})

== SQUAD AVAILABILITY ==
{home}: {_format_injuries(match_data.get('home_injuries', []))}
{away}: {_format_injuries(match_data.get('away_injuries', []))}
{elo_block}
== MATCH CONTEXT ==
  {home} Motivation: {ctx.get('home_motivation', 'N/A')}
  {away} Motivation: {ctx.get('away_motivation', 'N/A')}
  Derby/Rivalry: {ctx.get('derby', False)}
  {home} Rest: {ctx.get('home_rest_days', 'N/A')} days since last match{' (congested)' if ctx.get('home_congested') else ''}
  {away} Rest: {ctx.get('away_rest_days', 'N/A')} days since last match{' (congested)' if ctx.get('away_congested') else ''}
  Fixture Congestion: {ctx.get('fixture_congestion', 'Normal schedule')}
  Dead Rubber: {ctx.get('dead_rubber', False)}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. ASIAN HANDICAP ({home} {ah.get('home', 'N/A')}): Will the home team cover the handicap? Factor in xG trends, home advantage, and squad availability.
2. TOTAL GOALS (O/U {total_line}): Projected total goals. Does the xG matchup, defensive quality, and motivation suggest goals or a tight affair?
3. BOTH TEAMS TO SCORE: Will both teams find the net? Factor in defensive vulnerabilities, clean sheet rates, and attacking quality.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""
    logger.debug("Briefing built for %s vs %s: %d chars", home, away, len(briefing))
    return briefing
