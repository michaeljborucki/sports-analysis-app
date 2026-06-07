# MiroFish NCAAB Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for NCAA Division I men's college basketball (NCAAB). The system uses a 6-model LLM ensemble with adversarial challenge to predict game outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for NCAAB.

IMPORTANT CONTEXT: NCAAB scored highest (7.60/10) in our validated analysis. The key advantages: 362 D1 teams overwhelm oddsmakers (soft lines on small conferences), 5,600+ bettable games/season, excellent free data (Bart Torvik, CBBData), and ~700 qualifying bets/year means edge is provable in ~1 season. The main LLM advantage is synthesizing transfer portal impact, coaching changes, and early-season assessment across 362 teams — no human or simple model can track all of them.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Daily Schedule
- Source: ESPN API (undocumented but reliable) or CBBData API
- Returns: list of today's games with home/away teams, game time, venue, conference

### scrapers/team_stats.py — Team Efficiency Ratings
- Source: Bart Torvik (barttorvik.com) — FREE, downloadable CSV/JSON
- Also: CBBData R package / API (free key, ~30 endpoints, updates every 15 min)
- Per team, return:
  - Adjusted Offensive Efficiency (AdjOE) — points per 100 possessions, adjusted for opponent
  - Adjusted Defensive Efficiency (AdjDE) — points allowed per 100 possessions, adjusted
  - Adjusted Tempo — possessions per 40 minutes
  - Strength of Schedule (SOS)
  - T-Rank (overall composite ranking)
  - Luck factor (deviation from expected wins)
  - Record (overall, conference, home, away)
  - Last 10 games record and trend
  - Four Factors (offense and defense):
    - eFG% (effective field goal %)
    - TOV% (turnover %)
    - OREB% (offensive rebound %)
    - FT Rate (free throw rate)
  - 3PT attempt rate and accuracy
  - Conference name and standing
- Optional KenPom supplement ($25/yr) for:
  - KenPom ratings (AdjEM, AdjO, AdjD)
  - Pythagorean win % and luck

