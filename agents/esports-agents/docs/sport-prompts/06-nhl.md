# MiroFish NHL Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for NHL hockey. The system uses a 6-model LLM ensemble with adversarial challenge to predict game outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for NHL hockey.

IMPORTANT: Hockey has the highest variance of any major sport (~53% luck factor). Use conservative Kelly sizing (eighth-Kelly), higher edge thresholds, and expect longer drawdown periods. The goalie confirmation edge is the primary timing advantage.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Daily Schedule
- Source: NHL API (api-web.nhle.com/v1/) — free, no key required
- Python wrapper: nhl-api-py (pip install nhl-api-py)
- Returns: list of today's games with home/away teams, game time, venue

### scrapers/team_stats.py — Team Season Stats
- Source: NHL API + MoneyPuck (downloadable CSVs)
- Per team, return:
  - Record (W-L-OTL), points, points percentage
  - Goals for/against per game
  - xGF/xGA per 60 (expected goals for/against)
  - Corsi % (shot attempt share at 5v5)
  - Fenwick % (unblocked shot attempt share)
  - Power play %: PP goals / PP opportunities
  - Penalty kill %
  - Home record vs away record
  - Last 10 record
  - Back-to-back flag

### scrapers/goalies.py — Goalie Matchup (CRITICAL)
- Source: DailyFaceoff.com (confirmed starters ~90 min before puck drop) + NHL API
- Per confirmed starter, return:
  - Name, games started this season
  - Save percentage (SV%), Goals against average (GAA)
  - Goals saved above expected (GSAx) — the key advanced stat
  - Record (W-L-OTL)
  - Recent form: last 5 starts (date, opponent, saves, GA, SV%)
  - Days rest since last start
  - Home/away splits
  - Head-to-head record vs opponent
- ALSO return: starter vs backup quality gap for this team (how much worse is the backup?)

### scrapers/rest.py — Rest & Travel
- Source: Compute from schedule data
- Returns per team:
  - Days rest (0 = back-to-back)
  - Travel distance from last game
  - Time zone change
  - Games in last 7 days
  - Road trip length

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: `icehockey_nhl`
- Fetch: moneyline, puck line (-1.5), total, period betting (1st period)
- Return OddsData dataclass with:
  - home, away
  - moneyline: {home: price, away: price}
  - puck_line: {home: point, home_odds: price, away: point, away_odds: price}
  - total: {line: X.5, over_odds: price, under_odds: price}
  - p1_moneyline: {home: price, away: price} (1st period, if available)
  - p1_total: {line: X.5, over_odds: price, under_odds: price} (1st period)
  - implied_probs: {ml_home: prob, ml_away: prob} (vig-removed)

### scrapers/special_teams.py — Power Play & Penalty Kill
- Source: NHL API
- Returns per team:
  - Power play %: rank, recent trend (last 10 games)
  - Penalty kill %: rank, recent trend
  - Penalties taken per game (discipline factor)
  - PP opportunities per game (opponent discipline)

### scrapers/scores.py — Final Scores
- Source: NHL API
- Returns per completed game:
  - home, away, home_score, away_score
  - regulation_score (before OT/SO)
  - overtime flag, shootout flag
  - p1_home_score, p1_away_score (1st period)
  - total_goals, total_goals_p1

### scrapers/news.py — Injuries & Context
- Source: NHL API + team news
- Returns:
  - Injury list per team with status
  - Notable scratches
  - Lineup changes

---

## Layer 2: Briefing Template

