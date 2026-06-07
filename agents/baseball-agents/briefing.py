"""Compile all game data into a seed briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.briefing")

# Thin-sample threshold — batters below this get a "regress to league avg" tag
# so the LLM doesn't overweight noisy recent stats from rookies or call-ups.
THIN_SAMPLE_PA = 50


def _format_batter_line(b: dict) -> str:
    """One-line batter summary. Flags thin samples so the LLM regresses."""
    name = b.get("full_name") or b.get("name") or f"Player {b.get('player_id', '?')}"
    pa = int(b.get("pa", 0))
    avg = (b.get("single_pct", 0) + b.get("double_pct", 0)
           + b.get("triple_pct", 0) + b.get("hr_pct", 0))
    obp = avg + b.get("bb_pct", 0)  # approximation — excludes HBP
    slg = (b.get("single_pct", 0) + 2 * b.get("double_pct", 0)
           + 3 * b.get("triple_pct", 0) + 4 * b.get("hr_pct", 0))
    flag = "  (thin sample — regress to league avg)" if pa < THIN_SAMPLE_PA else ""
    return (f"    {name}: AVG {avg:.3f} OBP {obp:.3f} SLG {slg:.3f} | "
            f"K% {b.get('k_pct', 0)*100:.1f} BB% {b.get('bb_pct', 0)*100:.1f} "
            f"HR% {b.get('hr_pct', 0)*100:.1f} | PA {pa}{flag}")


def _format_lineup_block(team: str, batters: list) -> str:
    if not batters:
        return f"  {team}: (lineup not yet confirmed)"
    lines = [f"  {team} LINEUP:"]
    for b in batters:
        lines.append(_format_batter_line(b))
    return "\n".join(lines)


def _format_game_log(starts: list[dict]) -> str:
    if not starts:
        return "    No recent game logs available"
    lines = []
    for s in starts[:5]:
        lines.append(
            f"    {s.get('date', '?')} vs {s.get('opp', '?')}: "
            f"{s.get('ip', '?')} IP, {s.get('er', '?')} ER, "
            f"{s.get('k', '?')} K, {s.get('bb', '?')} BB, "
            f"{s.get('pitches', '?')} pitches"
        )
    return "\n".join(lines)


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


def build_briefing(game_data: dict) -> str:
    """Build the full briefing string from compiled game data."""
    away = game_data["away_team"]
    home = game_data["home_team"]
    ap = game_data.get("away_pitcher", {})
    hp = game_data.get("home_pitcher", {})
    odds = game_data.get("odds", {})
    env = game_data.get("environment", {})
    weather = env.get("weather", {})
    a_bp = game_data.get("away_bullpen", {})
    h_bp = game_data.get("home_bullpen", {})

    ml = odds.get("moneyline", {})
    rl = odds.get("run_line", {})
    total = odds.get("total", {})
    implied = odds.get("implied_probs", {})
    total_line = total.get("line", "N/A")

    prediction_task = f"""== PREDICTION TASK ==
Analyze this matchup and provide calibrated predictions for all of the following.

HOW TO CALIBRATE (read first — backtesting showed predictions missed reality by
15-30pp when this guidance was absent):

  * ANCHOR TO MARKET: The implied market probabilities above are the sharpest
    prior you have. Propose a probability that differs materially ONLY if you
    can name a specific, articulable factor the market underweighted. If you
    can't name it, default closer to market-implied.

  * CONFIDENCE CAPS: MLB has irreducible variance.
      - MONEYLINE specifically: rarely exceed 80%. Lopsided matchups (ace vs
        bottom-5 offense, bullpen collapse, callup starter on the dog side)
        legitimately reach 75-80% — don't artificially cap them. ML is the
        sharpest market, so genuine outlier predictions are how we find edge.
      - OTHER GAME-level bets (RL, totals, team totals): rarely exceed 70%.
      - PROP bets and short segments (F1/F3/F5): rarely exceed 65%.

  * THIN DATA → REGRESS: If a batter has <50 PA or a pitcher has <15 IP this
    season, regress heavily toward league average (K% 22.4, BB% 8.4, HR/PA 3.3).
    Do not extrapolate from a tiny sample.

  * STATE UNCERTAINTY: For each prediction, briefly note the strongest factor
    AGAINST your call. If the counter-case is substantial, lower your confidence.

PREDICTIONS REQUESTED:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. RUN LINE (-1.5): Probability the favorite wins by 2+ runs.
3. TOTAL (O/U {total_line}): Projected total runs.
4. TEAM TOTALS: Projected runs for EACH team individually. Over or under on each team total?
5. FIRST INNING: Probability of NO runs in the first inning (NRFI). Who leads
   after 1? Probability the game is TIED after 1?
6. FIRST 3 INNINGS: Based on first pass through the batting order, who leads
   after 3? Projected F3 total? Probability of tie after 3?
7. FIRST 5 INNINGS: Based on starting pitchers only, who leads after 5?
   Projected F5 total? Probability of tie after 5?

