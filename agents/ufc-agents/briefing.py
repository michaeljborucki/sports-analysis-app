"""Build UFC fight prediction briefing document."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    val = d
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
    return val if val is not None else default


def _format_fight_log(fights: list[dict]) -> str:
    """Format last N fights into readable lines."""
    if not fights:
        return "    No recent fight data available"
    lines = []
    for f in fights:
        result = f.get("result", "?")
        opp = f.get("opponent", "Unknown")
        method = f.get("method", "?")
        rnd = f.get("round", "?")
        date = f.get("date", "")
        lines.append(f"    {date} vs {opp}: {result} via {method} (R{rnd})")
    return "\n".join(lines)


def _format_context(ctx: dict) -> str:
    """Format fight context (injuries, camp, weight cut)."""
    parts = []
    injuries = ctx.get("injuries", [])
    if injuries:
        parts.append(f"  Injuries: {', '.join(injuries)}")
    camp = ctx.get("camp_info", "")
    if camp:
        parts.append(f"  Camp Notes: {camp}")
    weight = ctx.get("weight_cut_notes", "")
    if weight:
        parts.append(f"  Weight Cut: {weight}")
    short_notice = ctx.get("short_notice", False)
    if short_notice:
        parts.append("  SHORT NOTICE REPLACEMENT")
    return "\n".join(parts) if parts else "  No notable context"


def _compute_reach_diff(fa: dict, fb: dict) -> str:
    """Compute reach advantage between fighters."""
    try:
        reach_a = float(str(fa.get('reach', '0')).replace('"', '').replace("'", "").strip())
        reach_b = float(str(fb.get('reach', '0')).replace('"', '').replace("'", "").strip())
        diff = reach_a - reach_b
        if abs(diff) < 0.5:
            return "Even"
        name = fa.get('name', 'A') if diff > 0 else fb.get('name', 'B')
        return f"{name} +{abs(diff):.1f} inches"
    except (ValueError, TypeError):
        return "Unknown"


def _compute_strike_diff(fighter: dict) -> str:
    """Compute striking differential (landed - absorbed)."""
    slpm = fighter.get('slpm', 0)
    sapm = fighter.get('sapm', 0)
    diff = slpm - sapm
    return f"{diff:+.2f}" if sapm else f"{slpm:.2f} landed (absorption N/A)"


def _fight_type(fight_data: dict) -> str:
    """Return fight type description."""
    rounds = fight_data.get('rounds', 3)
    if rounds == 5:
        return "Championship/Main Event — cardio and wrestling advantage compounds"
    return "Standard bout"


def build_briefing(fight_data: dict) -> str:
    """Build a UFC fight prediction briefing document.

    Args:
        fight_data: dict with keys: event_name, date, fighter_a (dict),
                    fighter_b (dict), weight_class, rounds, odds (dict),
                    context_a (dict), context_b (dict), rankings (dict)

    Returns:
        Formatted briefing string for LLM consumption.
    """
    fa = fight_data.get("fighter_a", {})
    fb = fight_data.get("fighter_b", {})
    odds = fight_data.get("odds", {})
    ml = odds.get("moneyline", {})
    tr = odds.get("total_rounds", {})
    ip = odds.get("implied_probs", {})

    briefing = f"""UFC FIGHT PREDICTION ANALYSIS
==============================
{fight_data.get('event_name', 'TBD')} — {fight_data.get('date', 'TBD')}
{fa.get('name', 'Fighter A')} vs {fb.get('name', 'Fighter B')} | {fight_data.get('weight_class', '?')} | {fight_data.get('rounds', 3)} rounds

BETTING LINES:
  Moneyline: {fa.get('name', 'A')} {ml.get('fighter_a', 'N/A')} / {fb.get('name', 'B')} {ml.get('fighter_b', 'N/A')}
  Total Rounds: {tr.get('line', 'N/A')} (Over {tr.get('over_odds', 'N/A')} / Under {tr.get('under_odds', 'N/A')})
  Implied Win Prob: {fa.get('name', 'A')} {ip.get('fighter_a', 0):.1%} / {fb.get('name', 'B')} {ip.get('fighter_b', 0):.1%}

