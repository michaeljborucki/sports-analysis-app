# MiroFish Tennis Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for professional tennis (ATP and WTA). The system uses a 6-model LLM ensemble with adversarial challenge to predict match outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for tennis.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Tournament & Match Schedule
- Source: ATP/WTA official sites or API-Tennis (api-tennis.com, free trial)
- Returns: list of upcoming matches with player names, tournament, round, surface, indoor/outdoor, draw size

### scrapers/players.py — Player Profiles
- Source: Jeff Sackmann's GitHub repos (tennis_atp / tennis_wta) — CC BY-NC-SA 4.0
- Per player, return:
  - Current ranking and ranking points
  - Elo rating (overall and surface-specific: hard, clay, grass)
  - Record this season (overall and by surface)
  - Serve stats: 1st serve %, 1st serve win %, 2nd serve win %, ace rate, double fault rate
  - Return stats: return points won %, break point conversion %
  - Recent form: last 10 match results (opponent, score, surface, tournament, round)
  - Surface-specific career record (hard/clay/grass)
  - Head-to-head record vs opponent (overall and surface-specific)
  - Age, height, handedness (R/L), backhand (1H/2H)
  - Days since last match (freshness/fatigue indicator)
  - Tournament history at this specific event (past results)

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: `tennis_atp` or `tennis_wta` (or specific tournament keys)
- Fetch: match winner (moneyline), set handicap, total games, set betting
- Return OddsData dataclass with:
  - player_a, player_b
  - moneyline: {player_a: price, player_b: price}
  - game_handicap: {player_a: point, player_a_odds: price, player_b: point, player_b_odds: price}
  - total_games: {line: XX.5, over_odds: price, under_odds: price}
  - set_handicap: {player_a: point, player_a_odds: price, ...} (if available)
  - implied_probs: {player_a: prob, player_b: prob} (vig-removed)

### scrapers/conditions.py — Match Conditions
- Source: Tournament info + weather API (for outdoor events)
- Returns:
  - Surface: hard (indoor/outdoor), clay, grass
  - Altitude (e.g., Bogota is high altitude = faster ball)
  - Temperature, humidity, wind
  - Indoor vs outdoor
  - Day vs night session
  - Ball type (different tournaments use different balls)

### scrapers/news.py — Player Context
- Source: Tennis news sites, social media, press conferences
- Returns per player:
  - Injury reports and physical condition
  - Recent withdrawal history
  - Tournament motivation context (defending points, ranking implications)
  - Coaching changes
  - Personal news that might affect performance

### scrapers/scores.py — Match Results
- Source: Jeff Sackmann repos or API-Tennis
- Returns per completed match:
  - player_a, player_b
  - final_score (e.g., "6-4 3-6 7-5")
  - winner
  - total_games
  - sets (for set handicap grading)
  - retirement flag (did a player retire mid-match?)

---

## Layer 2: Briefing Template

```
TENNIS MATCH PREDICTION ANALYSIS
==============================
{tournament_name} — {round} | {surface} ({indoor_outdoor})
{player_a} vs {player_b} | Best of {sets}

BETTING LINES:
  Moneyline: {player_a} {ml_a} / {player_b} {ml_b}
  Game Handicap: {player_a} {gh_a} ({gh_a_odds}) / {player_b} {gh_b} ({gh_b_odds})
  Total Games: {line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {player_a} {prob_a:.1%} / {player_b} {prob_b:.1%}

== PLAYER PROFILES ==

{player_a} — Rank #{rank_a} | Elo: {elo_a} ({surface}_Elo: {surface_elo_a})
  Season Record: {record_a} | {surface} Record: {surface_record_a}
  Serve: {first_serve_pct_a}% 1st in, {first_serve_win_a}% 1st won, {second_serve_win_a}% 2nd won
  Aces/DF per match: {aces_a}/{df_a}
  Return: {return_pts_won_a}% pts won | Break Point Conv: {bp_conv_a}%
  Hand: {hand_a} | Backhand: {bh_a} | Height: {height_a}
  Days Since Last Match: {freshness_a}
  Tournament History: {event_history_a}
  Recent Form (Last 10):
    {date} {tournament} {round}: vs {opp} {score} ({surface})
    ...

{player_b} — Rank #{rank_b} | Elo: {elo_b} ({surface}_Elo: {surface_elo_b})
  [same structure]

== HEAD-TO-HEAD ==
  Overall: {h2h_record}
  On {surface}: {h2h_surface_record}
  Last 3 Meetings:
    {date}: {winner} d. {loser} {score} ({surface}, {tournament})
    ...

== CONDITIONS ==
  Surface: {surface} ({indoor_outdoor})
  Temperature: {temp}°F | Wind: {wind_mph}mph
  Altitude: {altitude}ft
  Session: {day_night}
  Conditions Impact: {conditions_analysis}

== CONTEXT ==
  Tournament Category: {grand_slam|masters_1000|atp_500|atp_250|challenger}
  Defending Points: {player_a}: {def_pts_a} | {player_b}: {def_pts_b}
  Stakes: {ranking_implications}
  Draw Path: {draw_context}

== INJURIES / FITNESS ==
{player_a}: {injury_info_a}
{player_b}: {injury_info_b}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each player. Which side has moneyline value?
2. GAME HANDICAP ({player_a} {gh_a}): Will the favorite cover the game spread? Factor in serve dominance, break frequency, and surface fit.
3. TOTAL GAMES (O/U {line}): Projected total games. Does the serve/return matchup, surface speed, and match competitiveness suggest a long or short match?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite tennis prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. SERVE ANALYST: Evaluates serve quality, first serve percentage, ace potential,
   second serve vulnerability, and how the serve matches up against the returner's
   skills. Service game hold percentages on this surface.
2. RETURN & RALLY ANALYST: Evaluates return effectiveness, ability to neutralize
   serve, baseline rally tolerance, and break point conversion. Who controls
   the rallies from the back of the court?
3. SURFACE & CONDITIONS ANALYST: Evaluates how each player's game translates to
   this specific surface. Clay grinders on hard courts, grass specialists on clay, etc.
   Altitude, temperature, ball speed, and indoor/outdoor adjustments.
4. FORM & FITNESS ANALYST: Evaluates recent results, match load, travel schedule,
   injury concerns, and competitive sharpness. Is this player peaking or fatigued?
   Surface transition effects (just switched from clay to grass, etc.).
5. MARKET ANALYST: Evaluates the betting lines for value. Is the market
   correctly pricing the surface matchup? Is name recognition inflating the
   favorite's odds? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What upset scenario is being overlooked?
   Is the favorite's recent form on a different surface? Is the underdog's
   style a bad matchup for the favorite? Motivation factors (defending champion
   vs player with nothing to lose)?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "serve", "pick": "PLAYER", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "player_a_win_prob": 0.XX,
      "player_b_win_prob": 0.XX,
      "value_side": "player_a|player_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "game_handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_games": {
      "projected_games": XX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "PLAYER", "score": "6-4 6-3"},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
# Bet types for Tennis
BET_SLOTS = ["moneyline", "game_handicap", "total_games"]

EDGE_THRESHOLDS = {
    "moneyline": 0.05,       # 5% min edge
    "game_handicap": 0.06,   # 6% min edge
    "total_games": 0.05,     # 5% min edge
}

# Kelly sizing — quarter-Kelly standard, consider eighth-Kelly for WTA (higher variance)
KELLY_FRACTION = 0.25          # ATP
KELLY_FRACTION_WTA = 0.125     # WTA (more upsets)
```