```
NHL GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}) at {home} ({home_record})
{venue} | Puck Drop: {time}

BETTING LINES:
  Moneyline: {home} {ml_home} / {away} {ml_away}
  Puck Line: {home} {pl_home} ({pl_home_odds}) / {away} {pl_away} ({pl_away_odds})
  Total: {total_line} (Over {over_odds} / Under {under_odds})
  1P Total: {p1_line} (Over {p1_over} / Under {p1_under})
  Implied Win Prob: {home} {prob_home:.1%} / {away} {prob_away:.1%}

== GOALIE MATCHUP ==

{away_goalie} ({away}) — {record_away_g}
  SV%: {svpct_away} | GAA: {gaa_away} | GSAx: {gsax_away}
  Last 5 Starts:
    {date} vs {opp}: {saves}/{shots} ({svpct}) — {result}
    ...
  Days Rest: {rest_away_g}
  Starter Quality Gap: {quality_gap_away} (starter vs backup GSAx difference)

{home_goalie} ({home}) — {record_home_g}
  [same structure]

== TEAM PROFILES ==

{away} — {away_record} | {away_pts} pts
  GF/G: {gfg_away} | GA/G: {gag_away}
  xGF/60: {xgf_away} | xGA/60: {xga_away}
  Corsi%: {corsi_away} | Fenwick%: {fenwick_away}
  PP: {pp_away}% (#{pp_rank_away}) | PK: {pk_away}% (#{pk_rank_away})
  Last 10: {l10_away}
  Rest: {rest_away} days | B2B: {b2b_away}
  Travel: {travel_away} miles

{home} — {home_record} | {home_pts} pts
  [same structure]

== SPECIAL TEAMS MATCHUP ==
  {away} PP ({pp_away}%) vs {home} PK ({pk_home}%)
  {home} PP ({pp_home}%) vs {away} PK ({pk_away}%)
  Penalties/Game: {away} {pim_away} | {home} {pim_home}
  Special Teams Edge: {st_edge_analysis}

== REST & SCHEDULE ==
  Rest Advantage: {rest_advantage}
  {away}: {schedule_context_away}
  {home}: {schedule_context_home}

== INJURIES ==
{away}: {injuries_away}
{home}: {injuries_home}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value? Factor in goalie matchup heavily.
2. PUCK LINE ({home} {pl_home}): Will the favorite win by 2+ goals? Extremely hard in hockey — factor in empty-net goal probability, score effects, and one-goal game frequency.
3. TOTAL (O/U {total_line}): Projected total goals. Factor in goalie quality, team pace, special teams, and score effects.
4. FIRST PERIOD: Who scores first? What's the projected 1P total? Early-game tempo and goalie cold-start effects.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low|medium|high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite NHL prediction system analyzing a game.
Simulate a panel of 6 expert analysts:

1. GOALTENDING ANALYST: Evaluates the goalie matchup — the single most important
   factor in hockey. Compare starter quality (GSAx), recent form, rest, and
   starter vs backup quality gap. A confirmed backup starting is the biggest
   edge in NHL betting.
2. EVEN-STRENGTH ANALYST: Evaluates 5-on-5 play. Corsi/Fenwick possession metrics,
   expected goals models, scoring chance quality, and defensive structure.
   Who controls play at even strength?
3. SPECIAL TEAMS ANALYST: Evaluates power play vs penalty kill matchup.
   A dominant PP (top 5) facing a weak PK (bottom 5) is a significant edge.
   Also evaluates penalty discipline and man-advantage frequency.
4. SCHEDULE & FATIGUE ANALYST: Evaluates rest days, back-to-backs, travel
   distance, time zones, and road trip length. Teams on B2Bs with travel
   show measurable decline, especially in the 3rd period.
5. MARKET ANALYST: Evaluates the betting lines for value. Is the moneyline
   properly pricing the goalie matchup? Is the total reflecting both teams'
   pace and goalie quality? Goalie confirmation timing creates a window.
6. CONTRARIAN: Challenges the consensus. Hockey is the highest-variance
   major sport — the "better team" loses 40%+ of games. What scenarios is
   the market underweighting? Is a backup goalie actually having a great
   season? Is a home favorite on a B2B being overvalued?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "goaltending", "pick": "TEAM", "reasoning": "..."},
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
    "puck_line": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_period": {
      "p1_home_win_prob": 0.XX,
      "p1_away_win_prob": 0.XX,
      "p1_projected_total": X.X,
      "p1_ml_value": "home|away|none",
      "p1_total_value": "over|under|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": X, "home": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
# Bet types for NHL
BET_SLOTS = ["moneyline", "puck_line", "total", "first_period_ml", "first_period_total"]

EDGE_THRESHOLDS = {
    "moneyline": 0.06,           # 6% min edge (higher than MLB due to variance)
    "puck_line": 0.08,           # 8% min edge (puck line is brutal — ~30% of games end 1-goal)
    "total": 0.06,               # 6% min edge
    "first_period_ml": 0.07,     # 7% min edge
    "first_period_total": 0.07,  # 7% min edge
}

# Kelly sizing — eighth-Kelly for NHL (highest variance major sport)
KELLY_FRACTION = 0.125
```

