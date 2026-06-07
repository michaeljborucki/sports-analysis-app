# MiroFish Cricket T20 Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for T20 cricket across major franchise leagues (IPL, BBL, CPL, PSL, The Hundred, SA20, BPL, ILT20). The system uses a 6-model LLM ensemble with adversarial challenge to predict match outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for T20 cricket.

IMPORTANT CONTEXT: Cricket T20 scored 5.45 in validated analysis — lower than originally estimated. The LLM advantage is strong (7/10) because pitch conditions, toss, dew, and venue narratives are genuinely hard to parameterize. But volume is limited (~328 matches across ALL leagues) and predictability is low (chasing team wins ~55%). Focus on IPL and BBL for maximum liquidity, expand to other leagues cautiously.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Match Schedule
- Source: CricketData.org (free API, up to 100K hits/hour) or ESPNcricinfo
- Returns: list of upcoming matches with team names, league, venue, date/time, toss time

### scrapers/team_stats.py — Team Profiles
- Source: Cricsheet (free ball-by-ball data) + ESPNcricinfo
- Per team per league, return:
  - Win rate (overall, batting first, chasing)
  - Average score batting first / chasing
  - Run rate (economy and scoring rate)
  - Powerplay scoring rate (overs 1-6)
  - Death overs economy (overs 16-20)
  - Net run rate (NRR)
  - League standing
  - Last 5 match results

### scrapers/players.py — Key Player Profiles
- Source: Cricsheet + ESPNcricinfo + cricketdata R package
- Per player (top 5-6 per team), return:
  - Role: batsman/bowler/all-rounder/wicketkeeper
  - T20 batting stats: avg, strike rate, runs in this tournament
  - T20 bowling stats: economy, avg, wickets in this tournament
  - Recent form: last 5 innings/spells
  - Record at this venue
  - Matchup vs specific opponent (if enough data)

### scrapers/venue.py — Venue & Conditions (CRITICAL for cricket)
- Source: ESPNcricinfo venue records + weather API
- Per venue, return:
  - Average 1st innings score at this ground (last 2 seasons)
  - Average 2nd innings score (chasing team)
  - Chase win % at this ground
  - Pitch type: batting-friendly / bowling-friendly / balanced
  - Pitch degradation: does the surface deteriorate in 2nd innings? (spin-friendly later)
  - Dew factor: evening matches in subcontinental venues get dew (makes chasing easier)
  - Boundary size: short boundaries = more sixes
  - Temperature, humidity, wind
  - Day/night vs afternoon match

### scrapers/toss.py — Toss Impact
- Source: Cricsheet historical data
- Returns per venue:
  - Toss win → choose to bat first % vs chase %
  - Win rate when batting first vs chasing (at this venue, this season)
  - Dew factor assessment for evening matches

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: varies by league — `cricket_ipl`, `cricket_big_bash_league`, `cricket_caribbean_premier_league`, etc.
- Fetch: match winner (moneyline), innings runs (total), top batsman (if available)
- Return OddsData dataclass with:
  - team_a, team_b
  - moneyline: {team_a: price, team_b: price}
  - total_runs: {line: XXX.5, over_odds: price, under_odds: price} (1st innings or match total)
  - implied_probs: {team_a: prob, team_b: prob} (vig-removed)

### scrapers/scores.py — Match Results
- Source: CricketData.org or ESPNcricinfo
- Returns per completed match:
  - team_a, team_b, winner
  - team_a_score, team_b_score (with wickets and overs)
  - toss_winner, toss_decision (bat/field)
  - total_runs (combined)
  - method (if DLS applied)

---

## Layer 2: Briefing Template