---

## Layer 5: Edge Detection Functions

```python
# check_moneyline_edge(sim, odds) — same pattern as MLB, compare player_a/b win probs vs implied
# check_game_handicap_edge(sim, odds) — same pattern as MLB run_line
#   - Favorite is the side with negative game handicap (e.g., -4.5 games)
# check_total_games_edge(sim, odds) — same pattern as MLB total
#   - Over/under on total games played in the match
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade moneyline: straightforward winner comparison
#   - IMPORTANT: Handle retirements. If player retires mid-match, most books void
#     moneyline bets or grade based on rules. Flag retirements for manual review.
# Grade game_handicap: count total games won by each player, apply handicap
#   - E.g., Player A wins 6-4 6-3 = 12 games won, Player B = 7 games won
#   - If Player A had -4.5 handicap: 12-4.5=7.5 vs 7 → Player A covers
# Grade total_games: count total games in match vs line
#   - E.g., 6-4 6-3 = 19 total games. Line was 21.5 → under wins.
# Grade set_handicap: count sets won, apply handicap (if betting this market)
```

---

## Config Adaptations

```python
# Data sources
SACKMANN_ATP_REPO = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_WTA_REPO = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"
ODDS_SPORT_KEY_ATP = "tennis_atp"
ODDS_SPORT_KEY_WTA = "tennis_wta"

# No team abbreviations — use player names
# Surface types matter hugely — track per surface

GAME_TIMEOUT = 180  # 3 min per match analysis

ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
```

---

## Key Differences From MLB

1. **Individual sport**: 1v1 matchup, not team vs team. Player profiles replace team profiles.
2. **Surface is the dominant factor**: A player's surface-specific Elo and record matters more than overall ranking. The briefing must prominently feature surface context. This replaces park factors.
3. **Head-to-head matters**: Unlike MLB where pitcher matchups reset, tennis H2H records reflect persistent stylistic matchups. Include H2H prominently.
4. **Withdrawal/retirement risk**: Players withdraw before or retire during matches far more than in team sports. Build void-handling into the results grader. Flag retirement risk in briefing for injury-prone players.
5. **Year-round season**: ~11 months of continuous play (Jan-Nov). No offseason dead period. Much higher annual volume than MLB.
6. **Best-of-3 vs Best-of-5**: Grand Slams are Bo5 (men), everything else is Bo3. Format affects variance. Consider higher thresholds for Bo3.
7. **Multiple simultaneous tournaments**: Unlike MLB where all games are the same league, tennis has 3-4 tournaments running simultaneously. Each has different surface/conditions.
8. **No sub-period market equivalent**: No F5 innings or first half. Replace with set handicap or first set winner if markets are available.
9. **ATP vs WTA**: WTA has more upsets, softer lines, and higher variance. Consider separate Kelly fractions and edge thresholds for WTA.
10. **Motivation factor**: Top players sometimes don't try at 250-level events after Grand Slams. This is hard to quantify but matters. The contrarian analyst should specifically address this.

## RISKS TO WATCH

- **Prediction ceiling**: ~67-70% match-winner accuracy regardless of methodology. Edges are thin.
- **Retirement voids**: Can wipe out a day's profit if a heavily-bet match is voided.
- **Bet limits on soft markets**: Challenger/early-round WTA limits can be $200-500.
- **Motivation opacity**: Impossible to truly know if a player is fully committed.
- **Surface transition noise**: First week on a new surface is high-variance.
