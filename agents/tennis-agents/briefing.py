"""Compile match data into a briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _safe_get(d: dict, *keys, default="N/A"):
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _format_recent_form(form: list[dict]) -> str:
    if not form:
        return "    No recent match data available"
    lines = []
    for m in form[-10:]:
        lines.append(f"    {m.get('tourney_date', '?')} {m.get('tourney_name', '?')}: "
                     f"vs {m.get('opponent', '?')} {m.get('score', '?')} ({m.get('surface', '?')})")
    return "\n".join(lines) if lines else "    No recent match data available"


def build_briefing(match_data: dict) -> str:
    pa = match_data.get("player_a", {})
    pb = match_data.get("player_b", {})
    odds = match_data.get("odds", {})
    cond = match_data.get("conditions", {})
    h2h = match_data.get("head_to_head", {})
    injuries = match_data.get("injuries", {})

    ml = odds.get("moneyline", {})
    gh = odds.get("game_handicap", {})
    tg = odds.get("total_games", {})
    implied = odds.get("implied_probs", {})

    pa_serve = pa.get("serve_stats", {})
    pa_ret = pa.get("return_stats", {})
    pb_serve = pb.get("serve_stats", {})
    pb_ret = pb.get("return_stats", {})

    briefing = f"""TENNIS MATCH PREDICTION ANALYSIS
==============================
{match_data.get('tournament', '')} — {match_data.get('round', '')} | {cond.get('surface', '')} ({cond.get('indoor_outdoor', '')})
{pa.get('name', 'TBD')} vs {pb.get('name', 'TBD')} | Best of {match_data.get('best_of', 3)}

BETTING LINES:
  Moneyline: {pa.get('name', 'A')} {ml.get('player_a', 'N/A')} / {pb.get('name', 'B')} {ml.get('player_b', 'N/A')}
  Game Handicap: {pa.get('name', 'A')} {gh.get('player_a_point', 'N/A')} ({gh.get('player_a_odds', 'N/A')}) / {pb.get('name', 'B')} {gh.get('player_b_point', 'N/A')} ({gh.get('player_b_odds', 'N/A')})
  Total Games: {tg.get('line', 'N/A')} (Over {tg.get('over_odds', 'N/A')} / Under {tg.get('under_odds', 'N/A')})
  Implied Win Prob: {pa.get('name', 'A')} {implied.get('player_a', 0):.1%} / {pb.get('name', 'B')} {implied.get('player_b', 0):.1%}

== PLAYER PROFILES ==

{pa.get('name', 'TBD')} — Rank #{pa.get('ranking', 'N/A')} | Elo: {pa.get('elo', 'N/A')} (Surface Elo: {pa.get('surface_elo', 'N/A')})
  Season Record: {pa.get('season_record', 'N/A')} | Surface Record: {pa.get('surface_record', 'N/A')}
  Serve: {pa_serve.get('first_serve_pct', 'N/A')} 1st in, {pa_serve.get('first_serve_win_pct', 'N/A')} 1st won, {pa_serve.get('second_serve_win_pct', 'N/A')} 2nd won
  Aces/DF per match: {pa_serve.get('ace_rate', 'N/A')}/{pa_serve.get('df_rate', 'N/A')}
  Return: {pa_ret.get('return_pts_won_pct', 'N/A')} pts won | Break Point Conv: {pa_ret.get('bp_conversion_pct', 'N/A')}
  Hand: {pa.get('hand', 'N/A')} | Backhand: {pa.get('backhand', 'N/A')} | Height: {pa.get('height', 'N/A')} | Age: {pa.get('age', 'N/A')}
  Days Since Last Match: {pa.get('days_since_last_match', 'N/A')}
  Recent Form (Last 10):
{_format_recent_form(pa.get('recent_form', []))}

{pb.get('name', 'TBD')} — Rank #{pb.get('ranking', 'N/A')} | Elo: {pb.get('elo', 'N/A')} (Surface Elo: {pb.get('surface_elo', 'N/A')})
  Season Record: {pb.get('season_record', 'N/A')} | Surface Record: {pb.get('surface_record', 'N/A')}
  Serve: {pb_serve.get('first_serve_pct', 'N/A')} 1st in, {pb_serve.get('first_serve_win_pct', 'N/A')} 1st won, {pb_serve.get('second_serve_win_pct', 'N/A')} 2nd won
  Aces/DF per match: {pb_serve.get('ace_rate', 'N/A')}/{pb_serve.get('df_rate', 'N/A')}
  Return: {pb_ret.get('return_pts_won_pct', 'N/A')} pts won | Break Point Conv: {pb_ret.get('bp_conversion_pct', 'N/A')}
  Hand: {pb.get('hand', 'N/A')} | Backhand: {pb.get('backhand', 'N/A')} | Height: {pb.get('height', 'N/A')} | Age: {pb.get('age', 'N/A')}
  Days Since Last Match: {pb.get('days_since_last_match', 'N/A')}
  Recent Form (Last 10):
{_format_recent_form(pb.get('recent_form', []))}

== HEAD-TO-HEAD ==
  Overall: {h2h.get('overall', 'N/A')}
  On Surface: {h2h.get('surface', 'N/A')}

== CONDITIONS ==
  Surface: {cond.get('surface', 'N/A')} ({cond.get('indoor_outdoor', 'N/A')})
  Temperature: {cond.get('temperature', 'N/A')} | Wind: {cond.get('wind', 'N/A')}
  Altitude: {cond.get('altitude', 'N/A')}
  Session: {cond.get('session', 'N/A')}

== INJURIES / FITNESS ==
{pa.get('name', 'A')}: {injuries.get('player_a', 'None reported')}
{pb.get('name', 'B')}: {injuries.get('player_b', 'None reported')}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each player. Which side has moneyline value?
2. GAME HANDICAP ({pa.get('name', 'A')} {gh.get('player_a_point', '')}): Will the favorite cover the game spread?
3. TOTAL GAMES (O/U {tg.get('line', '')}): Projected total games. Does the serve/return matchup suggest long or short?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""
    logger.debug("Briefing built for %s vs %s: %d chars", pa.get("name", "?"), pb.get("name", "?"), len(briefing))
    return briefing
