# MiroFish NBA Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for NBA basketball. The system uses a 6-model LLM ensemble with adversarial challenge to predict game outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for NBA basketball.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Daily Schedule
- Source: nba_api (swar/nba_api on GitHub) or NBA.com undocumented endpoints
- Returns: list of today's games with home/away teams, game time, arena

### scrapers/team_stats.py — Team Season Stats
- Source: nba_api (TeamDashboardByGeneralSplits, LeagueDashTeamStats)
- Per team, return:
  - Record (W-L, home record, away record)
  - Offensive rating, Defensive rating, Net rating
  - Pace (possessions per 48 min)
  - eFG%, TOV%, OREB%, FT rate (Four Factors)
  - 3PT attempt rate and accuracy
  - Last 10 record and trend
  - Back-to-back flag (is this the 2nd night of a B2B?)
  - Days rest since last game

### scrapers/injuries.py — Injury Report
- Source: nba_api (PlayerDashboardByGameSplits) or official NBA injury report page
- Returns per team: list of injured/questionable/out players with status and impact tier (star/rotation/bench)
- Critical: flag when a top-5 minute player is OUT — this is the biggest line mover

### scrapers/matchup.py — Matchup-Specific Data
- Source: nba_api (TeamVsPlayer, BoxScoreAdvancedV3)
- Returns:
  - Head-to-head record this season
  - Pace matchup projection (fast vs slow team)
  - Defensive rating against opponent's playstyle
  - Key player matchup notes

### scrapers/rest.py — Rest & Travel
- Source: Compute from schedule data
- Returns per team:
  - Days rest (0 = back-to-back, 1 = normal, 2+ = extra rest)
  - Travel distance from last game (miles)
  - Time zone change
  - Games in last 7 days
  - Road trip length (consecutive away games)

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: `basketball_nba`
- Fetch: moneyline, point spread, total, 1st half spread, 1st half total
- Return OddsData dataclass with:
  - home, away
  - moneyline: {home: price, away: price}
  - spread: {home: point, home_odds: price, away: point, away_odds: price}
  - total: {line: X.5, over_odds: price, under_odds: price}
  - h1_spread: {home: point, home_odds: price, away: point, away_odds: price}
  - h1_total: {line: X.5, over_odds: price, under_odds: price}
  - implied_probs: {ml_home: prob, ml_away: prob} (vig-removed)

### scrapers/scores.py — Final Scores
- Source: nba_api (ScoreboardV2 or LeagueGameFinder)
- Returns per completed game:
  - home, away, home_score, away_score
  - home_score_h1, away_score_h1 (first half)
  - total_points, total_points_h1

---

## Layer 2: Briefing Template

