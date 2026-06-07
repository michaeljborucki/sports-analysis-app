# MiroFish Soccer Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for professional soccer/football. Start with MLS and Eredivisie (softer lines), then expand to Serie A and other leagues. The system uses a 6-model LLM ensemble with adversarial challenge to predict match outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for soccer.

IMPORTANT: Focus on Asian Handicap and Over/Under 2.5 as primary markets. Avoid 1X2 (3-way) as the primary bet type — the draw makes calibration much harder.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Fixture Schedule
- Source: FBref (via soccerdata Python package) or ESPN API
- Returns: list of upcoming matches with home/away teams, league, matchday, kickoff time, venue

### scrapers/team_stats.py — Team Season Stats
- Source: FBref (powered by StatsBomb) via soccerdata or web scraping
- Per team, return:
  - League position, record (W-D-L), points
  - Goals scored/conceded, goal difference
  - xG (expected goals for), xGA (expected goals against), xGD (differential)
  - xG overperformance: actual goals - xG (positive = lucky finishing, regression candidate)
  - Possession %, pass completion %
  - Shots per 90, shots on target per 90
  - Home record vs away record
  - Last 5 match form (W/D/L string)
  - Clean sheet percentage

### scrapers/xg.py — Expected Goals Detail
- Source: Understat (top 6 European leagues) or FBref
- Per team, return:
  - xG per match (rolling 5-game average)
  - xGA per match (rolling 5-game average)
  - Shot quality breakdown (xG per shot)
  - xG from open play vs set pieces
  - PPDA (passes allowed per defensive action — pressing intensity)

### scrapers/injuries.py — Squad Availability
- Source: Transfermarkt (scrape) or team news pages
- Returns per team:
  - Injured players with expected return date
  - Suspended players (red cards, accumulated yellows)
  - Key player availability tier (star/rotation/bench)
  - Expected lineup changes from last match

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: varies by league (`soccer_epl`, `soccer_usa_mls`, `soccer_netherlands_eredivisie`, etc.)
- Fetch: Asian handicap, over/under 2.5, moneyline (1X2), BTTS
- Return OddsData dataclass with:
  - home, away
  - asian_handicap: {home: point, home_odds: price, away: point, away_odds: price}
  - total: {line: 2.5, over_odds: price, under_odds: price}
  - moneyline_1x2: {home: price, draw: price, away: price}
  - btts: {yes_odds: price, no_odds: price}
  - implied_probs: {ah_home: prob, ah_away: prob, over: prob, under: prob}

### scrapers/context.py — Match Context
- Source: League tables + fixture list analysis
- Returns per match:
  - Fixture congestion (days since last match, days until next)
  - Competition context (league, cup, continental)
  - Motivation factors: title race, relegation battle, mid-table with nothing to play for
  - Derby/rivalry flag
  - Expected rotation (if team has a bigger match within 3 days)
  - Manager tenure (new manager bounce or long-established)

### scrapers/scores.py — Final Scores
- Source: FBref or ESPN API
- Returns per completed match:
  - home, away, home_score, away_score
  - total_goals
  - half_time_score (for HT/FT grading if needed)
  - both_teams_scored: bool

---

## Layer 2: Briefing Template

```
SOCCER MATCH PREDICTION ANALYSIS
==============================
{league} — Matchday {matchday} | {date}
{home} vs {away}
{venue} | Kickoff: {time}

BETTING LINES:
  Asian Handicap: {home} {ah_home} ({ah_home_odds}) / {away} {ah_away} ({ah_away_odds})
  Total: O/U 2.5 (Over {over_odds} / Under {under_odds})
  1X2: {home} {ml_home} / Draw {ml_draw} / {away} {ml_away}
  BTTS: Yes {btts_yes} / No {btts_no}
  Implied AH Prob: {home} {ah_prob_home:.1%} / {away} {ah_prob_away:.1%}

== TEAM PROFILES ==

{home} — {position_home} in {league} | {record_home} | {points_home} pts
  Goals: {gf_home} scored / {ga_home} conceded (GD: {gd_home})
  xG: {xg_home} / xGA: {xga_home} / xGD: {xgd_home}
  xG Overperformance: {xg_over_home} (positive = regression risk)
  Home Record: {home_record_home}
  Form (Last 5): {form_home}
  Possession: {poss_home}% | PPDA: {ppda_home}
  Clean Sheets: {cs_pct_home}%
  Fixture Congestion: {days_since_last_home} days rest, {days_until_next_home} days to next

{away} — {position_away} in {league} | {record_away} | {points_away} pts
  [same structure with away_record]

== xG REGRESSION ANALYSIS ==
  {home} xG vs Actual: {xg_analysis_home}
  {away} xG vs Actual: {xg_analysis_away}
  Regression Candidates: {regression_flags}

== SQUAD AVAILABILITY ==
{home}: {injuries_home}
  Suspensions: {suspensions_home}
  Expected Rotation: {rotation_home}
{away}: {injuries_away}
  Suspensions: {suspensions_away}
  Expected Rotation: {rotation_away}

== MATCH CONTEXT ==
  {home} Motivation: {motivation_home}
  {away} Motivation: {motivation_away}
  Derby/Rivalry: {derby_flag}
  Manager Notes: {manager_notes}
  Head-to-Head (Last 5): {h2h}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. ASIAN HANDICAP ({home} {ah_home}): Will the home team cover the handicap? Factor in xG trends, home advantage, and squad availability.
2. TOTAL GOALS (O/U 2.5): Projected total goals. Does the xG matchup, defensive quality, and motivation suggest goals or a tight affair?
3. BOTH TEAMS TO SCORE: Will both teams find the net? Factor in defensive vulnerabilities, clean sheet rates, and attacking quality.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite soccer/football prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. xG & ATTACKING ANALYST: Evaluates expected goals data, shot quality,
   chance creation, and whether teams are over/underperforming their xG.
   Teams overperforming xG are regression candidates (bearish). Teams
   underperforming are value candidates (bullish).
2. DEFENSIVE & TACTICAL ANALYST: Evaluates defensive structure, pressing
   intensity (PPDA), clean sheet rate, and how the defensive approach
   matches up against the opponent's attacking style. Set piece vulnerability.
3. SQUAD & ROTATION ANALYST: Evaluates injuries, suspensions, and expected
   rotation. If a team has a Champions League match in 3 days, will they
   rest key players? How deep is the squad? New signings settling in?
4. MOTIVATION & CONTEXT ANALYST: Evaluates what's at stake. Title race teams
   play differently than mid-table teams with nothing to play for. Relegation
   battles create desperate, defensive football. Derbies are unpredictable.
5. MARKET ANALYST: Evaluates the betting lines for value. Is the Asian
   handicap reflecting the true quality gap? Is the total line accounting
   for both teams' xG profiles? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is the home team's form masking
   poor underlying xG numbers? Is the away team better than their league
   position suggests? What narrative is the market overweighting?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "xg_attacking", "pick": "TEAM_OR_SIDE", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "asian_handicap": {
      "home_cover_prob": 0.XX,
      "away_cover_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_goals": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "btts": {
      "btts_yes_prob": 0.XX,
      "btts_no_prob": 0.XX,
      "value_side": "yes|no|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_score": {"home": X, "away": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
# Bet types for Soccer — avoid 1X2, focus on 2-way markets
BET_SLOTS = ["asian_handicap", "total", "btts"]

EDGE_THRESHOLDS = {
    "asian_handicap": 0.05,   # 5% min edge
    "total": 0.05,            # 5% min edge
    "btts": 0.06,             # 6% min edge (harder to calibrate)
}

# Kelly sizing — eighth-Kelly for soccer (low scoring = high variance)
KELLY_FRACTION = 0.125
```

