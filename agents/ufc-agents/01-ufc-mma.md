# MiroFish UFC/MMA Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for UFC/MMA fights. The system uses a 6-model LLM ensemble with adversarial challenge to predict fight outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for UFC/MMA.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Event & Fight Card
- Source: UFC API or scrape UFCStats.com
- Returns: list of upcoming fights with fighter names, weight class, card position (main/prelim), event name, date
- Also useful: whether it's a PPV/Fight Night, number of rounds (3 or 5)

### scrapers/fighters.py — Fighter Profiles
- Source: UFCStats.com (scrape) or Fighting Tomatoes API (free tier, 200 req/month)
- Per fighter, return:
  - Record (W-L-D, wins by KO/sub/dec)
  - Significant strikes landed/attempted per minute
  - Striking accuracy %
  - Takedown average per 15 min
  - Takedown defense %
  - Submission attempts per 15 min
  - Reach (inches), height, stance (orthodox/southpaw)
  - Average fight time
  - Recent fight history (last 5 fights: opponent, result, method, round, date)
  - Win/loss streak
  - Age
- GitHub scrapers: Greco1899/scrape_ufc_stats, UFCscraper (ReadTheDocs)

### scrapers/odds.py — Betting Odds
- Source: The Odds API (already have ODDS_API_KEY)
- Sport key: `mma_mixed_martial_arts`
- Fetch: moneyline, over/under rounds (if available), method of victory props
- Return OddsData dataclass with:
  - fighter_a, fighter_b
  - moneyline: {fighter_a: price, fighter_b: price}
  - total_rounds: {line: X.5, over_odds: price, under_odds: price}
  - implied_probs: {fighter_a: prob, fighter_b: prob} (vig-removed)

### scrapers/news.py — Fight Context
- Source: MMA news sites, social media, press conferences (web search or RSS)
- Returns per fight:
  - Camp/gym information and recent changes
  - Weight cut reports (missed weight history, weigh-in appearance)
  - Injury reports
  - Layoff duration (days since last fight)
  - Short-notice replacement flag
  - Notable quotes about preparation/motivation

### scrapers/rankings.py — Current Rankings
- Source: UFC API or scrape ufc.com/rankings
- Returns: current pound-for-pound and divisional rankings
- Useful for gauging relative quality and motivation (title shot implications)

---

## Layer 2: Briefing Template