== FIGHTER PROFILES ==

{fa.get('name', 'Fighter A')} — Record: {fa.get('record', '?')}
  Wins: {fa.get('wins_ko', 0)} KO | {fa.get('wins_sub', 0)} SUB | {fa.get('wins_dec', 0)} DEC
  Stance: {fa.get('stance', '?')} | Height: {fa.get('height', '?')} | Reach: {fa.get('reach', '?')}
  Sig. Strikes Landed/Min: {fa.get('slpm', 0)} | Striking Accuracy: {fa.get('str_acc', 0):.0%}
  Takedown Avg/15min: {fa.get('td_avg', 0)} | Takedown Defense: {fa.get('td_def', 0):.0%}
  Submission Avg/15min: {fa.get('sub_avg', 0)} | Avg Fight Time: {fa.get('avg_fight_time', '?')}
  Age: {fa.get('age', '?')} | Current Streak: {fa.get('win_streak', 0)}
  Last 5 Fights:
{_format_fight_log(fa.get('last_5_fights', []))}

{fb.get('name', 'Fighter B')} — Record: {fb.get('record', '?')}
  Wins: {fb.get('wins_ko', 0)} KO | {fb.get('wins_sub', 0)} SUB | {fb.get('wins_dec', 0)} DEC
  Stance: {fb.get('stance', '?')} | Height: {fb.get('height', '?')} | Reach: {fb.get('reach', '?')}
  Sig. Strikes Landed/Min: {fb.get('slpm', 0)} | Striking Accuracy: {fb.get('str_acc', 0):.0%}
  Takedown Avg/15min: {fb.get('td_avg', 0)} | Takedown Defense: {fb.get('td_def', 0):.0%}
  Submission Avg/15min: {fb.get('sub_avg', 0)} | Avg Fight Time: {fb.get('avg_fight_time', '?')}
  Age: {fb.get('age', '?')} | Current Streak: {fb.get('win_streak', 0)}
  Last 5 Fights:
{_format_fight_log(fb.get('last_5_fights', []))}

== MATCHUP ANALYSIS ==
  Reach Advantage: {_compute_reach_diff(fa, fb)}
  Stance Matchup: {fa.get('stance', '?')} vs {fb.get('stance', '?')}
  Striking Differential A: {_compute_strike_diff(fa)} (landed - absorbed/min)
  Striking Differential B: {_compute_strike_diff(fb)} (landed - absorbed/min)
  Fight Duration: {fight_data.get('rounds', 3)} rounds ({_fight_type(fight_data)})

== CONTEXT ==
  Card Position: {fight_data.get('card_position', 'main_card')}
  Short Notice: {fight_data.get('short_notice', 'No')}

== FIGHTER A CONTEXT ==
{_format_context(fight_data.get('context_a', {}))}

== FIGHTER B CONTEXT ==
{_format_context(fight_data.get('context_b', {}))}

== PREDICTION TASK ==
Analyze this fight from multiple expert perspectives and provide predictions for ALL of the following:

1. FIGHT WINNER: Win probability for each fighter. Which side has moneyline value?
2. TOTAL ROUNDS (O/U {tr.get('line', '?')}): Will this fight go the distance or end early? Factor in finishing rates, cardio, and style matchup.
3. METHOD OF VICTORY: Most likely method (KO/TKO, Submission, Decision). Where does the value lie?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment"""

    missing = []
    if not fa.get("record"):
        missing.append("fighter_a.record")
    if not fb.get("record"):
        missing.append("fighter_b.record")
    if not ml:
        missing.append("odds.moneyline")
    if missing:
        logger.warning("Briefing missing fields: %s", missing)

    return briefing