---

## Layer 5: Edge Detection Functions

```python
# check_asian_handicap_edge(sim, odds) — similar to MLB run_line
#   - Compare home_cover_prob vs implied from AH odds
#   - Asian handicap can be whole numbers (push possible), half numbers (no push),
#     or quarter numbers (split bet). Start with half-number lines only.
# check_total_edge(sim, odds) — same pattern as MLB total
#   - Over/under on total goals (typically 2.5)
# check_btts_edge(sim, odds) — NEW bet type
#   - Compare btts_yes_prob vs implied from BTTS yes odds
#   - Compare btts_no_prob vs implied from BTTS no odds
#   - Signal the side with more edge above threshold
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade asian_handicap: home_score + handicap vs away_score
#   - E.g., Home -0.5 AH, score 1-1: Home adjusted = 0.5-1 → Away covers
#   - E.g., Home -0.5 AH, score 2-1: Home adjusted = 1.5-1 → Home covers
#   - Handle whole-number AH pushes (refund)
#   - Handle quarter-number AH splits (half win/half push) if implementing
# Grade total: home_score + away_score vs line
#   - Standard over/under grading
# Grade btts: did both teams score at least 1 goal?
#   - Yes: both scores > 0
#   - No: at least one team scored 0
```

---

## Config Adaptations

```python
# Supported leagues and their Odds API sport keys
SUPPORTED_LEAGUES = {
    "MLS": "soccer_usa_mls",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "La Liga": "soccer_spain_la_liga",
    "EPL": "soccer_epl",
    "Ligue 1": "soccer_france_ligue_one",
}

# Start with softer markets
ACTIVE_LEAGUES = ["MLS", "Eredivisie", "Serie A"]

# No park factors — home advantage varies by league
HOME_ADVANTAGE_BY_LEAGUE = {
    "MLS": 0.08,           # ~8% home win boost
    "Eredivisie": 0.10,
    "Serie A": 0.12,
    "EPL": 0.08,
}

GAME_TIMEOUT = 180  # 3 min per match
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
```

---

## Key Differences From MLB

1. **Low scoring = high variance**: Soccer averages ~2.5 goals/match vs ~9 runs in MLB. Use eighth-Kelly (0.125) instead of quarter-Kelly. Expect longer losing streaks and slower convergence.
2. **No 2-way moneyline**: The draw exists (~25% of matches). AVOID 1X2 as primary market — use Asian Handicap (removes draw) and Over/Under 2.5 instead.
3. **xG regression is the primary edge**: Teams outperforming xG regress. This is the soccer equivalent of pitcher ERA vs FIP divergence. The xG scraper is critical.
4. **Rotation and fixture congestion**: Teams playing every 3 days rotate squads. A team's best XI vs their B-team is a huge difference. This is the soccer equivalent of "bullpen fatigue" but more impactful.
5. **Motivation matters enormously**: A mid-table team with nothing to play for vs a relegation-threatened team is a completely different match than the form table suggests. The context scraper must capture this.
6. **Multi-league**: Unlike MLB (one league), soccer spans dozens of leagues. Start with 2-3 leagues with softer lines (MLS, Eredivisie) and expand. Each league needs its own team data.
7. **Year-round**: European season is Aug-May, MLS is Feb-Nov, other leagues fill gaps. Nearly continuous action.
8. **BTTS replaces F5**: Both Teams to Score is a unique soccer market with no MLB equivalent. It requires separate calibration.
9. **Top-league lines are razor-sharp**: EPL/La Liga/Champions League lines are as efficient as NFL. The real opportunity is in MLS, Eredivisie, Liga MX, and other lower-attention leagues.