```
NBA GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}) at {home} ({home_record})
{arena} | {game_time}

BETTING LINES:
  Moneyline: {home} {ml_home} / {away} {ml_away}
  Spread: {home} {spread_home} ({spread_home_odds}) / {away} {spread_away} ({spread_away_odds})
  Total: {total_line} (Over {over_odds} / Under {under_odds})
  1H Spread: {home} {h1_spread_home} ({h1_spread_home_odds})
  1H Total: {h1_total_line} (Over {h1_over_odds} / Under {h1_under_odds})
  Implied Win Prob: {home} {prob_home:.1%} / {away} {prob_away:.1%}

== TEAM PROFILES ==

{away} — {away_record} ({away_away_record} away)
  Off Rtg: {ortg_away} | Def Rtg: {drtg_away} | Net: {net_away}
  Pace: {pace_away} | eFG%: {efg_away} | TOV%: {tov_away}
  3PT Rate: {three_rate_away} | 3PT%: {three_pct_away}
  Last 10: {l10_away} | Trend: {trend_away}
  Rest: {rest_days_away} days | B2B: {b2b_away}
  Travel: {travel_away} miles from last game

{home} — {home_record} ({home_home_record} home)
  Off Rtg: {ortg_home} | Def Rtg: {drtg_home} | Net: {net_home}
  Pace: {pace_home} | eFG%: {efg_home} | TOV%: {tov_home}
  3PT Rate: {three_rate_home} | 3PT%: {three_pct_home}
  Last 10: {l10_home} | Trend: {trend_home}
  Rest: {rest_days_home} days | B2B: {b2b_home}

== PACE MATCHUP ==
  Projected Pace: {projected_pace} (avg of both teams)
  Projected Possessions: {projected_possessions}
  Pace Mismatch: {mismatch_description}

== INJURIES ==
{away}: {injury_list_away}
{home}: {injury_list_home}

== REST & SCHEDULE CONTEXT ==
  Rest Advantage: {rest_advantage_description}
  {away} schedule: {recent_schedule_away}
  {home} schedule: {recent_schedule_home}

== HEAD-TO-HEAD ==
  Season Series: {h2h_record}
  Last Meeting: {last_meeting_result}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. SPREAD ({home} {spread_home}): Will the favorite cover? Factor in rest, pace matchup, and injury impact.
3. TOTAL (O/U {total_line}): Projected total points. Does the pace matchup, defensive ratings, and rest situation point over or under?
4. FIRST HALF: Based on starting lineups and early-game tendencies, who leads at halftime? What's the projected 1H total?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite NBA prediction system analyzing a game.
Simulate a panel of 6 expert analysts:

1. OFFENSIVE ANALYST: Evaluates offensive efficiency, shot selection, spacing,
   three-point shooting, and how the offense matches up against the defensive scheme.
   Pace-adjusted scoring projections.
2. DEFENSIVE ANALYST: Evaluates defensive rating, rim protection, perimeter defense,
   transition defense, and how the defense matches the opponent's primary actions.
3. PACE & TEMPO ANALYST: Evaluates pace matchup, projected possessions, and how
   tempo affects total scoring. Fast vs slow teams, half-court vs transition.
   Critical for over/under predictions.
4. REST & SCHEDULE ANALYST: Evaluates rest days, back-to-backs, travel distance,
   time zones, and fatigue factors. Teams on 0 rest shoot worse and defend worse.
   This drives spread and total adjustments.
5. MARKET ANALYST: Evaluates the betting lines for value. Where is the
   public money likely flowing? Is the spread reflecting rest/injury adjustments
   properly? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What narrative is the public overweighting?
   Is a resting team still being priced as full-strength? Is a B2B impact
   already baked into the line?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "offensive", "pick": "TEAM", "reasoning": "..."},
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
    "predicted_score": {"away": XXX, "home": XXX},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
# Bet types for NBA
BET_SLOTS = ["moneyline", "spread", "total", "first_half_ml", "first_half_total"]

EDGE_THRESHOLDS = {
    "moneyline": 0.05,         # 5% min edge
    "spread": 0.06,            # 6% min edge (lines are sharp)
    "total": 0.05,             # 5% min edge
    "first_half_ml": 0.05,     # 5% min edge
    "first_half_total": 0.05,  # 5% min edge
}

# Kelly sizing — quarter-Kelly (same as MLB)
KELLY_FRACTION = 0.25
```

---

## Layer 5: Edge Detection Functions

```python
# check_moneyline_edge(sim, odds) — identical pattern to MLB
# check_spread_edge(sim, odds) — identical pattern to MLB run_line
#   - Rename: "run_line" → "spread", favorite_cover_prob stays the same
#   - Spread is typically -X.5 (no pushes in NBA)
# check_total_edge(sim, odds) — identical pattern to MLB total
#   - NBA totals are ~210-230 range instead of 7-12
# check_h1_ml_edge(sim, odds) — identical pattern to MLB F5 ML
# check_h1_total_edge(sim, odds) — identical pattern to MLB F5 total
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade moneyline: straightforward winner comparison
# Grade spread: home_score + spread vs away_score (or vice versa)
# Grade total: home_score + away_score vs line
# Grade first_half_ml: h1 score comparison
# Grade first_half_total: h1_home_score + h1_away_score vs h1_line
```

---

## Config Adaptations

```python
# API — nba_api uses NBA.com endpoints, no API key needed
NBA_API_AVAILABLE = True  # pip install nba_api
ODDS_SPORT_KEY = "basketball_nba"

# No park factors (home court advantage is uniform ~3 points)
HOME_COURT_ADVANTAGE = 3.0  # approximate points

# Team abbreviations — 30 NBA teams
TEAM_ABBREVS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

GAME_TIMEOUT = 300  # 5 min per game
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
```

---

## Key Differences From MLB

1. **No pitcher matchup**: The single biggest factor in MLB (starting pitcher) has no direct equivalent. Replace with team-level offensive/defensive efficiency + rest/injury context.
2. **Spread replaces run line**: NBA spreads range from -1.5 to -15+, vs MLB's fixed -1.5. The spread market is the primary NBA bet (not moneyline).
3. **First half replaces first 5 innings**: Same concept (sub-game period), but driven by starting lineup efficiency rather than starting pitcher.
4. **Rest and B2Bs are the primary edge**: Teams on 0 rest lose ~2-3 points of efficiency. Markets sometimes underprice this. The REST scraper is critical.
5. **Pace matchup drives totals**: Two fast teams = high total, fast vs slow = uncertain. Projected possessions × efficiency = projected score. This is more formulaic than MLB totals.
6. **Late injury news**: Stars rest unexpectedly 1-2 hours before tip. The pipeline should run as close to game time as possible to capture late news.
7. **Sharp lines**: NBA closing lines are among the sharpest in sports. Edges will be thinner than MLB. Focus on early-line timing, rest spots, and injury cascading effects.