---

## Layer 5: Edge Detection Functions

```python
# check_moneyline_edge(sim, odds) — same pattern as MLB
# check_puck_line_edge(sim, odds) — same pattern as MLB run_line
#   - Puck line is -1.5/+1.5 (same as run line). Very hard to cover in hockey.
# check_total_edge(sim, odds) — same pattern as MLB total
#   - NHL totals typically 5.5 or 6.0
# check_p1_ml_edge(sim, odds) — same pattern as MLB F5 ML
# check_p1_total_edge(sim, odds) — same pattern as MLB F5 total
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade moneyline: straightforward winner comparison
#   - NOTE: Include OT/SO wins as wins (they count for moneyline)
# Grade puck_line: final score (including OT/SO) adjusted by spread
#   - E.g., Home -1.5, final 3-2 OT → Home adjusted 1.5-2 → Home doesn't cover
#   - E.g., Home -1.5, final 4-2 → Home adjusted 2.5-2 → Home covers
# Grade total: total goals (including OT/SO goals) vs line
# Grade first_period: 1st period score comparison
#   - Many 1st periods end 0-0 or 1-0 — high draw rate
```

---

## Config Adaptations

```python
# API — NHL API is free, no key needed
NHL_API_BASE = "https://api-web.nhle.com/v1"
DAILY_FACEOFF_BASE = "https://www.dailyfaceoff.com"
MONEYPUCK_BASE = "https://moneypuck.com"
ODDS_SPORT_KEY = "icehockey_nhl"

# 32 NHL teams
TEAM_ABBREVS = [
    "ANA", "ARI", "BOS", "BUF", "CGY", "CAR", "CHI", "COL",
    "CBJ", "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL",
    "NSH", "NJD", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS",
    "SEA", "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WSH",
]

GAME_TIMEOUT = 300
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
```

---

## Key Differences From MLB

1. **Goalie = starting pitcher**: The goalie matchup is the single biggest factor, just like pitcher matchup in MLB. The GOALIE scraper is critical. Confirmed starter vs backup can swing a line 20-30 cents.
2. **Goalie confirmation timing edge**: Starters confirmed ~90 min before puck drop. Lines adjust but not always fully. Your pipeline should run AFTER confirmation for maximum edge. This is the equivalent of knowing the pitcher.
3. **Highest variance**: ~53% of a team's record is luck. Even the best model will lose 40%+ of bets. Use eighth-Kelly (0.125) and expect extended drawdowns.
4. **Puck line is painful**: ~30% of NHL games end with a 1-goal margin. The -1.5 puck line is very hard to cover. Set the threshold high (8%+).
5. **Special teams are a distinct factor**: PP/PK matchups don't exist in MLB. A top-5 PP vs bottom-5 PK is one of the most reliable edges in hockey.
6. **Overtime distorts grading**: OT/SO goals count for moneyline and total but not always for period bets. Handle this carefully in results grading.
7. **Score effects**: Teams trailing play more aggressively (pull goalie). This affects late-game scoring patterns and total bets.
8. **First period replaces F5 innings**: Same concept but 1 period (~33% of game) vs 5 innings (~56% of game). More variance in 1P.
9. **Free API**: The NHL API requires no key, unlike MLB Stats API. MoneyPuck provides free advanced stats CSVs.