For each, provide probability + brief reasoning + the counter-case that would
change your mind.
"""

    # Additional betting lines (if available)
    extra_lines = []
    if odds.get("f1_total"):
        f1t = odds["f1_total"]
        extra_lines.append(f"  NRFI/YRFI: NRFI {f1t.get('under_odds', 'N/A')} / YRFI {f1t.get('over_odds', 'N/A')}")
    if odds.get("f3_moneyline"):
        f3m = odds["f3_moneyline"]
        extra_lines.append(f"  F3 ML: {home} {f3m.get('home', 'N/A')} / {away} {f3m.get('away', 'N/A')}")
    if odds.get("team_total_home"):
        tth = odds["team_total_home"]
        tta = odds.get("team_total_away", {})
        extra_lines.append(f"  Team Totals: {home} O/U {tth.get('line', 'N/A')} / {away} O/U {tta.get('line', 'N/A')}")
    extra_lines_str = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

    briefing = f"""MLB GAME PREDICTION ANALYSIS
==============================
{away} ({game_data.get('away_record', '')}) at {home} ({game_data.get('home_record', '')})
{env.get('ballpark', '')} | {env.get('day_night', '')}
Weather: {weather.get('temp_f', 'N/A')}°F, Wind {weather.get('wind_mph', 'N/A')}mph {weather.get('wind_direction', '')} | Park Factor: {env.get('park_factor_runs', 'N/A')}

BETTING LINES:
  Moneyline: {home} {ml.get('home', 'N/A')} / {away} {ml.get('away', 'N/A')}
  Run Line: {home} {rl.get('home', -1.5)} ({rl.get('home_odds', 'N/A')}) / {away} {rl.get('away', 1.5)} ({rl.get('away_odds', 'N/A')})
  Total: {total_line} (Over {total.get('over_odds', 'N/A')} / Under {total.get('under_odds', 'N/A')})
  Implied Win Prob: {home} {implied.get('ml_home', 0):.1%} / {away} {implied.get('ml_away', 0):.1%}{extra_lines_str}

== STARTING PITCHING MATCHUP ==

{ap.get('name', 'TBD')} ({away}) — {_safe_get(ap, 'season_stats', 'w')}-{_safe_get(ap, 'season_stats', 'l')}, {_safe_get(ap, 'season_stats', 'era')} ERA
  FIP: {_safe_get(ap, 'season_stats', 'fip')} | xFIP: {_safe_get(ap, 'season_stats', 'xfip')} | WHIP: {_safe_get(ap, 'season_stats', 'whip')}
  K/9: {_safe_get(ap, 'season_stats', 'k_per_9')} | BB/9: {_safe_get(ap, 'season_stats', 'bb_per_9')} | HR/9: {_safe_get(ap, 'season_stats', 'hr_per_9')}
  Days Rest: {ap.get('days_rest', 'N/A')}
  Last 5 Starts:
{_format_game_log(ap.get('last_5_starts', []))}

{hp.get('name', 'TBD')} ({home}) — {_safe_get(hp, 'season_stats', 'w')}-{_safe_get(hp, 'season_stats', 'l')}, {_safe_get(hp, 'season_stats', 'era')} ERA
  FIP: {_safe_get(hp, 'season_stats', 'fip')} | xFIP: {_safe_get(hp, 'season_stats', 'xfip')} | WHIP: {_safe_get(hp, 'season_stats', 'whip')}
  K/9: {_safe_get(hp, 'season_stats', 'k_per_9')} | BB/9: {_safe_get(hp, 'season_stats', 'bb_per_9')} | HR/9: {_safe_get(hp, 'season_stats', 'hr_per_9')}
  Days Rest: {hp.get('days_rest', 'N/A')}
  Last 5 Starts:
{_format_game_log(hp.get('last_5_starts', []))}

== BULLPEN STATE ==
{away} Bullpen: {a_bp.get('bullpen_freshness', 'N/A')}
  Closer: {_safe_get(a_bp, 'closer', 'name', default='TBD')}

{home} Bullpen: {h_bp.get('bullpen_freshness', 'N/A')}
  Closer: {_safe_get(h_bp, 'closer', 'name', default='TBD')}

== LINEUPS ==
{_format_lineup_block(away, game_data.get('away_batters', []))}

{_format_lineup_block(home, game_data.get('home_batters', []))}

== INJURIES ==
{away}: {_format_injuries(game_data.get('away_injuries', []))}
{home}: {_format_injuries(game_data.get('home_injuries', []))}

{prediction_task}"""
    # Log briefing completeness
    missing = []
    if ap.get("name") == "TBD":
        missing.append("away_pitcher")
    if hp.get("name") == "TBD":
        missing.append("home_pitcher")
    if not odds:
        missing.append("odds")
    if not weather:
        missing.append("weather")
    if not a_bp:
        missing.append("away_bullpen")
    if not h_bp:
        missing.append("home_bullpen")

    logger.debug("Briefing built for %s@%s: %d chars, missing=%s",
                 away, home, len(briefing), missing or "none")
    return briefing