### scrapers/roster.py — Roster Continuity & Key Players
- Source: Bart Torvik (returning minutes %), CBBData, or ESPN
- Per team, return:
  - Returning minutes % (how much of last year's production is back)
  - Transfer portal additions (names, previous school, stats at previous school)
  - Key player stats: top 5 scorers with PPG, RPG, APG, eFG%
  - Freshman impact players (recruiting ranking)
  - Coaching tenure (years at school)
  - Coaching change flag (new coach this season)

### scrapers/injuries.py — Injury & Availability
- Source: ESPN injury reports, team beat reporters, DonBest
- NOTE: NCAA has NO mandatory injury reporting (unlike NFL). This is a key information asymmetry.
- Returns per team:
  - Known injuries with status (out/doubtful/questionable)
  - Player importance tier (star/rotation/bench)
  - Minutes per game of injured player

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: `basketball_ncaab`
- Fetch: spread, moneyline, total, 1st half spread, 1st half total
- Return OddsData dataclass with:
  - home, away
  - spread: {home: point, home_odds: price, away: point, away_odds: price}
  - moneyline: {home: price, away: price}
  - total: {line: XXX.5, over_odds: price, under_odds: price}
  - h1_spread: {home: point, home_odds: price, away: point, away_odds: price}
  - h1_total: {line: XX.5, over_odds: price, under_odds: price}
  - implied_probs: {ml_home: prob, ml_away: prob} (vig-removed)

### scrapers/matchup.py — Matchup Context
- Source: Computed from team_stats + schedule context
- Returns:
  - Projected pace (average of both teams' tempo)
  - Projected possessions
  - Efficiency gap (AdjEM difference)
  - Conference game flag
  - Rivalry flag
  - Tournament context (conference tourney, NCAA tourney, NIT)
  - Quad 1/2/3/4 classification of the game (NET-based)
  - Travel distance and time zone change

### scrapers/scores.py — Final Scores
- Source: ESPN API or CBBData
- Returns per completed game:
  - home, away, home_score, away_score
  - home_score_h1, away_score_h1 (first half)
  - total_points, total_points_h1

---

## Layer 2: Briefing Template

```
NCAAB GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}, #{away_trank}) at {home} ({home_record}, #{home_trank})
{venue} | {conference_context} | {game_time}

BETTING LINES:
  Spread: {home} {spread_home} ({spread_home_odds}) / {away} {spread_away} ({spread_away_odds})
  Moneyline: {home} {ml_home} / {away} {ml_away}
  Total: {total_line} (Over {over_odds} / Under {under_odds})
  1H Spread: {home} {h1_spread_home} ({h1_spread_home_odds})
  1H Total: {h1_total_line} (Over {h1_over_odds} / Under {h1_under_odds})
  Implied Win Prob: {home} {prob_home:.1%} / {away} {prob_away:.1%}

== EFFICIENCY PROFILES ==

{away} — T-Rank: #{trank_away} | AdjEM: {adjem_away}
  AdjOE: {adjoe_away} (#{adjoe_rank_away}) | AdjDE: {adjde_away} (#{adjde_rank_away})
  Tempo: {tempo_away} poss/40min
  Record: {record_away} | Conf: {conf_record_away} | Away: {away_record_away}
  Last 10: {l10_away} | Trend: {trend_away}
  Four Factors (Off): eFG% {efg_off_away} | TOV% {tov_off_away} | OREB% {oreb_off_away} | FT Rate {ftr_off_away}
  Four Factors (Def): eFG% {efg_def_away} | TOV% {tov_def_away} | OREB% {oreb_def_away} | FT Rate {ftr_def_away}
  3PT: {three_rate_away} attempt rate, {three_pct_away}%
  SOS: {sos_away} | Luck: {luck_away}

{home} — T-Rank: #{trank_home} | AdjEM: {adjem_home}
  AdjOE: {adjoe_home} (#{adjoe_rank_home}) | AdjDE: {adjde_home} (#{adjde_rank_home})
  Tempo: {tempo_home} poss/40min
  Record: {record_home} | Conf: {conf_record_home} | Home: {home_record_home}
  Last 10: {l10_home} | Trend: {trend_home}
  [same Four Factors structure]

== TEMPO MATCHUP ==
  Projected Pace: {projected_tempo} poss/40min
  Projected Possessions: {projected_poss}
  Tempo Mismatch: {mismatch_desc}
  Projected Total (efficiency × possessions): {projected_total}

== ROSTER CONTEXT ==
{away}:
  Returning Minutes: {ret_min_away}%
  Key Players: {top_scorers_away}
  Notable Transfers In: {transfers_in_away}
  Coach: {coach_away} ({tenure_away} years) {new_coach_flag_away}

{home}:
  Returning Minutes: {ret_min_home}%
  Key Players: {top_scorers_home}
  Notable Transfers In: {transfers_in_home}
  Coach: {coach_home} ({tenure_home} years) {new_coach_flag_home}

== INJURIES ==
{away}: {injuries_away}
{home}: {injuries_home}
(NOTE: NCAA has no mandatory injury reporting — information may be incomplete)

== GAME CONTEXT ==
  Conference: {conference_context}
  Rivalry: {rivalry_flag}
  Quad: {quad_classification}
  Tournament Implications: {tourney_context}
  Travel: {travel_context}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. SPREAD ({home} {spread_home}): Will the favorite cover? Factor in efficiency gap, tempo matchup, home court, and roster quality.
3. TOTAL (O/U {total_line}): Projected total points. Does the tempo matchup, efficiency ratings, and pace projection point over or under?
4. FIRST HALF: Who leads at halftime? What's the projected 1H total? Consider early-game pace and team tendencies.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite NCAAB prediction system analyzing a college basketball game.
Simulate a panel of 6 expert analysts:

1. EFFICIENCY ANALYST: Evaluates tempo-free efficiency metrics — adjusted offensive
   and defensive efficiency, Four Factors (eFG%, TOV%, OREB%, FT Rate). How do
   the efficiency profiles match up? Which team has the fundamental edge?
2. TEMPO & MATCHUP ANALYST: Evaluates pace matchup and how it affects scoring.
   Fast team vs slow team = what projected pace? How many possessions?
   This directly drives the total prediction. Projected score = efficiency × pace.
3. ROSTER & TRANSFER ANALYST: Evaluates returning production, transfer portal
   impact, coaching stability, and key player contributions. Is this roster
   better or worse than last year? Have new transfers integrated?
   Early season (Nov-Dec) this analyst carries extra weight.
4. SITUATIONAL ANALYST: Evaluates home court advantage, conference dynamics,
   rivalry factor, tournament implications (bubble team needing a win?),
   travel fatigue, and scheduling spots (lookahead, letdown).
5. MARKET ANALYST: Evaluates the betting lines for value. Is the spread
   properly reflecting the efficiency gap? Is the total accounting for tempo?
   Small-conference games are often mispriced — is this one of them?
6. CONTRARIAN: Challenges the consensus. Is a highly-ranked team overvalued
   by reputation? Is a mid-major being dismissed? Is the "new transfers =
   better team" narrative actually wrong because of chemistry issues?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "efficiency", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "home_win_prob": 0.XX,
      "away_win_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "spread": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": XXX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_half": {
      "h1_home_win_prob": 0.XX,
      "h1_away_win_prob": 0.XX,
      "h1_projected_total": XX.X,
      "h1_ml_value": "home|away|none",
      "h1_total_value": "over|under|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": XX, "home": XX},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
BET_SLOTS = ["moneyline", "spread", "total", "first_half_ml", "first_half_total"]

EDGE_THRESHOLDS = {
    "moneyline": 0.05,         # 5% min edge
    "spread": 0.05,            # 5% min edge (softer lines than NBA — can be tighter)
    "total": 0.05,             # 5% min edge
    "first_half_ml": 0.05,     # 5% min edge
    "first_half_total": 0.05,  # 5% min edge
}

KELLY_FRACTION = 0.25  # quarter-Kelly
```

---

## Layer 5: Edge Detection Functions

```python
# check_moneyline_edge(sim, odds) — identical to MLB pattern
# check_spread_edge(sim, odds) — identical to MLB run_line pattern
#   - Rename run_line → spread. favorite_cover_prob stays the same concept.
# check_total_edge(sim, odds) — identical to MLB total pattern
#   - NCAAB totals are ~120-160 range
# check_h1_ml_edge(sim, odds) — identical to MLB F5 ML pattern
# check_h1_total_edge(sim, odds) — identical to MLB F5 total pattern
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade moneyline: straightforward winner comparison
# Grade spread: home_score + spread vs away_score
# Grade total: home_score + away_score vs line
# Grade first_half_ml: h1 score comparison
# Grade first_half_total: h1_home + h1_away vs h1_line
# All standard — no special cases (unlike NHL OT or tennis retirements)
```

---

## Config Adaptations

```python
TORVIK_BASE = "https://barttorvik.com"
CBBDATA_API_KEY = os.getenv("CBBDATA_API_KEY", "")
ODDS_SPORT_KEY = "basketball_ncaab"

# 362 D1 teams — too many for a static list. Load dynamically from Torvik/CBBData.
# Conference list for filtering:
POWER_CONFERENCES = ["SEC", "B10", "B12", "ACC", "BE"]
MID_MAJOR_CONFERENCES = ["A10", "MWC", "WCC", "MVC", "Amer", "CUSA", "SB", "MAC"]
# ... etc for all 32 conferences

# Home court advantage varies by venue — average ~3.5 points in college
HOME_COURT_ADVANTAGE = 3.5

GAME_TIMEOUT = 300
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Season: November through early April
# Peak volume: Saturdays in January-February (80-100 games)
# March Madness: mid-March through early April (67 games over 3 weeks)
```

---

## Key Differences From MLB

1. **Efficiency metrics replace pitcher matchup**: The "starting pitcher" equivalent is the team efficiency gap (AdjOE vs opponent AdjDE). Tempo-free efficiency is the single strongest predictor in college basketball.
2. **Tempo drives totals**: Projected total = (team_A_adjOE + team_B_adjOE) / 2 × projected_possessions / 100. This is more formulaic than MLB totals.
3. **362 teams = structural edge**: Oddsmakers can't deeply model every team. Small-conference games (Ohio Valley, SWAC, Southland) are systematically mispriced. Target these.
4. **No mandatory injury reporting**: NCAA doesn't require injury disclosures like NFL. Beat reporter monitoring and social media scraping provide an information edge.
5. **Transfer portal creates early-season chaos**: ~2,000 players transfer annually. November/December games have the most mispricing because rosters are new and untested.
6. **March Madness is a separate beast**: 67 games over 3 weeks with massive public betting. Casual money floods in on brand names (Duke, Kentucky) creating contrarian value on underdogs.
7. **Home court advantage is larger**: ~3.5 points in college vs ~3 in NBA. Hostile environments (Cameron Indoor, Allen Fieldhouse, Rupp Arena) can be worth 5+ points.
8. **Conference familiarity matters**: Late-season conference games between teams that have already played each other this season behave differently than non-conference games.
9. **Free data is excellent**: Bart Torvik provides KenPom-quality analytics for free. CBBData has 30 endpoints updated every 15 minutes. No equivalent exists for MLB at this quality for free.