```
T20 CRICKET MATCH PREDICTION ANALYSIS
==============================
{league} — Match {match_number} | {date}
{team_a} vs {team_b}
{venue} | {day_night} | Start: {time}

BETTING LINES:
  Match Winner: {team_a} {ml_a} / {team_b} {ml_b}
  Total Runs: {line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {team_a} {prob_a:.1%} / {team_b} {prob_b:.1%}

== VENUE & CONDITIONS ==
  Ground: {venue_name}
  Avg 1st Innings Score: {avg_1st_score} (last 2 seasons, {sample_size} matches)
  Avg 2nd Innings Score: {avg_2nd_score}
  Chase Win %: {chase_win_pct}%
  Pitch Type: {pitch_type}
  Pitch Degradation: {degradation_desc}
  Dew Factor: {dew_factor} (relevant for evening matches)
  Boundaries: {boundary_size}
  Weather: {temp}°C, Humidity {humidity}%, Wind {wind}

== TOSS IMPACT ==
  At this venue: teams batting first win {bat_first_pct}%, chasing wins {chase_pct}%
  Toss winner typically elects to: {typical_toss_choice}
  Toss result: {toss_result} (if known)

== TEAM PROFILES ==

{team_a} — {record_a} | NRR: {nrr_a} | Standing: #{standing_a}
  Bat First Avg: {bat_first_avg_a} | Chase Avg: {chase_avg_a}
  Powerplay Run Rate: {pp_rr_a} | Death Overs Economy: {death_econ_a}
  Form (Last 5): {form_a}

  Key Players:
    {player1}: {role} | Batting: {avg}/{sr} | Recent: {last_5_innings}
    {player2}: {role} | Bowling: {econ}/{avg} | Recent: {last_5_spells}
    ...

{team_b} — {record_b} | NRR: {nrr_b} | Standing: #{standing_b}
  [same structure]

== HEAD-TO-HEAD ==
  Overall: {h2h_record}
  At This Venue: {h2h_venue}
  Last 3 Meetings:
    {date}: {winner} by {margin} ({venue})
    ...

== MATCH CONTEXT ==
  League Stage: {stage} (group/qualifier/eliminator/final)
  Playoff Implications: {playoff_context}
  Team Motivation: {motivation_notes}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each team. Factor in toss impact, venue history, and current form. Which side has moneyline value?
2. TOTAL RUNS (O/U {line}): Projected total runs. Factor in pitch conditions, powerplay/death bowling quality, boundary dimensions, and dew factor.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite T20 cricket prediction system analyzing a franchise league match.
Simulate a panel of 6 expert analysts:

1. PITCH & CONDITIONS ANALYST: Evaluates the pitch surface, venue history,
   weather conditions, dew factor, and how conditions will change through
   the match. Is this a high-scoring belter or a turning track?
   Does the surface deteriorate for the team batting second?
   This is the MOST IMPORTANT factor in T20 prediction.
2. BATTING ANALYST: Evaluates top-order and middle-order quality, power-hitting
   ability, matchups against the opposition bowling attack, and recent form.
   Powerplay aggression vs death-overs finishing ability.
3. BOWLING ANALYST: Evaluates pace and spin bowling matchups, death bowling
   quality, powerplay wicket-taking ability, and economy rates. How does the
   bowling attack match up on this specific surface?
4. TOSS & CHASE ANALYST: Evaluates the toss impact at this venue. If the
   toss has occurred, how does the decision change probabilities?
   Dew makes chasing significantly easier at subcontinental evening venues.
   What is the historical chase win rate here?
5. MARKET ANALYST: Evaluates the betting lines for value. Is the market
   properly pricing the venue factor? Is a team's recent form masking
   underlying quality? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is a strong team overvalued because
   of brand/IPL auction price? Is a "weak" batting lineup actually better
   suited to this pitch? Is the dew factor being overweighted in dry conditions?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "pitch_conditions", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "team_a_win_prob": 0.XX,
      "team_b_win_prob": 0.XX,
      "value_side": "team_a|team_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_runs": {
      "projected_total": XXX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {
      "winner": "TEAM",
      "winning_margin": "X wickets|X runs",
      "projected_scores": {"batting_first": XXX, "chasing": XXX}
    },
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
BET_SLOTS = ["moneyline", "total_runs"]

EDGE_THRESHOLDS = {
    "moneyline": 0.06,     # 6% min edge (T20 is volatile — higher threshold)
    "total_runs": 0.06,    # 6% min edge
}

# Eighth-Kelly for cricket — T20 has high variance (55% chase win rate = near coin-flip)
KELLY_FRACTION = 0.125
```

---

## Key Differences From MLB

1. **Pitch conditions dominate**: The single biggest factor is the playing surface and venue conditions. This replaces park factors AND pitcher matchup combined. LLMs reading pitch reports add genuine value here.
2. **Toss is a unique random variable**: The coin toss determines batting order, which at some venues shifts win probability by 10-15%. No equivalent in baseball. Must handle both pre-toss and post-toss analysis.
3. **Dew factor**: Evening matches in India/subcontinental venues get dew in the second innings, making the ball slippery (harder to grip for bowlers, easier to bat). This systematically favors chasing. No equivalent in any other sport.
4. **Only 2 bet types**: Match winner and total runs. No spread (cricket doesn't have one), no first half (cricket has innings, but betting on 1st innings score is rare at standard books). Fewer bet types means fewer edges per match.
5. **Low volume**: ~328 T20 matches across all major leagues per year. This is far less than MLB (2,430). Quality over quantity — only bet with high conviction.
6. **Multiple leagues across time zones**: IPL (Mar-May), BBL (Dec-Jan), CPL (Aug-Sep), PSL (Feb-Mar), etc. Each has different conditions, teams, and markets. Build league-specific venue databases.
7. **DLS method**: Rain-interrupted matches use Duckworth-Lewis-Stern to adjust targets. Handle DLS-affected results in the grader.
8. **Franchise leagues ≠ international**: Players play for different franchises each year. Roster composition changes every season via auction/draft.