```
UFC FIGHT PREDICTION ANALYSIS
==============================
{event_name} — {date}
{fighter_a} vs {fighter_b} | {weight_class} | {rounds} rounds

BETTING LINES:
  Moneyline: {fighter_a} {ml_a} / {fighter_b} {ml_b}
  Total Rounds: {line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {fighter_a} {prob_a:.1%} / {fighter_b} {prob_b:.1%}

== FIGHTER PROFILES ==

{fighter_a} — Record: {record_a}
  Wins: {ko_a} KO | {sub_a} SUB | {dec_a} DEC
  Stance: {stance_a} | Height: {height_a} | Reach: {reach_a}"
  Sig. Strikes Landed/Min: {slpm_a} | Striking Accuracy: {str_acc_a}%
  Takedown Avg/15min: {td_avg_a} | Takedown Defense: {td_def_a}%
  Submission Avg/15min: {sub_avg_a} | Avg Fight Time: {avg_time_a}
  Age: {age_a} | Days Since Last Fight: {layoff_a}
  Current Streak: {streak_a}
  Last 5 Fights:
    {date} vs {opp}: {result} via {method} (R{round})
    ...

{fighter_b} — Record: {record_b}
  [same structure]

== CONTEXT ==
  Card Position: {main_event|co_main|main_card|prelim}
  Rankings: {fighter_a} #{rank_a} / {fighter_b} #{rank_b} at {weight_class}
  Camp Notes: {camp_info}
  Weight Cut Notes: {weight_cut_info}
  Short Notice: {yes/no}

== INJURIES ==
{fighter_a}: {injury_info_a}
{fighter_b}: {injury_info_b}

== PREDICTION TASK ==
Analyze this fight from multiple expert perspectives and provide predictions for ALL of the following:

1. FIGHT WINNER: Win probability for each fighter. Which side has moneyline value?
2. TOTAL ROUNDS (O/U {line}): Will this fight go the distance or end early? Factor in finishing rates, cardio, and style matchup.
3. METHOD OF VICTORY: Most likely method (KO/TKO, Submission, Decision). Where does the value lie?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite UFC/MMA prediction system analyzing a fight.
Simulate a panel of 6 expert analysts:

1. STRIKING ANALYST: Evaluates stand-up technique, volume, accuracy, power,
   range management, and how each fighter's striking style matches up.
   Orthodox vs southpaw dynamics, reach advantages, and distance fighting.
2. GRAPPLING ANALYST: Evaluates wrestling pedigree, takedown offense/defense,
   submission threats, ground control, and scrambling ability.
   How does the grappling matchup determine where the fight takes place?
3. CARDIO & DURABILITY ANALYST: Evaluates gas tank, chin durability,
   fight pace sustainability, and round-by-round performance trends.
   Who fades? Who gets stronger as the fight progresses?
4. STYLE MATCHUP ANALYST: Evaluates how the specific styles interact.
   Pressure vs counter-striker, wrestler vs anti-wrestler, etc.
   What is the path to victory for each fighter?
5. MARKET ANALYST: Evaluates the betting lines for value. Where is the
   public money likely flowing? Is the favorite over-valued due to name recognition?
   Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What is the obvious narrative
   that might be wrong? What upset scenario is under-priced?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "striking", "pick": "FIGHTER", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "fighter_a_win_prob": 0.XX,
      "fighter_b_win_prob": 0.XX,
      "value_side": "fighter_a|fighter_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_rounds": {
      "projected_rounds": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "method": {
      "ko_tko_prob": 0.XX,
      "submission_prob": 0.XX,
      "decision_prob": 0.XX,
      "most_likely": "KO/TKO|Submission|Decision",
      "value_method": "ko|sub|dec|none",
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "FIGHTER", "method": "METHOD", "round": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
# Bet types for UFC
BET_SLOTS = ["moneyline", "total_rounds", "method"]

EDGE_THRESHOLDS = {
    "moneyline": 0.06,        # 6% min edge (higher variance than team sports)
    "total_rounds": 0.06,     # 6% min edge
    "method": 0.08,           # 8% min edge (hardest to predict, softest lines)
}

# Kelly sizing — use eighth-Kelly for UFC (higher variance than team sports)
KELLY_FRACTION = 0.125
```

---

## Layer 5: Edge Detection Functions

```python
# check_moneyline_edge(sim, odds) — same as MLB, compare fighter_a/b win probs vs implied
# check_total_rounds_edge(sim, odds) — same pattern as MLB total, over/under rounds
# check_method_edge(sim, odds) — NEW: compare method probs vs method market odds
#   - Only signal if a specific method's probability exceeds market implied by threshold
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade moneyline: straightforward winner comparison
# Grade total_rounds: compare actual rounds/method to over/under line
#   - If fight ends in round <= line → under wins
#   - If fight goes past line → over wins
#   - Decision = max rounds (3 or 5) → over wins if line < max
# Grade method: match actual method (KO/TKO, Submission, Decision) to bet
```

---

## Config Adaptations

```python
# API
UFC_STATS_BASE = "http://ufcstats.com/statistics/events/completed"
ODDS_SPORT_KEY = "mma_mixed_martial_arts"

# No park factors or weather — fights are indoors
# No team abbreviations — use fighter names as identifiers

# Event timeout: fights are individual, less data per event
GAME_TIMEOUT = 180  # 3 min per fight analysis

# Ensemble same as MLB
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
```

---

## Key Differences From MLB

1. **Individual sport**: Matchup is 1v1, not team vs team. Fighter profiles replace team/pitcher profiles.
2. **Style matchup is king**: The LLM prompt emphasizes HOW styles interact, not just raw stats. This is where LLM reasoning adds the most value vs traditional models.
3. **Lower volume**: ~500 fights/year vs ~2,430 MLB games. Compensate with multiple bet types per fight.
4. **Higher variance**: Single-strike KOs create noise. Use eighth-Kelly (0.125) instead of quarter-Kelly.
5. **Narrative-heavy**: Camp changes, weight cuts, layoffs, motivation — these qualitative factors matter more than in any team sport. The briefing should include as much context as possible.
6. **No sub-period markets**: No equivalent to F5 innings. Replace with method of victory.
7. **Data sparsity**: Fighters fight 2-3x/year. Career stats + recent form are all you get. LLMs compensate by reasoning from context.
